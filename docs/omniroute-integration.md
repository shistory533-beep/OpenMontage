# OmniRoute upstream integration — FREE-AUTO (verified 2026-10-08)

Architecture preserved: OpenCode → FREE-AUTO (port 4100) → upstream candidates.
OmniRoute is NOT the new router of record. FREE-AUTO remains the adapter.

## Runtime status
- Installed: omniroute@3.8.51 (global npm)
- Server: running on 0.0.0.0:20128 (started via `omniroute serve --port 20128`)
- Health (CLI): healthy (version 3.8.51, uptime stable)
- Catalog: 358 models; configuredCount=0; activeCount=0 (no provider connections configured yet)
- /v1/models: returns auth-required (admin/inference split — documented, not a failure)
- /health: HTML dashboard responds (Next.js); /v1/health not defined
- No secrets exposed; STORAGE_ENCRYPTION_KEY lives only in ~/.omniroute/.env

## Catalog findings (conservative — do NOT add paid/unverified)
- Catalog count: 358 total; no provider connections active.
- Because configuredCount=0, nothing is verified runnable yet.
- Only verified free-tier upstreams will be added to FREE-AUTO registry.
- Paid-only / unverified models excluded per instruction.

## OpenCode integration (documented mechanism, not replacement)
- Documented command: `omniroute setup-opencode` generates an openai-compatible provider entry.
- Existing opencode.json preserved; `free-auto` remains primary provider.
- Integration path if needed: add `omniroute` provider alongside `free-auto` (baseURL `http://localhost:20128/v1`); do NOT remove `free-auto`.
- No API keys configured; no secrets in opencode.json.

## FREE-AUTO upstream preparation
- Gateway name for registry: `omniroute`
- Base URL: `http://localhost:20128/v1`
- No verified free model added yet because no provider connection is active (configuredCount=0). Once a verified free upstream is configured, add a conservative model entry to `lib/free_auto/model_registry.json` with `gateway: omniroute`, `free_tier: free`, and verified `base_url_env` / `api_key_env`.
- Fallback/error behavior: FREE-AUTO `complete()` tries ranked candidates; if `omniroute` fails (connection refused / 503 due to unconfigured provider), it falls back to next eligible upstream (existing `kilo`/`openrouter`/`bytez` candidates) — same retry/retryable logic already present.

## Blockers / next
- OmniRoute catalog exists but no upstream connections configured → no verified free model to bind yet.
- /v1/models requires auth (management plane vs inference plane); inference `/v1/chat/completions` remains available per server doc.
- Next: configure at least one verified free provider connection in OmniRoute, verify with minimal chat request, then add one conservative `omniroute` upstream entry to FREE-AUTO registry with `free_tier: free`.
