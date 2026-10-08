# Verified FREE-ONLY Audit — OmniRoute / FREE-AUTO (2026-10-08)

Source authority (read directly; no synthesis from memory):
- `lib/free_auto/omniroute-verified-free.json`
- `lib/free_auto/omniroute-upstream.json`
- `lib/free_auto/omniroute-ranking.md`
- `docs/omniroute-integration.md`
- Real endpoint probes (`omniroute health --output json`; `curl` to `localhost:20128/v1/`)
- DB state (`provider_connections` active = 0; verified_models = [])

Hard rules applied:
- ONLY VERIFIED_FREE / genuinely recurring free access.
- EXCLUDE paid-only, trial-credit-only, one-time-credit-only, unknown-status, deprecated tiers, providers requiring payment after small trial.
- Only free MODELS listed per provider (provider-level free tier ≠ model-level free).
- Evidence must cite source file / endpoint response, not assumption.

## Actual repository state (evidence)

`omniroute-verified-free.json` (line 1):
```
"verified_free_models": []
```
`omniroute-upstream.json`:
```
"verified_models": []
"free_tier": "unknown (no verified connection)"
"auth_state": "AUTH_REQUIRED (all providers need configured connection + credentials; DB provider_connections=0)"
"availability": "NOT_CONFIGURED (server healthy; inference plane responds; no upstream configured)"
```
`omniroute-ranking.md` (line 3):
```
Ranked verified free candidates from omniroute: 0 (configuredCount=0; no active connection; no verified free tier).
```
Real inference attempts (all 401 or 400):
- openrouter/gemini-2.5-flash-preview: 401 (no active credentials)
- together/google/gemma-3-4b-it: 401
- groq/llama3-8b-8192: 401
- gemini-api/gemini-2.5-flash-preview: 401
- pollinations/google/gemma-3-4b-it: 400 (invalid alias / no verified mapping)
- cloudflare-workers/gemma-3-4b: 401
- devin-cli-agentic: 400 (no provider/model prefix)
- auto (catalog routing): 502 (routes to catalog models requiring auth)

DB: `provider_connections` active = 0 (confirmed via `omniroute health` + `.env` files + `tests/smoke_omniroute_full.py`).
No `model_registry.json` mutation performed (verified by smoke test `tests/smoke_omniroute_upstream.py`).

## Conclusion

Number of genuinely verified, recurring-free models available right now: **0**.

Every provider/model mentioned in repository docs (openrouter, together, groq, gemini-api, pollinations, cloudflare-workers, opencode contract-only, devin-cli-agentic, auto/catalog) either requires active credentials (401) or has no verified mapping (400/502). There are zero recurring free quotas verified by real inference.

Because the user rules say "If a provider has both free and paid models, list ONLY the free models" and "Do not include a model just because the provider itself has a free tier" — and because zero free models are verified — the clean output below contains NO included models.

---

## Clean ranked list (FREE ONLY)

No rows qualify. All are EXCLUDED below with reason + evidence file.

| Rank | Provider | Model | Free quota | Auth required | Context | Coding | Reasoning | Agent/Tools | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| EXCLUDED | openrouter | (all) | UNKNOWN / unverified | YES (401) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | EXCLUDED — no active connection; all real requests 401 | `omniroute-verified-free.json` (401); `omniroute-upstream.json` |
| EXCLUDED | together | (all) | UNKNOWN / unverified | YES (401) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | EXCLUDED — no active connection; 401 | `omniroute-verified-free.json` |
| EXCLUDED | groq | (all) | UNKNOWN / unverified | YES (401) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | EXCLUDED — no active connection; 401 | `omniroute-verified-free.json` |
| EXCLUDED | gemini-api | (all) | UNKNOWN / unverified | YES (401) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | EXCLUDED — no active connection; 401 | `omniroute-verified-free.json` |
| EXCLUDED | pollinations | google/gemma-3-4b-it | UNKNOWN / invalid alias | N/A (400) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | EXCLUDED — 400 invalid alias; no verified mapping | `omniroute-verified-free.json` |
| EXCLUDED | cloudflare-workers | gemma-3-4b | UNKNOWN / unverified | YES (401) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | EXCLUDED — 401; no verified connection | `omniroute-verified-free.json` |
| EXCLUDED | opencode (contract) | (free-tier only per `noauth.ts`) | UNKNOWN / unverified locally | NONE (client-contract) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | EXCLUDED — contract free note unverified at localhost:20128; no 200 response recorded; `verified_models` = [] | `docs/omniroute-free-provider-priority.md`; `omniroute-verified-free.json` |
| EXCLUDED | devin-cli-agentic | (no prefix/model) | UNKNOWN | N/A | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | EXCLUDED — 400 (unknown provider/model prefix) | `omniroute-verified-free.json` |
| EXCLUDED | cloudflare-playground | (not mapped) | UNKNOWN | N/A | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | EXCLUDED — 400 (unknown provider/model) | `omniroute-verified-free.json` |
| EXCLUDED | auto / catalog routing | 358 models in catalog | UNKNOWN / requires auth per routing | YES (indirect via auth-required upstreams) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | EXCLUDED — `auto` test returned 502; all routed upstreams require auth; `verified_models` = [] | `omniroute-verified-free.json`; `omniroute-upstream.json` |

## Required lists (only genuinely free = verified; none exist)

### 1. TOP 50 genuinely free models
`[]` (empty array). Zero verified.

### 2. TOP 20 best free coding models
`[]` (empty array). Zero verified; no coding-capability verification performed (would require live 200 response + tool-output inspection; none occurred).

### 3. TOP 20 best free reasoning models
`[]` (empty array). Zero verified.

### 4. TOP 10 best free agent/tool models
`[]` (empty array). Zero verified; agent/tool capability requires verified upstream + real tool-use test; none performed.

### 5. TOP 10 best free models with largest recurring quotas
`[]` (empty array). Zero verified; no recurring quota verified by inference (`verified_requests` shows 0 successful requests; all 401/400/502).

---

## Inventory of what is NOT included (to prevent future confusion)

- `opencode` (contract-only “no auth” note in `noauth.ts`) — NOT included. No 200 verified at localhost:20128; no `verified_models` entry; `omniroute-verified-free.json` records zero verified models. Listed as EXCLUDED.
- Any model mentioned in docs (`omniroute-api-key-top50.md`) that relies on future `provider_connections` setup — EXCLUDED until `omniroute health` shows active connections AND `/v1/chat/completions` returns 200 for that exact provider/model AND entry is added to `omniroute-verified-free.json`.
- `free-auto` candidate ranking file (`omniroute-candidate.md`) — contains no verified live upstream; used only as planning reference, not evidence of free access.
- Any trial/credit references (e.g., “15% extra credits on first top-up”, “signup credit”, “one-time purchase grants 6 months”) — excluded by user rule (trial/one-time excluded).
- Any “catalog has 358 models” claim — excluded; catalog size ≠ verified free access; `verified_models` = [].

## Verification commands run (reproducible)

```
cat lib/free_auto/omniroute-verified-free.json
cat lib/free_auto/omniroute-upstream.json
omniroute health --output json
cat lib/free_auto/omniroute-ranking.md
python -c "from tools.tool_registry import registry; registry.discover(); ..." (provider_menu_summary checked; no free-only upstream registered)
```

No fabricated quotas. No fabricated free tiers. Only `verified_models: []` and 401/400/502 response records are cited.
