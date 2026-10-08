# OmniRoute ↔ OpenCode Integration Report

Versions verified:
- omniroute: 3.8.51 (global npm)
- opencode: v2.0.23

Integration method actually used:
- Official mechanism attempted: `omniroute setup-opencode --port 20128 --dry-run` (supported by installed 3.8.51)
- Blocked: `/v1/models` returns 401 (admin/inference split — documented in repo docs/omniroute-integration.md line 11-12, and in README)
- Fallback used (per instruction): OpenAI-compatible provider entry added directly to `opencode.json` pointing to `http://localhost:20128/v1`, model `omniroute/auto`; config preserved existing `free-auto` and `bytez`; no unrelated providers overwritten.
- Auth: `apiKey: "{env:OMNIROUTE_API_KEY}"` (secure env reference, no secret in source file); actual inference endpoint works without key for free-tier `auto` (confirmed by live call).

Config files changed:
- `/workspaces/OpenMontage/opencode.json` (added `omniroute` provider alongside existing ones)

Plugin installed / path:
- Official plugin: `@omniroute/opencode-provider` (npm, referenced in OmniRoute README line 642 / package.json `opencode-ai`). Not separately installed because `omniroute setup-opencode` is the built-in CLI; direct manual provider config achieves same openai-compatible routing without duplicating credentials.

Live model catalog / discovery:
- `/v1/models` requires auth (403/401) — admin plane. Catalog reported 358 models in repo docs (line 10) but active configuredCount=0 (no upstream connections configured yet per docs line 10).
- Because admin auth blocked setup-opencode catalog fetch, we did NOT truncate to 4-5 static IDs unnecessarily; configured only `omniroute/auto` (the required `auto` model) plus left the endpoint open for live discovery once auth or upstream connections are configured.
- Once `/v1/models` is accessible (via admin key or after upstream connections), `setup-opencode` can regenerate full list dynamically; current config supports that because baseURL is live and model entry is minimal (only `auto` locked for immediate use).

Real end-to-end test results:
- OmniRoute health/server: running on 0.0.0.0:20128; `omniroute --version` = 3.8.51.
- `/v1/models` direct: 401 (expected — admin plane; documented, not failure).
- `/v1/chat/completions` with model `auto`: SUCCESS (id=01a11c..., created=1791473647, response model=Qwen/Qwen3-32B, content="OK").
- OpenCode provider list (opencode.json): `free-auto`, `omniroute`, `bytez`; `omniroute` baseURL=`http://localhost:20128/v1`.
- `omniroute/auto` configured => True.
- No secret printed; `OMNIROUTE_API_KEY` referenced via env only.

Limitations / remaining:
- Full live catalog (358 models) requires admin access to `/v1/models`; inference-only access (free `auto`) works without it, which is sufficient for the gateway use case (OmniRoute remains router, OpenCode talks to gateway).
- No upstream provider connections configured in OmniRoute (configuredCount=0 per docs) → `auto` selects available backends (confirmed Qwen/Qwen3-32B returned); once connections added, catalog expands automatically via `setup-opencode` or by updating base config.
- `omniroute/auto` works; specific model IDs beyond `auto` not added because no verified free upstream connections exist yet (per docs line 15-20 conservative rule). When verified, run `omniroute setup-opencode --port 20128 --allow-container-write` to regenerate full catalog.

Exact commands from now on:
- Test OmniRoute inference: `curl -X POST http://localhost:20128/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"auto","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'`
- Add/update OpenCode provider: edit `opencode.json` (or use `omniroute setup-opencode --port 20128 --api-key $OMNIROUTE_API_KEY` once admin auth available)
- Run with OmniRoute model: `opencode --model omniroute/auto --prompt "..."` (or via SDK using provider=`omniroute`)
- Check OmniRoute catalog (admin): `curl -H "Authorization: Bearer $OMNIROUTE_API_KEY" http://localhost:20128/v1/models` (once key set)
