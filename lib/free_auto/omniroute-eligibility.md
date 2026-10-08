# FREE-AUTO eligibility diagnostics — OmniRoute upstream (verified 2026-10-08)

- Gateway: omniroute
- Runtime server: healthy (localhost:20128, HTML dashboard 200)
- CLI health: healthy (3.8.51, configuredCount=0, activeCount=0, catalogCount=358)
- /v1/models: 401 auth-required (documented admin/inference split) — does NOT block inference plane
- Provider connections (DB): 0 active
- Provider nodes (DB): 0
- Model context overrides (DB): 0
- Verified free upstream model: 0
- Auth required: yes (OMNIROUTE_API_KEY not set; no connection configured)
- Availability: UNAVAILABLE (no configured provider connections)
- Free tier verified: UNKNOWN (catalog contains free/paid/unknown; no verified connection)
- Deprecated/retired: qwen-web, chatgpt-web, felo-web, felo, msdesigner (trigger-enforced)
- Fallback behavior: FREE-AUTO tries ranked candidates; if omniroute unavailable (connection missing / auth missing), fall back to next eligible upstream (kilo/openrouter/bytez/native) — same retry/retryable logic as gateway.
- Infinite retry prevention: since verified_models=0 for omniroute, it cannot dominate ranking; FREE-AUTO's `rank_candidates()` will skip it if health_key not eligible (same as any upstream with zero candidates).
- Benchmark scores: none assigned (no verified model; no scores invented)
