# Bytez First-Class Provider Integration — Plan (T2)

Date: 2026-10-08. Owner: Build. Status: PLAN → BUILD.

## Objective
Bytez appears by name in OpenCode with `BYTEZ_API_KEY` auth, and its
FREE-ELIGIBLE models route through FREE-AUTO with full health/telemetry —
without fakes, without breaking kilo/openrouter.

## Evidence (official sources, verified 2026-10-08)
- OpenAI-compat baseURL `https://api.bytez.com/models/v2/openai/v1`
  (docs.bytez.com chat-completions example, JS/Python/curl agree).
- Auth: `Authorization` header with Bytez key; OpenAI SDK `apiKey` works
  → `Bearer` accepted. Our `urllib_transport` (Bearer) is compatible.
- Billing (docs.bytez.com/model-api/docs/billing): free = $1 credits per
  4 weeks, open models **≤7B params**, 1 concurrent request. Nothing is
  price-free → `free_tier` is NEVER `"free"` on Bytez; eligible = unknown.
  Paid-only = >7B open models + all closed-source (provider-key) models.
- Model IDs attested in official sources ONLY:
  `Qwen/Qwen3-4B` (Bytez docs), `google/gemma-3-4b-it` (LiteLLM docs).
  Both ≤7B. No other IDs invented. `/models` needs a key (401 without).
- OpenCode mechanism (opencode.ai/docs/providers, official patterns for
  Atomic Chat/Ollama/LM-Studio/Poolside-deployment): custom provider in
  `opencode.json` with `npm:@ai-sdk/openai-compatible` + `name` +
  `options.baseURL` + `options.apiKey:"{env:BYTEZ_API_KEY}"` + `models` map.
  This surfaces Bytez BY NAME in the picker. `/connect` named listing comes
  from Models.dev built-ins; Bytez is absent there (226 providers checked) →
  named-/connect-by-default belongs upstream (rule 12, §7).

## Steps
1. [x] Audit + official-source verification (above).
2. [x] `opencode.json`: bytez provider added; `opencode models` lists
   `bytez/Qwen/Qwen3-4B`, `bytez/google/gemma-3-4b-it`, `free-auto/free-auto`.
3. [x] `model_registry.json`: `qwen3-4b`, `gemma-3-4b-it` (bytez-only,
   free_tier unknown, never free). 22 candidates total.
4. [x] Tests: `tests/test_free_auto_bytez.py` (6 tests: config guard,
   registry honesty, Bearer/base-URL transport, 401 failover + exhaustion,
   unconfigured-drops-out, loopback session affinity). 80/80 with suites.
5. [x] Verify: focused 80 → compile → loopback E2E (in-module) →
   real `opencode models` proof. Bytez live smoke: `/models` w/o key →
   HTTP 401 (AUTH_REQUIRED, recorded, not faked).
6. [x] Docs: catalog §3 Bytez + reliability bullet; ROUTER.md env note.
7. [ ] Commit; continue Apollo excerpt (highest prior task).

## Risks
- R1 Bearer vs bare-key auth: docs' own OpenAI-SDK example proves Bearer OK.
- R2 Only 2 models: thin but honest; live `/models` with a future key
  refreshes the list (document procedure, never hardcode more).
- R3 Existing `test_autoplan_workflow` opencode.json guard must stay green;
  extend, don't weaken.

## 7. Upstream integration point (rule 12)
Named `/connect` without local config requires Bytez in Models.dev
(`sst/models.dev` providers directory — PR adds provider + models), then an
OpenCode release pulling the catalog. Local `opencode.json` custom provider
is the complete legitimate in-repo mechanism; do not claim `/connect`-default.
