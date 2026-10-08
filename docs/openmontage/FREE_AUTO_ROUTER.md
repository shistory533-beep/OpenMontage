# FREE-AUTO Router

One selectable virtual model in OpenCode (`/models` → `FREE-AUTO`) that routes
each request to the best currently available free model automatically.

## Architecture

```
OpenCode /models: FREE-AUTO  (opencode.json -> free-auto provider)
        |
        v  POST /v1/chat/completions  (OpenAI-compatible, 127.0.0.1:4100)
lib/free_auto/gateway.py     virtual model `free-auto`
        |-- task_classify.py  coding | planning | research | multimodal |
        |                         fast_simple | general (deterministic)
        |-- registry.py + model_registry.json   capabilities, upstreams,
        |                         priors, benchmark source+date (null = prior only)
        |-- health.py         per-(candidate,gateway,model): failures, cooldown,
        |                         reset_at, quota, latency EMA, tool-call/SO rates
        |-- scoring.py        12 explainable components x per-task weights,
                              deterministic ranking
        |-- upstream POST     OpenRouter (https://openrouter.ai/api/v1) and/or
                              Kilo (KILO_BASE_URL) with user keys from env
```

`opencode.json` binds one virtual model ID to one local endpoint (an
OpenCode-level 1:1 constraint). The N-way fan-out lives in the gateway, so
no TUI changes are needed and the user's `/models` selection never changes
while the underlying model varies per request.

Start it with:

```bash
python3 -m lib.free_auto.gateway --host 127.0.0.1 --port 4100
```

Endpoints: `GET /v1/models`, `POST /v1/chat/completions` (streaming is
replayed as SSE from the completed response, so failover stays safe),
`GET /health`, `GET /status`.

## Agentic telemetry (live, not prior-only)

`health.py` tracks per-(candidate, gateway, model) tool-call and
structured-output demonstration probes. The router records them on every
successful 200 **only when the request explicitly asked for that capability**
(`payload["tools"]` / `response_format` of type `json_schema` or `json_object`),
so a candidate is never marked down for a capability nobody tested.

`score_candidate` folds that live rate into the `tool_use` /
`structured_output` scoring components, overriding the static registry prior
whenever telemetry exists. A candidate with no telemetry stays on its prior
(unknown != incapable). This is what lets FREE-AUTO demote a model that fails
every tool call instead of trusting an unmeasured 0.5 forever.

## Ranking model

Per request: classify → drop capability-incompatible → drop in-cooldown →
score → highest wins → on retryable failure, next candidate (never the same
upstream twice per request; attempts ≤ number of ranked candidates).

Score components (each 0–1): quality, coding, reasoning, agentic, tool_use,
structured_output, context, multimodal, reliability, latency, quota_health,
historical_success. Weights differ per task class
(see `TASK_WEIGHTS` in `lib/free_auto/scoring.py:28`); e.g. coding weights
coding 0.24/agentic 0.14, fast_simple weights latency 0.34. Unknown
capabilities score 0.5 with a confidence penalty, so untested models stay
eligible but rank below equally good measured ones. Experimental models take
an extra 0.9 confidence multiplier. Ties break deterministically
(total, confidence, initial_priority, id, gateway).

## Task classes

`coding`, `planning`, `research`, `multimodal`, `fast_simple`, `general`.
Keyword heuristic in `lib/free_auto/task_classify.py`; image content blocks
force `multimodal`. Pure function, unit-tested.

## Adaptive depth — complexity T0–T3 (v2)

`classify_task` also returns `complexity`: explicit `[T0]`–`[T3]` tag wins,
else a deterministic heuristic (length + class signals; coding floored at T1).
Per-request override via the `complexity` field (`"t0"`–`"t3"`); the effective
tier is echoed in `free_auto.complexity`. Scoring re-weight: T0 doubles the
latency voice, T3 boosts quality/reasoning/agentic ×1.5 (renormalized);
T1/T2/`None` reproduce base weights exactly. See `FREE_AUTO_CATALOG.md` §4
for the role policy (T0 fastest → T3 strongest, Explore cheap, Review
independent).

## Session affinity (v2)

Pass `session_id` per request: the session's last successful
(candidate, gateway, model) sorts first while still eligible, with
`(session-affine)` appended to the reason. Pins persist in the health JSON
(next to cooldowns, no secrets); an in-cooldown pin is skipped silently and a
failover winner re-pins automatically.

## Provider policy — free-tier preference (v2)

Upstream `free_tier` (`free|paid|unknown`, normalized) adjusts the total
(+0.03 free, −0.05 paid) without touching the 12-component table. Verified
2026-10-08: 5 registry IDs are paid on OpenRouter (see `FREE_AUTO_CATALOG.md`),
so those OpenRouter upstreams carry `paid` and Kilo is preferred there until
live telemetry says otherwise. New `:free` models carry OpenRouter `free`;
their Kilo slugs are mirrored-pattern UNVERIFIED (`unknown`).

## Latency EMA + TTFT (v2)

`latency_ms_ema` now blends 50/50 with the static latency class when measured
(thresholds 600/1500/3000/8000ms); unmeasured candidates stay on the static
prior. `record_ttft()` tracks streaming time-to-first-token EMA for future
use (the gateway is non-streaming today: it replays SSE from the completed
response, so TTFT is recorded only when a caller supplies it).

## Failure states

`transient`, `rate_limit`, `quota_exhausted`, `auth_failure`,
`invalid_request`, `provider_unavailable`, `model_unavailable`,
`capability_mismatch`, `timeout`. Only `auth_failure`,
`invalid_request`, `capability_mismatch` are non-retryable on the same
credential; everything else continues to the next candidate. HTTP mapping in
`lib/free_auto/health.py:classify_http_failure`.

## Quota / reset handling

429 with quota wording → `quota_exhausted`, 1h cooldown; plain 429 →
`rate_limit`, 60s (or `Retry-After`); `reset_at` parsed best-effort from
`Retry-After` / `X-RateLimit-Reset` headers and honored via `max(cooldown,
reset_at)`. Transient errors back off exponentially (5m doubling, capped
30m). A recovered provider rejoins automatically: cooldown expiry makes it
eligible again and the next routed request doubles as a lightweight probe
(`record_success` clears the streak); `router.probe()` issues an explicit
`max_tokens:1` ping. State persists at
`$FREE_AUTO_STATE_PATH` (default `~/.cache/openmontage/free-auto-health.json`)
and contains no secrets — only key env-var names.

Never rotate keys to evade limits: each (candidate, gateway) is tried at most
once per request and only user-configured credentials (`OPENROUTER_API_KEY`,
`KILO_API_KEY`, `KILO_BASE_URL`, `BYTEZ_API_KEY`, `BYTEZ_BASE_URL`) are used.

## /models integration

`opencode.json` declares provider `free-auto`
(`npm: @ai-sdk/openai-compatible`, `baseURL: http://127.0.0.1:4100/v1`)
with model `free-auto` named `FREE-AUTO`. Select it once in `/models` and
leave it; every request may land on a different upstream without touching the
selection.

## How to add / remove models

Edit `lib/free_auto/model_registry.json`: add an entry with `id`, `display`,
`category`, `upstreams[]` (gateway, model slug, `free_tier`, key/base envs),
`capabilities`, `priors`, `latency_class`, `benchmark{source,date,note}`,
`initial_priority`, `experimental`. Gateways are plain strings — `kilo`,
`openrouter`, `bytez` all work with zero code changes (key env + base URL
default per upstream). Routers (`openrouter/auto`,
`openrouter/free`, `kilo-auto/*`) and safety classifiers
(`nemotron-3.5-content-safety`) are rejected as leaf candidates by
`registry.py`. No code changes needed; scoring and health pick the entry up
automatically. `free_tier` must be `"free"` only when a `:free`/`-free`
marker was actually observed — otherwise `"unknown"`.

## How real telemetry changes ranking

`reliability` falls 0.25 per consecutive failure, `quota_health` drops to 0
in cooldown (filtered) or 0.3 when recently limited, `historical_success`
tracks success ratio, latency EMA feeds nothing directly today except the
static latency class (wired for future use). A 429 on the top pick therefore
demotes it below healthy peers on the very next request until cooldown/reset
expires, with the reason visible in `free_auto.reason` and `/status`.

## Observability

`GET /status` returns selected virtual model, current actual model,
provider, reason, candidate ranking, cooldowns, quota/reset, recent
failures, current task class. Full keys are never logged or returned.
