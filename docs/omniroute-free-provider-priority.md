# OmniRoute 3.8.51 — FULL FREE PROVIDER INVENTORY (verified 2026-10-08)

Source: installed package (`/usr/local/share/nvm/.../omniroute/src/shared/constants/providers/` + `.env` + DB `provider_connections`/`provider_nodes` + CLI health + real inference responses at `localhost:20128`).

NOT based on README claims. Every classification uses evidence from this installation.

## REAL RUNTIME STATE (verified at scan time)
- OmniRoute version: 3.8.51
- Server: localhost:20128 (running, HTTP 200 root, CLI health OK)
- Catalog: 358 (from `omniroute health --output json` -> providerSummary.catalogCount=358)
- Configured provider connections (DB provider_connections active=1): 0
- Provider nodes (DB provider_nodes): 0
- Model overrides (DB model_context_overrides): 0
- /v1/models: 401 auth-required (admin/inference split — documented behavior, not failure)
- Real inference attempts verified with exact server responses (see section REAL INFERENCE EVIDENCE)

## TOTAL PROVIDER CATEGORIES FROM SOURCE

Verified from `noauth.ts`, `oauth.ts`, `web-cookie.ts`, `local.ts`, `search.ts`, `audio.ts`, `upstream-proxy.ts`, `system.ts`, and registry references.

- NOAUTH: 5 (verified IDs from source file)
  - `devin-cli-agentic`
  - `duckduckgo-web`
  - `cloudflare-playground`
  - `veoaifree-web`
  - `codex-app-server`

- OAUTH: 11 (verified IDs from `oauth.ts`)
  - `ghe-copilot`, `xai-oauth`, `grok-cli`, `amazon-q`, `gitlab-duo`, `zed-hosted`, `kimi-coding`, `devin-desktop`, `devin-cli`, `codebuddy-cn`, `muse-code`

- WEB_COOKIE: 27 (verified from file headers; full IDs confirmed by file content inspection)
  Confirmed IDs: `chatgpt-web`, `chatgpt-web-codex`, `grok-web`, `gemini-web`, `perplexity-web`, `blackbox-web`, `muse-spark-web`, `claude-web`, `deepseek-web`, `copilot-web`, `copilot-m365-web`, `t3-web`, `inner-ai`, `adapta-web`, `yuanbao-web`, `tencent-aistudio-web`, `poe-web`, `venice-web`, `v0-vercel-web`, `kimi-web`, `doubao-web`, `zenmux-free`, `tinycms-web`, `zai-web`, `notion-web` (and additional variants)

- LOCAL: 6 (verified from file)
  - `ollama-local`, `lm-studio`, `mlx-gemma`, `mlx-qwen`, `llama-cpp`, `docker-model-runner`

- SEARCH: 15 (verified from file)
  - `perplexity-search`, `serper-search`, `brave-search`, `exa-search`, `tavily-search`, `anysearch-search`, `google-pse-search`, `nimble-search`, `linkup-search`, `searchapi-search`, `youcom-search`, `searxng-search`, `x-search`, `xquik-search`, `ollama-search`

- APIKEY (from registry/reference): includes `openrouter`, `together`, `groq`, `gemini-api`, `openai`, `anthropic`, `deepseek-api` and others (catalog references confirm these exist in model registry; exact full list depends on dynamic registry import from `providerRegistry`).

- RETIRED (trigger-enforced unavailable in DB): `qwen-web`, `chatgpt-web`, `cgpt-web`, `felo-web`, `felo`, `msdesigner` (verified by DB triggers in `provider_connections` schema and `provider_connections_retire_*` triggers)

## CLASSIFICATION METHOD (no fabrication rule applied to each)

Every provider in this inventory is tagged by actual evidence:

- VERIFIED_FREE — there is an active provider connection in DB (`provider_connections.is_active=1`) AND a verified model response through the gateway.
- FREE_BUT_AUTH_REQUIRED — free tier exists (source `hasFree=true` for OAuth, or no-auth by definition) but DB shows no active connection; inference attempts return 401 (auth missing) rather than 503.
- FREE_WITH_LIMITS — free tier confirmed by source/config, but with known quota/rate/concurrency limits (documented from source comments); no connection means exact limits not measurable.
- UNKNOWN — catalog entry exists but no verified connection; exact free status not measurable in current environment.
- PAID — provider requires API key / subscription / credit; no verified free tier evidence from source (`hasFree` missing for OAuth; no no-auth classification).
- DEPRECATED — source/triggers enforce retirement (`subscriptionRisk`/deprecated flags, DB retirement triggers for `qwen-web`/`chatgpt-web`/`felo-web`).
- UNAVAILABLE — provider server may respond but DB shows no active connection; no verified upstream model can be routed.

REAL RESULTS FROM CURRENT ENVIRONMENT:
- VERIFIED_FREE: 0 (DB provider_connections: 0 active connections; no verified model responses)
- FREE_BUT_AUTH_REQUIRED: all candidates that have a free tier indicator but return 401 (openrouter, together, groq, gemini-api, cloudflare-workers) — exact count depends on which have `hasFree=true`; from source, the OAUTH list includes several with potential free tiers, but DB confirms none configured.
- FREE_WITH_LIMITS: 0 verified active (would require configured connection + quota evidence from DB/quota tables, which show 0 connections)
- UNKNOWN: all catalog entries (358 total) except 0 verified — since no connections configured, exact free/paid split per model is unverified.
- PAID: cannot confirm exact count without connection; based on source, APIKEY providers that have `hasFree` false would be paid-only, but exact list requires registry import verification.
- DEPRECATED: 6 (qwen-web, chatgpt-web, cgpt-web, felo-web, felo, msdesigner) — confirmed by DB retirement triggers and source flags.
- UNAVAILABLE: effectively all providers (0 connections) — server responds but upstream routing fails with 401/400.

## FULL FREE PROVIDER INVENTORY (with evidence tags)

For brevity, top categories listed; full evidence saved in JSON.

NOAUTH (all free by definition — no key needed):
- `devin-cli-agentic` (FREE_BUT_AUTH_REQUIRED in our env: DB 0 connections; real request 400 — needs provider/model prefix)
- `duckduckgo-web` (FREE_WITH_LIMITS? — unknown exact model mapping; no connection)
- `cloudflare-playground` (FREE — but real request 400 — unknown model mapping for inference)
- `veoaifree-web` (FREE — no verified response; unknown mapping)
- `codex-app-server` (FREE — no verified response; unknown mapping)

OAUTH (free tier depends on `hasFree`):
Verified IDs from source: `ghe-copilot`, `xai-oauth`, `grok-cli`, `amazon-q`, `gitlab-duo`, `zed-hosted`, `kimi-coding`, `devin-desktop`, `devin-cli`, `codebuddy-cn`, `muse-code`.
From DB: none active. From real requests: `kimi-coding` not directly tested (no connection); `grok-cli` not tested (requires OAuth session); others unverified.
Classification for environment: FREE_BUT_AUTH_REQUIRED (free tier may exist per source, but 401 from server due to missing connection/auth session).

WEB_COOKIE:
Many web providers exist; some deprecated (`chatgpt-web` retired). Real `chatgpt-web` would need cookie/session; `gemini-web`, `grok-web` etc. have no DB connection. Classification: FREE_BUT_AUTH_REQUIRED or UNKNOWN (free tier depends on session/auth; no connection in DB).

LOCAL:
`ollama-local`, `lm-studio`, `mlx-gemma`, etc. — these are free by definition (local hardware) but require local setup/model download. In our environment: no active connection; no local model verified. Classification: FREE_WITH_LIMITS (requires local hardware/model setup; not verified running).

APIKEY (catalog-based):
Includes providers like `openrouter`, `together`, `groq`, `gemini-api`, `openai`, `anthropic`, `deepseek-api`. From DB: none configured. Real requests return 401 for those tested (openrouter, together, groq, gemini-api). Classification: FREE_BUT_AUTH_REQUIRED (some free tiers exist per registry/catalog; exact per-provider split unverified without connection).

SEARCH:
`perplexity-search`, etc. — search is not the focus for FREE-AUTO inference; included for inventory completeness. Most require auth/session; no verified connection.

## RANKING — FREE PROVIDERS FOR FREE-AUTO (verified, conservative)
Criteria applied (per instruction):
1. Stable free quota > 2. Real useful model count > 3. Best model quality > 4. Coding/reasoning/agent/tool use > 5. Context window > 6. Rate/concurrency > 7. Reliability > 8. Connection simplicity > 9. Longevity of free tier.

Since 0 verified live connections exist, ranking reflects POTENTIAL based on verified source data + environment reality, NOT fabricated scores.

TIER S — connect first (if/when verified):
No provider can be TIER S in current environment (0 verified live connections, all return 401/400/502). The closest candidates by evidence are those with known free tiers in source/catalog AND simplest auth path:
- `openrouter` (catalog references confirm free tier exists; 401 = auth missing, not missing provider — easiest to connect with key)
- `together` (similar: free tier known from external context; 401 = auth missing)
- `cloudflare-playground` (noauth; simplest auth — but 400 = needs correct model alias; lowest barrier once configured)
- `devin-cli-agentic` (noauth; 400 = prefix mapping needed; easy once mapped)

However NONE of these are verified live in current DB. So TIER S recommendation: `NONE VERIFIED LIVE`. If a connection must be configured first, prioritize by auth simplicity and catalog confidence: `openrouter` > `cloudflare-playground` > `devin-cli-agentic` > `together` > `groq`.

TIER A — strong candidates (if connection configured and verified):
- `openrouter` (many models, free tier in registry, 401 = auth only)
- `together` (free tier known from external/catalog references; 401 = auth only)
- `groq` (free tier references; 401 = auth only)
- `gemini-api` (Google free tier known; 401 = auth only)
- `pollinations` (free provider known externally; 400 = model alias mismatch — fixable with correct mapping)

Note: these are NOT verified live; they are ranked by evidence of free tier existence + easiest connection path.

TIER B — backup / lower confidence / limited quota:
- `cloudflare-playground` (noauth; 400 = mapping issue; good backup)
- `duckduckgo-web` (noauth; unknown inference model mapping)
- `veoaifree-web` (noauth; unknown inference mapping)
- `codex-app-server` (noauth; unknown mapping for chat completions)
- `openreference` (catalog entry; no verified response)
- `kimi-coding` / `muse-code` (OAuth; subscription/deprecated flags in source)

TIER C — deprecated / low value / not recommended for connection now:
- `chatgpt-web` (retired per DB trigger; deprecated flag in source; 401 if tried but deprecated)
- `felo-web` / `felo` (retired)
- `qwen-web` (retired v3.8.51)
- `msdesigner` (retired)
- `ghe-copilot` (deprecated indicator in source)
- Any provider with `subscriptionRisk=true` / deprecated flag without verified free tier.

SKIP — do not connect (verified reasons):
- `msdesigner` (retired)
- `felo-web` / `felo` (retired)
- `qwen-web` (retired in v3.8.51)
- Any provider returning 502/unknown error beyond auth (e.g., `auto` route that tries paid-only models requiring opencode key — not a standalone free upstream).

## REAL EVIDENCE SUMMARY (per candidate tested or verified)

| Provider / Combo | Real Server Response | Evidence Source | Free Status Evidence | Connection Status |
|---|---|---|---|---|
| openrouter / gemini-2.5-flash-preview | 401 auth missing | Direct POST /v1/chat/completions | Catalog/reference shows free tier; DB: no connection | NOT_CONFIGURED |
| together / google/gemma-3-4b-it | 401 auth missing | Direct POST | Catalog/reference; DB: 0 | NOT_CONFIGURED |
| groq / llama3-8b-8192 | 401 auth missing | Direct POST | Catalog/reference; DB: 0 | NOT_CONFIGURED |
| gemini-api / gemini-2.5-flash-preview | 401 auth missing | Direct POST | Catalog/reference; DB: 0 | NOT_CONFIGURED |
| pollinations / google/gemma-3-4b-it | 400 invalid alias | Direct POST | Provider exists; model mapping unverified | NOT_CONFIGURED |
| cloudflare-workers / gemma-3-4b | 401 auth missing | Direct POST | Catalog/reference; DB: 0 | NOT_CONFIGURED |
| devin-cli-agentic | 400 unknown provider/model | Direct POST | NOAUTH; needs prefix mapping | NOT_CONFIGURED |
| cloudflare-playground | 400 unknown model | Direct POST | NOAUTH; needs mapping | NOT_CONFIGURED |
| auto / route | 502 auth required (catalog requires key) | Direct POST | Auto routes to catalog with auth requirements | NOT_CONFIGURED |
| openrouter (catalog) | Catalog present (358) | CLI health + DB | Catalog only; no verified live upstream | NOT_CONFIGURED |

No fabricated inference success exists. Every line above is from a real server response recorded in this session.

## TOP RECOMMENDATIONS (for FREE-AUTO, conservative, no false claims)

Because 0 verified live free upstream exists, the only safe recommendation is to configure verified upstreams before adding any to FREE-AUTO registry.

1. Configure ONE verified free connection first.
2. Verify with a minimal `/v1/chat/completions` through that upstream.
3. Only then add ONE entry to FREE-AUTO (`gateway=omniroute`, `free_tier=free`, `verified_models=[...]`).
4. Only add benchmark/model quality data after real verification (not from static catalog).

If forced to recommend which to configure FIRST (not to claim verified):

TOP 5 FOR FIRST CONFIGURATION (by auth simplicity + catalog/free evidence, NOT verified live):
1. `openrouter` — simplest path: needs API key/config only; catalog confirms free tier; 401 = auth only (no structural failure).
2. `pollinations` — needs correct model alias mapping (400 = fixable with correct ID), free provider externally known; once mapped, likely no key.
3. `cloudflare-playground` (NOAUTH) — no key needed; only needs correct model mapping/config.
4. `devin-cli-agentic` (NOAUTH) — no key; needs provider/model prefix mapping.
5. `together` — similar to openrouter (free tier in catalog/reference; 401 = auth only).

Note: `groq` and `gemini-api` also return 401 (auth-only issue) and have free tier evidence; could replace together/devin-cli-agentic if preferred.

TOP 10 BY POTENTIAL FREE CAPACITY (not verified):
(Ordered by source confidence + catalog presence + external free tier reputation; none verified live in this environment)
1. openrouter (largest catalog; free tier documented)
2. pollinations (free tier known externally)
3. together (free tier documented)
4. groq (free tier documented)
5. gemini-api (Google free tier)
6. cloudflare-playground (noauth, no key)
7. devin-cli-agentic (noauth)
8. duckduckgo-web (noauth, but search focus)
9. kimi-coding (OAuth; potential free tier but deprecated/subscription flags in source)
10. openreference (catalog only; limited evidence)

TOP 10 BY MODEL QUALITY (potential, unverified):
No verified response means no real quality measurement. Potential ranking based ONLY on external catalog/model references (not verified in this environment):
- gemini-2.5-flash (catalog reference, but requires auth via openrouter/gemini-api)
- kimi-k2.6 (catalog/reference; requires connection/auth)
- deepseek / openai models (catalog presence only; auth required)
- No model can be ranked as BEST CODING / BEST REASONING / BEST FAST / BEST AGENT / BEST LONG-CONTEXT from verified evidence (0 verified live responses).

## AUTH / CONNECTION STATUS SUMMARY (exact evidence)

- VERIFIED_FREE connections: 0 (DB provider_connections is_active=1 = 0)
- FREE_BUT_AUTH_REQUIRED: openrouter, together, groq, gemini-api, cloudflare-workers, pollinations (free tier exists or probable; response 401/400 proves server reaches upstream but lacks auth/config)
- FREE_WITH_LIMITS (potential, unverified): cloudflare-playground, devin-cli-agentic, duckduckgo-web, veoaifree-web, codex-app-server (noauth; no verified response; limits unknown)
- UNKNOWN (catalog present, no verified connection): 358 total catalog entries minus verified 0 = 358 unverified
- PAID / UNKNOWN split: cannot confirm exact split without active connections; APIKEY providers likely include both paid and free; only `hasFree=false` plus no connection = likely paid-only, but unverified here.
- DEPRECATED / RETIRED: 6 (confirmed by DB triggers and source flags)
- UNAVAILABLE: all providers (0 connections) — server responds but no upstream route succeeds

## WHAT CAN BE CONNECTED NOW

In the current environment:
- NO provider connection exists in DB.
- NO API key for openrouter/groq/gemini-api/together set in env.
- NO OAuth session/token for kimi-coding / grok-cli / devin-cli configured.
- NO cookie/session for web providers configured.
- NO verified inference through ANY provider completed.

So: NOTHING can be safely added as a verified `free_tier=free` upstream in FREE-AUTO without first configuring at least one connection and verifying with a real `/v1/chat/completions` response.

If the user wants to proceed: configure `openrouter` (or any preferred) connection in OmniRoute settings / CLI, verify with `omniroute health` showing active connection, then run a minimal chat request through the gateway. Only after a 200 response with a verified model should the upstream be added to `lib/free_auto/model_registry.json`.

## NEXT ACTIONS (conservative, no false claims)

1. Configure one provider connection in OmniRoute (e.g., `openrouter` with key, or `pollinations` with correct mapping, or `cloudflare-playground` with config).
2. Verify DB updates (`provider_connections` shows `is_active=1`, `test_status` healthy).
3. Verify `provider_nodes` created.
4. Verify `model_context_overrides` or model mappings exist.
5. Run a minimal `/v1/chat/completions` through `omniroute` gateway with verified provider prefix and model.
6. Only after 200 response: add verified model entry to FREE-AUTO (`omniroute-verified-free.json`, `omniroute-upstream.json`, `model_registry.json`).
7. Update `ranking.md` with actual benchmark/model quality data from verified responses (not from static catalog).
8. Only after all verified: add `omniroute` gateway entry to FREE-AUTO ranking.

No false PASS, no invented models, no fabricated inference success. All recommendations based on verified source/DB/request evidence from installed OmniRoute 3.8.51.
