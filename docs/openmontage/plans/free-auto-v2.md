# FREE-AUTO v2 — Plan Artifact (T3)

Date: 2026-10-08. Owner: Build (lead engineer). Status: PLAN → BUILD.

## 1. Objective

Upgrade `lib/free_auto/` (one virtual model `free-auto` → N free upstreams over
Kilo + OpenRouter) into a token-efficient, self-routing, self-verifying
free-model system — without creating a second router. Extend in place:
task + complexity (T0–T3) routing, session affinity, capability gating,
provider:model health, 429/quota/reset/cooldown, TTFT/latency, fallback
cascade, provider policy, lightweight telemetry, benchmark + live-performance
scoring. Refresh the model catalog from live OpenRouter data, rank per role,
document, test, E2E, review.

## 2. Discovered constraints (repository reality, verified 2026-10-08)

- Router lives in `lib/free_auto/`: `gateway.py` (544L, sole server, port 4100),
  `registry.py`, `scoring.py` (12 components × per-TaskClass weights),
  `task_classify.py` (6 TaskClasses, keyword heuristic), `health.py`
  (FailureClass ×9, cooldowns, JSON persist, EMA latency), `model_registry.json`
  (10 seeds, all capabilities null, all benchmark.source null — priors only).
- `opencode.json` binds ONE virtual model → `http://127.0.0.1:4100/v1`.
  N-way fan-out must stay inside the gateway (OpenCode 1:1 constraint).
- `lib/scoring.py` is an UNRELATED media-provider scorer — do not touch/conflate.
- No API keys in env (`KILO_API_KEY`, `OPENROUTER_API_KEY` unset) → live
  completion smokes will be AUTH_REQUIRED; completions cannot be verified live.
  OpenRouter `GET /v1/models` is public (no key) — used for discovery.
- `tests/conftest.py` blocks non-loopback sockets in pytest; live tests must be
  `@pytest.mark.live_api` + `OPENMONTAGE_ALLOW_NETWORK=1`. Existing suite:
  `tests/test_free_auto_router.py` (~50 tests, mocked transports) +
  `tests/test_autoplan_workflow.py` — baseline 50 passed.
- Existing skills: `.opencode/skills/{repository-archaeology,
  implementation-verify,production-smoke}` — reuse; do NOT recreate.
  No Superpowers/ECC in repo. Only 1 agent file (`.opencode/agents/reviewer.md`).
- Gaps confirmed: `_redact()` defined never called; `latency_ms_ema` recorded
  but unused in scoring; `free_tier` recorded but unused in ranking;
  no session affinity; no T0–T3 complexity; no TTFT field; no measured
  benchmarks anywhere (honesty guard test exists — keep it).

## 3. Live discovery evidence (public OpenRouter /models, 2026-10-08)

- 467 models total; 16 with `:free` suffix (pricing 0/0).
- All 10 registry IDs still listed. BUT the 5 non-suffixed registry IDs are
  PAID on OpenRouter (prompt $0.10–0.30/M): `muse-spark-1.3-contributor`,
  `mimo-v2.6-flash`, `step-3.7-flash`, `ling-3.1-flash`, `longcat-2.0`.
  Their free status depends entirely on the Kilo upstream (unverifiable, no key).
- Verified capability signals (`supported_parameters` + context_length) for all
  10 registry models + 9 new `:free` models (see §7 catalog). `capabilities {}`
  empty on OpenRouter side; multimodal/vision not advertised — keep null.
- New `:free` models to add: `apodex-1.1-mini`, `ling-3.0-flash-sante`,
  `dots-3-note-preview`, `lfm-2.5-2.6b`, `nemotron-3.5-lightning`,
  `inkling` (big sibling of inkling-small), `laguna-xs-2.1`,
  `nemotron-3-nano-omni-30b-a3b-reasoning`, `gemma-4-26b-a4b-it`,
  `gemma-4-31b-it`. (`nemotron-3.5-content-safety` stays excluded: SAFETY_ONLY.)

## 4. Affected files / reuse

- Reuse as-is: `gateway.py` cascade/observability, `health.py` failure/cooldown
  model, `scoring.py` weight table shape, `registry.py` filter semantics
  (None = untested = eligible), `tests/test_free_auto_router.py` patterns,
  `.opencode/skills/{implementation-verify,production-smoke}` procedures.
- Extend (no new router): `task_classify.py` (+Complexity T0–T3),
  `scoring.py` (+complexity re-weight, +`free_tier` preference, +EMA latency
  blend), `health.py` (+TTFT field/recorder, +session pins),
  `registry.py` (+`free_tier` accessor/normalization),
  `gateway.py` (+session_id affinity, +complexity passthrough, +wire `_redact`),
  `model_registry.json` (+10 entries, +verified capabilities).
- Create: `docs/openmontage/FREE_AUTO_CATALOG.md` (catalog + benchmark sources
  + rankings), `.opencode/skills/free-auto/SKILL.md` (only missing high-value
  skill), `tests/test_free_auto_v2.py` (new behavior), this plan file.
- Update: `docs/openmontage/FREE_AUTO_ROUTER.md` (v2 deltas only).

## 5. Ordered implementation steps

1. [x] Understand + Explore (evidence packs, §2–§3). Baseline tests: 50 passed.
2. [ ] `task_classify.py`: add `Complexity` (T0/T1/T2/T3) — explicit `[Tt][0-3]`
       tag wins; else deterministic heuristic (length + class signals).
       `Classification` gains `complexity` (default T2). Pure function.
3. [ ] `health.py`: add `ttft_ms_ema` + `record_ttft()`; add `session_pins`
       dict + `pin_session()/pinned_for()` persisted in same JSON (no secrets).
4. [ ] `scoring.py`: `score_candidate(..., free_tier="unknown", complexity=None,
       latency_ema_ms=None)` — free→+0.03 total-equivalent boost via quota-adjacent
       component? NO new component (keep 12): apply as small total adjustment
       (+0.03 free / −0.05 paid, documented) so COMPONENTS/weights untouched.
       Complexity re-weight: T0 latency×2.0, T3 quality/reasoning/agentic×1.5,
       renormalized; None → identical scores (backward compat).
       Latency component: blend static class with EMA when present
       (0.5/0.5), EMA→score via thresholds (>8000ms→0.2, >3000→0.4, >1500→0.6,
       >600→0.75, else 0.9).
5. [ ] `registry.py`: `Upstream.free_tier` normalize (`free|paid|unknown`);
       `Registry.free_only()` helper (drops upstreams known-paid); keep entries.
6. [ ] `gateway.py`: `rank_for(..., complexity=None, session_id=None)` —
       pinned candidate (if eligible) sorts first with reason suffix
       `(session-affine)`; `complete()` accepts `extra.complexity` ("t0".."t3")
       + `extra.session_id`, pins successful candidate per session.
       Wire `_redact` on history/failure-log bodies. Plumb free_tier + EMA into
       `score_candidate`; pass measured latency EMA from health.
7. [ ] `model_registry.json`: add 10 new `:free` entries (openrouter upstream
       verified `free`; kilo upstream mirrored slug, `free_tier:"unknown"` —
       explicitly unverified). Backfill verified capabilities for ALL entries
       from OpenRouter evidence: `tool_use` (tools param), `structured_output`
       (response_format/structured_outputs), `reasoning`, `context_tokens`.
       Keep `benchmark.source:null` (no measured benchmarks — honesty guard stays
       green). Set paid-on-openrouter upstreams' `free_tier:"paid"` with note.
8. [ ] Benchmark research (web, ≤3 searches): record only sourced scores;
       expect sparse; "no reliable public benchmark found" is a valid result.
       Local benchmark without keys is impossible for completions → run
       deterministic local tasks instead: classification matrix + ranking
       determinism + fallback-path E2E (mock 429→success, mock timeout→next).
9. [ ] Rankings (transparent, dated, prior-based): global + 7 role rankings
       from benchmark prior (none → 0.5) + verified capabilities + latency class
       + context fit. No hardcoded Top-10 in code — rankings live in docs only.
10. [ ] Tests `tests/test_free_auto_v2.py`: complexity tags/heuristics,
       session pin/first-sort/expiry, free-tier boost/paid penalty,
       EMA latency blend, TTFT recorder, registry normalization + free filter,
       invalid/auth states unchanged, concurrency (ThreadingHTTPServer parallel
       Posts), OpenCode compat (envelope keys). Keep honesty-guard green.
11. [ ] E2E: start gateway loopback (empty env → 503 exhausted path proves
       wiring); mock-transport success + 429→failover→success; `GET /status`.
12. [ ] Docs: `FREE_AUTO_CATALOG.md` + ROUTER.md v2 deltas. Skill
       `.opencode/skills/free-auto/SKILL.md`.
13. [ ] Independent `reviewer` subagent → fix findings → re-verify (focused +
       related + full free-auto tests, py_compile).
14. [ ] Final report (STATUS…NEXT_STEP schema from mission).

## 6. Verification strategy

- Focused: `pytest tests/test_free_auto_v2.py tests/test_free_auto_router.py -q`.
- Related: `test_autoplan_workflow.py` + contracts touching opencode.json.
- Full relevant: whole `tests/test_free_auto*` + `python -m py_compile`.
- E2E loopback gateway (production-smoke: trivial "say ok", mock upstream).
- Fallback path: mock 429 on top candidate → success on next (non-destructive).
- No networked live completion tests (no keys; conftest guard respected).

## 7. Verified model catalog (OpenRouter evidence 2026-10-08; Kilo unverified)

| id (openrouter) | ctx | tools | SO | reasoning | status |
|---|---|---|---|---|---|
| meta/muse-spark-1.3-contributor | 1M | Y | Y | Y | PAID on OR ($0.10/M); Kilo-free assumed |
| xiaomi/mimo-v2.6-flash | 1.05M | Y | Y | Y | PAID on OR ($0.14/M); Kilo-free assumed |
| poolside/laguna-s-2.1:free | 262k | Y | – | Y | FREE |
| nvidia/nemotron-3-ultra-550b-a55b:free | 1M | Y | – | Y | FREE |
| nvidia/nemotron-3-super-120b-a12b:free | 262k | Y | Y | Y | FREE |
| thinkingmachines/inkling-small:free | 1M | Y | – | Y | FREE |
| stepfun/step-3.7-flash | 262k | Y | Y | Y | PAID on OR ($0.20/M); Kilo-free assumed |
| inclusionai/ling-3.1-flash | 262k | Y | – | Y | price 0/0 on OR listing (no :free suffix; treat unknown→keep) |
| cohere/north-mini-code:free | 256k | Y | – | Y | FREE |
| meituan/longcat-2.0 | 1M | Y | – | Y | PAID on OR ($0.30/M); Kilo-free assumed, experimental |
| NEW apodex/apodex-1.1-mini:free | 262k | Y | Y | Y | FREE |
| NEW inclusionai/ling-3.0-flash-sante:free | 262k | Y | – | Y | FREE |
| NEW dots-studio/dots-3-note-preview:free | 512k | Y | Y | Y | FREE |
| NEW liquid/lfm-2.5-2.6b:free | 65k | Y | Y | Y | FREE (small/fast) |
| NEW nvidia/nemotron-3.5-lightning:free | 1M | Y | – | Y | FREE |
| NEW thinkingmachines/inkling:free | 1M | Y | – | Y | FREE |
| NEW poolside/laguna-xs-2.1:free | 262k | Y | – | Y | FREE |
| NEW nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | 256k | Y | – | Y | FREE |
| NEW google/gemma-4-26b-a4b-it:free | 262k | Y | Y | Y | FREE |
| NEW google/gemma-4-31b-it:free | 262k | Y | Y | Y | FREE |

Vision/multimodal: no OpenRouter capability evidence → all `multimodal:null`.
Cloudflare/Google-direct/Keyless providers: no credentials or endpoints
configured in repo → documented as GAPS, not inventoried as candidates.

## 8. Risks / blockers

- R1 No keys → no live completion evidence; rankings stay prior-based. Mitigate:
  mark confidence accordingly, AUTH_REQUIRED recorded, E2E via mocks+loopback.
- R2 Kilo slugs for new models unverified (mirrored pattern). Mitigate:
  `free_tier:"unknown"`, documented; misconfigured kilo entries fail safe
  (per-upstream failure → failover, never fatal).
- R3 OpenRouter free lineup rotates; today's `:free` may lapse. Mitigate:
  `free_tier` is data; health demotes dead models automatically; note refresh
  procedure in docs.
- R4 Score-shape change could break existing tests. Mitigate: defaults preserve
  identical scores (complexity=None, free_tier unknown, no EMA); run baseline
  first (done: 50 passed).

## TODO state (mirrors todowrite; no todowrite tool in this runtime)

- [x] Understand → Explore → Plan artifact
- [x] Complexity T0–T3 in task_classify
- [x] TTFT + session pins in health
- [x] Scoring: complexity/free-tier/EMA
- [x] Registry: normalization + free_only
- [x] Gateway: session affinity + complexity + _redact
- [x] Registry JSON: +10 models, capability backfill
- [x] Benchmark research (web unavailable → honestly none) + local deterministic benchmark
- [x] Rankings (docs)
- [x] Tests v2 + full verify
- [x] E2E loopback + fallback path
- [x] Docs + free-auto skill
- [x] Review: subagent unavailable (provider free-tier restriction) → rigorous
      self-review (weights/determinism/honesty/no-secrets/no-upstream-leak all
      proven by script) → re-verify → Report

## Review ruling (self-review, reviewer subagent unreachable)

Finding: none critical. Backward compat preserved (40 legacy tests untouched
in behavior; 2 updated tests encode new data reality, intent preserved).
Design is token-efficient (no new router, ±0.03/∓0.05 scalar + renormalized
re-weight, pins advisory). Residual risks R1–R4 from §8 stand, plus R5:
reviewer subagent could not run — recommend an independent review pass when
provider access allows.

## Calibration 2026-10-08T02:34Z (plan change record)

Benchmark evidence found for 7/20 models (web research, sources + dates +
confidence in each entry's benchmark.note). Priors mapped as score/100 for
domain-matched standard benchmarks only (coding←SWE/DeepSWE, agentic←TB 2.1,
reasoning←GPQA); harness-incomparable figures (TB 4.0/hard, Lite, Pro-on-Flash)
recorded but unmapped. Honesty-guard test strengthened to require
source+date+score%+confidence on sourced entries. Rankings recalculated;
role tables updated in FREE_AUTO_CATALOG.md §3. Live probes still BLOCKED
(no keys) — no live telemetry in scores yet.
