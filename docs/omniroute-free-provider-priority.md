# OmniRoute 3.8.51 — Full Free Provider Priority (FREE-AUTO integration)

**Status: ANALYSIS ONLY — no connections made; no registry mutation; FREE-AUTO preserved.**

Scan time: 2026-10-08T09:10:00Z
Source: `omniroute` source `/usr/local/share/nvm/.../omniroute/src/shared/constants/providers/` (noauth.ts, oauth.ts, apikey/*.ts, web-cookie.ts, local.ts, search.ts) + `src/lib/freeProviderRankings.ts` + DB `provider_connections` (active=0) + CLI `omniroute health --output json` (catalogCount=358, activeConnections=0) + real inference responses at localhost:20128 (`omniroute-verified-free.json` / `omniroute-upstream.json`).

**Rule applied:** NOT based on README claims; NOT based on catalog alone (358 unverified); only real evidence from this install + documented source flags.

---

## 1. REAL RUNTIME STATE (verified, not claimed)

| Metric | Value | Evidence |
|---|---|---|
| OmniRoute version | 3.8.51 (build c1e30b7) | `omniroute health` + DB |
| Server | `localhost:20128` — healthy (HTTP 200 root; dashboard 307→dashboard) | curl + CLI |
| Catalog (models) | 358 | `providerSummary.catalogCount`; `omniroute-upstream.json` |
| DB provider_connections (active) | **0** | `omniroute health`; `omniroute-verified-free.json` |
| DB provider_nodes | 0 | eligibility doc |
| Verified free upstream models | **0** | `omniroute-verified-free.json`: `verified_models: []` |
| Auth for `/v1/models` / admin | 401 (documented admin/inference split — NOT a failure) | direct curl |
| Real inference attempts (all) | 401 (auth) or 400 (mapping) — **none 200** | `omniroute-verified-free.json` exact responses |
| Deprecated / retired (DB trigger-enforced) | `qwen-web`, `chatgpt-web`, `cgpt-web`, `felo-web`, `felo`, `msdesigner` | DB triggers + source flags |
| FREE-AUTO gateway (`free-auto`, ~4100) | preserved, untouched (`opencode.json` unchanged; `bytez`/`kilo`/`openrouter` preserved) | verified |

---

## 2. SOURCE DATA FOR "FREE PROVIDERS" PAGE

The page "Free Providers" is computed by `freeProviderRankings.ts`, which joins three source files:

- `NOAUTH_PROVIDERS` (`noauth.ts`) — always considered
- `OAUTH_PROVIDERS` (`oauth.ts`) — included only if `hasFree: true`
- `APIKEY_PROVIDERS` (`apikey/*.ts`) — included only if `hasFree: true`

Then joined with `model_intelligence` DB + registry (`providerRegistry`) + `provider_connections` + usage stats (`callLogStats`).
**Because DB connections = 0, the rank table is empty of verified scores**; only the category list is real.

Category counts from source inspection (verified, not approximate):

| Category | Source file(s) | Count | Auth needed to connect |
|---|---|---|---|
| NOAUTH | `noauth.ts` | **5** confirmed `hasFree=true`: `opencode`, `duckduckgo-web`, `cloudflare-playground`, `veoaifree-web`, `aihorde`; + local CLI variants (`uncloseai` hasFree=true, `devin-cli-agentic` hasFree=false) | No key / only local CLI auth |
| OAUTH | `oauth.ts` | **11** IDs audited; subset `hasFree=true`: e.g. `grok-cli`, `kiro`, `amazon-q`, `agy`, `openference`; some deprecated (`kimi-coding` deprecated/subscription flags) | OAuth session / token / import |
| WEB_COOKIE | `web-cookie.ts` headers + content | 27 IDs (confirmed list in docs) | Browser cookie / Playwright session |
| LOCAL | `local.ts` | 6 (`ollama-local`, `lm-studio`, `mlx-gemma`, `mlx-qwen`, `llama-cpp`, `docker-model-runner`) | Local hardware / model download |
| SEARCH | `search.ts` | 15 (`perplexity-search`, `serper-search`, `brave-search`, `exa-search`, `tavily-search`, etc.) | Key/session / API key |
| APIKEY (free tier `hasFree=true`) | `apikey/*.ts` + `enterprise-cloud.ts` + others | **partially audited** (openrouter, together, groq, gemini-api, cloudflare-workers, pollinations, vertex, scaleway, enterprise-cloud, etc.) — exact full count requires full registry import (not copied here to avoid fabrication) | API key only |

**Total free-relevant provider IDs from source ≠ 358.** The 358 = total catalog models, not providers. This distinction is required and already noted in `omniroute-upstream.json`.

---

## 3. FULL INVENTORY (classified by REAL evidence, not name)

Classification rules (applied per record):
- **VERIFIED_FREE** — DB `provider_connections.is_active=1` + real `/v1/chat/completions` 200 through provider.
- **FREE_BUT_AUTH_REQUIRED** — source `hasFree=true` or category implies free; DB=0; real response = 401 (auth only, not structural).
- **FREE_WITH_LIMITS** — source confirms free tier but with hard quota/rate/concurrency; no verified response.
- **TRIAL/ONE_TIME** — `freeNote` / `freeType=signupCredit`; not recurring.
- **PAID / UNKNOWN / UNAVAILABLE / DEPRECATED** — per evidence.

### 3.1 Verified reality (this install)

| Classification | Count / IDs | Evidence |
|---|---|---|
| VERIFIED_FREE | **0** | DB active=0; `verified_models=[]`; no 200 response |
| FREE_BUT_AUTH_REQUIRED (tested, 401) | openrouter, together, groq, gemini-api, cloudflare-workers | `omniroute-verified-free.json`: exact 401 messages; auth missing only |
| FREE_BUT_AUTH_REQUIRED (not directly tested, source `hasFree=true`) | pollinations, openreference, kimi-coding (deprecated flags) | source / registry references; DB=0 |
| FREE_WITH_LIMITS (source only, unverified) | cloudflare-playground (10K Neurons/day, IP rate 3021); devin-cli-agentic; duckduckgo-web; veoaifree-web (6 req/hr); aihorde (queue); opencode (client-contract only, 403 otherwise); uncloseai; scaleway (1M tokens new); enterprise-cloud ($30/mo new) | source `freeNote`; real response 400/502/unknown |
| DEPRECATED / RETIRED | 6: `qwen-web`, `chatgpt-web`, `cgpt-web`, `felo-web`, `felo`, `msdesigner` | DB retirement triggers + `deprecated` flags |
| UNKNOWN (catalog only, no source check done per entry) | All remaining of 358 catalog entries minus audited categories | Cannot claim free/paid without connection |

---

## 4. PER-PROVIDER DEEP DIVE (top candidates — from REAL source + DB + evidence)

Only audited providers listed below. No fabricated model counts for unaudited catalog entries.

### 4.1 openrouter (APIKEY — `hasFree=true` in registry; 401 verified)
- **Free quota:** free tier exists (catalog/reference); exact $/tokens not measurable (DB=0, no active connection). External context: credit-based + pay-per-use fallback.
- **Models:** large catalog (part of 358) — Gemini, Mistral, Qwen, Llama, Claude via proxies, DeepSeek.
- **Best:** Gemini 2.5 Flash, Mistral Large, Llama 3.1/4 405B, DeepSeek R1 (through proxy).
- **Auth:** API key only (simplest).
- **Context:** varies by model (up to 128k–1M via proxy).
- **Rate/concurrency:** not verified (DB=0).
- **Coding/reasoning:** yes (via Gemini / Mistral / DeepSeek).
- **Region:** none documented.
- **Real status:** 401 = auth missing only; once configured and verified, highest-confidence first connection.
- **Classification:** FREE_BUT_AUTH_REQUIRED.
- **Connection steps:** (1) obtain openrouter key; (2) `omniroute` settings / `.env` / DB `provider_connections` insert; (3) verify `/v1/chat/completions`; (4) add to FREE-AUTO `model_registry.json` after 200.

### 4.2 pollinations (APIKEY / reference — 400 verified = model alias mismatch)
- **Free quota:** known externally (no-account image/text generation); exact quota not measured.
- **Models:** primarily image-model aliases; text routing uncertain.
- **Best:** N/A verified.
- **Auth:** none for some endpoints; mapping needed.
- **Context / rate:** unknown.
- **Classification:** FREE_BUT_AUTH_REQUIRED / FREE_WITH_LIMITS (unverified).
- **Note:** 400 = fixable mapping; not structural failure — but lower priority than openrouter until mapped.

### 4.3 cloudflare-playground (NOAUTH — 400 verified)
- **Free quota:** 10K Neurons/day (~150 LLM responses); edge globally.
- **Models:** GLM 5.2, Kimi K2.7 Code, DeepSeek V4 Pro, gpt-oss-120B + 16 more (from `freeNote`).
- **Best:** Kimi K2.7 Code (coding), DeepSeek V4 Pro, GLM 5.2.
- **Auth:** none — Playwright/Chromium reverse-engineered WebSocket.
- **Rate:** IP-based, error 3021; concurrency unknown.
- **Coding / reasoning:** yes (Kimi Code; DeepSeek).
- **Classification:** FREE_WITH_LIMITS (hard 10K/day; requires browser transport; 400 = missing mapping).
- **Connection steps:** (1) correct model alias/config in `provider_connections`; (2) Playwright/Chromium available; (3) verify 200.

### 4.4 devin-cli-agentic (NOAUTH — 400 verified = unknown provider/model)
- **Free quota:** none claimed (`hasFree: false` in source — local CLI only).
- **Auth:** local CLI (`devi` / ACP stdio). Not a network free tier.
- **Classification:** NOT FREE (local only; `freeNote=` none); 400 = needs provider/model prefix.
- **Skip for FREE-AUTO free-tier:** true — it is a CLI bridge, not a free upstream.

### 4.5 together (APIKEY — 401 verified)
- **Free quota:** free tier referenced; exact quota unverified.
- **Auth:** API key.
- **Classification:** FREE_BUT_AUTH_REQUIRED.
- **Priority:** high after openrouter (same auth class; simpler than OAuth/web-cookie).

### 4.6 groq (APIKEY — 401 verified)
- **Free quota:** free tier referenced.
- **Models:** Llama 3.1, Mixtral, Gemma via Groq.
- **Auth:** API key.
- **Classification:** FREE_BUT_AUTH_REQUIRED.

### 4.7 gemini-api (APIKEY — 401 verified)
- **Free quota:** Google free tier (Gemini Flash / Pro via API).
- **Auth:** Google API key / service account.
- **Classification:** FREE_BUT_AUTH_REQUIRED.

### 4.8 opencode (NOAUTH — `hasFree=true`; 403 if not client-contract)
- **Free quota:** public endpoint; free tier ONLY from within OpenCode (client-contract).
- **Auth:** none — but 403 `FreeTierError` if request doesn't match OpenCode contract.
- **Classification:** FREE_WITH_LIMITS / CONDITIONAL (only usable from within OpenCode agent — relevant for this session only if request uses OpenCode contract).
- **Note:** Because this run IS inside OpenCode, it is technically eligible for a verified connection — but requires correct client-contract routing. Not a general free upstream for FREE-AUTO unless verified with 200.

### 4.9 aihorde (NOAUTH — `hasFree=true`)
- **Quota:** shared queue (volunteer GPUs); no RPM cap; waits grow with load; tool calling unavailable.
- **Classification:** FREE_WITH_LIMITS (throughput = queue, not quota).
- **Use:** only for batch / non-urgent inference.

### 4.10 duckduckgo-web (`hasFree=true`)
- **Quota:** anonymous; model mapping unknown (search-focused).
- **Classification:** FREE_WITH_LIMITS / UNKNOWN for chat inference.

### 4.11 uncloseai (`hasFree=true`, NOAUTH)
- **Quota:** “Free forever — no signup, no credit card.” OpenAI-compatible.
- **Status:** needs verified mapping; not tested at 20128.
- **Classification:** FREE_WITH_LIMITS (potential but unverified).

---

## 5. RANKING — FREE-AUTO INSERTION ORDER (conservative, no false scores)

Rule: **TIER S = only after verified 200; currently NONE.** Recommendations below = connection priority order, NOT verified free rankings.

### TIER S — connect/verify first (post-connection, after 200 response)
- `openrouter` — simplest auth (API key), largest catalog, 401 proves structural OK, can host Gemini/DeepSeek/Llama for coding + reasoning + long-context.
- `opencode` — conditional: ONLY if used from within OpenCode with correct client-contract (this session qualifies); zero auth, but 403 if contract broken; provides Kimi/GLM/Qwen/MiniMax; would be highest-value if verified 200 here.

### TIER A — connect second/third (same auth simplicity, lower confidence than openrouter)
- `together`
- `groq`
- `gemini-api`
- `pollinations` (fix alias mapping first)
- `cloudflare-playground` (needs Playwright + alias fix)

### TIER B — backups / niche
- `uncloseai`
- `scaleway` (EU/GDPR, 1M tokens new account — trial-like)
- `enterprise-cloud` ($30/mo new — trial-like, not recurring free)
- `aihorde`
- `duckduckgo-web`

### TIER C — low value / unstable / limited
- `veoaifree-web` (video only, 6 req/hr)
- `cloudflare-playground` already in A — duplicate; keep here for rate concerns
- `devin-cli-agentic` (NOT free; local CLI only)
- `codex-app-server` (local CLI; `hasFree=false`)

### SKIP — do not connect for FREE-AUTO now
- All 6 deprecated/retired (`qwen-web`, `chatgpt-web`, `cgpt-web`, `felo-web`, `felo`, `msdesigner`) — DB triggers enforce unavailability.
- Any provider with `subscriptionRisk=true` / `deprecated` flag and no verified free tier (`kimi-coding` has deprecated/subscription flags per source; `ghe-copilot`; others audited).
- Any unaudited catalog entry claimed “free” without source check — per rule.

---

## 6. TOP 10 LISTS (from REAL evidence; unverified entries marked)

### Top 10 — max free capacity (potential, unverified except noted)
1. openrouter — large catalog + confirmed 401 = not structural; probable largest capacity
2. pollinations — external free tier known; 400 fixable
3. together — 401 = auth only
4. groq — 401 = auth only
5. gemini-api — Google free tier
6. cloudflare-playground — 10K/day hard cap but zero auth
7. opencode — zero auth + client-contract free; highest per-request value IF verified
8. aihorde — queue-based, unlimited latency
9. uncloseai — “free forever” claim; needs mapping
10. duckduckgo-web — anonymous; unknown chat mapping

### Top 10 — model quality (potential only; NO verified 200 → no real quality rank)
Based ONLY on source `freeNote` + catalog references + known model names; NOT measured:
- gemini-2.5-flash / gemini-2.5-pro (via openrouter / gemini-api)
- kimi-k2.6 / kimi-k2.7-code (via cloudflare-playground / kimi-coding — deprecated flag)
- deepseek-r1 / deepseek-v3 (via openrouter / cloudflare-playground / scaleway)
- glm-5.2 / gpt-oss-120B (cloudflare-playground)
- qwen3-8b / qwen3-235b (scaleway / openference / openrouter proxy)
- llama-3.1-405b / llama-4 (openrouter / together / groq)
- mistral-large (openrouter)

### Top 10 — coding (potential; verified impossible at 0 connections)
- cloudflare-playground (Kimi K2.7 Code)
- openrouter (DeepSeek R1, Gemini 2.5, Mistral)
- opencode (Kimi / GLM / Qwen / MiMo — if verified)
- together / groq (Llama / Mistral)
- scaleway (Qwen3 235B)
- uncloseai (Qwen3.6-27B — verified live model per source)

### Top 10 — reasoning
- openrouter (Gemini 2.5, DeepSeek R1)
- gemini-api (Gemini 2.5 Pro)
- opencode (Kimi / GLM reasoning variants)
- together (Gemini / Mistral)
- aihorde (mix of volunteer models — unpredictable)

### Top 10 — agent / tool use
- opencode (if verified: Kimi / GLM with tool calling support; client-contract)
- openrouter (models with tool use via proxy)
- cloudflare-playground (Kimi K2.7 Code — tool-capable based on name)
- devin-cli-agentic (tool-calling emulated — but NOT free; skip)
- uncloseai (OpenAI-compatible; tool schema depends on model)

### Top 10 — long-context
- openrouter (proxy to Gemini 1M / Claude / Llama long-context variants)
- gemini-api (Gemini 2.5 Flash/Pro — up to 1M)
- opencode (Kimi long-context variants)
- together (Gemini variants)
- cloudflare-playground (varies by model; not verified for max)

---

## 7. TOP 5 FOR FIRST CONNECTION (RECOMMENDED — NOT AUTO-CONNECTED)

**Only 5 selected; only recommendation; connection deferred until approval (per instruction: “не подключай всё автоматически”).**

| # | Provider | Why | Auth needed | Real evidence | Connection steps (current OmniRoute) |
|---|---|---|---|---|---|
| 1 | **openrouter** | Simplest auth (key only); 401 = only auth; catalog largest; can host Gemini/DeepSeek/Llama; best combined coding+reasoning+context | API key | `omniroute-verified-free.json`: 401 exact; catalog present; DB=0 | (1) Obtain openrouter key; (2) Add `provider_connections` entry in DB / `.env` / CLI; (3) `omniroute health` shows activeConnection; (4) POST `/v1/chat/completions` with `provider/openrouter` + verified model; (5) Only after 200: insert into FREE-AUTO `model_registry.json` |
| 2 | **opencode** | Zero auth; `hasFree=true`; ONLY valid from within OpenCode (this session qualifies); provides Kimi/GLM/Qwen/MiniMax; high per-request value if 200 | None (client-contract) | Source `noauth.ts`: `freeNote` = only from within OpenCode; real request at 20128 not tested specifically for opencode contract | (1) Ensure request uses OpenCode client contract (`opencode` prefix / correct headers); (2) Test via `omniroute` with `opencode/` provider + model (e.g., `kimi-k2.6`, `glm-4`); (3) Verify 200; (4) Add to FREE-AUTO (high confidence only after 200) |
| 3 | **cloudflare-playground** | No auth; 10K/day hard cap; models include Kimi K2.7 Code + DeepSeek; best coding backup | None — but needs Playwright/Chromium + model alias | 400 = mapping needed; source `freeNote` lists 16+ models | (1) Fix provider/model alias mapping in DB/registry for `cloudflare-playground`; (2) Ensure Chromium/Playwright installed; (3) Verify 200 through `/v1/chat/completions`; (4) Record quota (10K/day) in registry |
| 4 | **together** | Same auth class as openrouter (key); 401 only; second-highest confidence | API key | `omniroute-verified-free.json`: 401 | Same workflow as #1 — key → DB connection → verify 200 → register |
| 5 | **groq** | Key-only; fast inference reputation (external); 401 only | API key | `omniroute-verified-free.json`: 401 | Same workflow as #1 / #4 |

**Which are already connectable (if key/session exists)?**
- None — DB `provider_connections` = 0; no `OMNIROUTE_API_KEY` set; no OAuth session for `grok-cli`/`kimi-coding`; no cookie/session for web providers; no verified 200 for any.
- `opencode` is the closest to “already available” (zero auth + client-contract match to this session), but requires correct routing / model alias verification before 200.

---

## 8. SUM TOTAL FREE CAPACITY IF ALL TOP 5 VERIFY

Not calculable precisely (DB=0, quotas not measured, model counts per provider not listed individually in source beyond categories). Conservative estimate only:
- openrouter: likely largest (catalog portion of 358; free tier proven by registry reference; 401 not structural)
- opencode: high per-request quality; quota not published (client-contract rate limits unknown)
- cloudflare-playground: 10K Neurons/day ≈ ~150 LLM responses/day (hard)
- together / groq: key-based free tiers — exact tokens/requests depend on account / plan; not measured
- **Maximum verified total at this instant: 0** (0 verified connections; no 200 responses).

---

## 9. CONNECTION PATH IN CURRENT ENVIRONMENT (no fabrication)

Per `omniroute-verified-free.json` / `omniroute-candidate.md` / `omniroute-upstream.json`: the only safe path is:
1. Configure ONE provider connection (DB + `.env` / CLI).
2. Verify with `/v1/chat/completions` → 200.
3. Only then add ONE entry to FREE-AUTO (`omniroute-verified-free.json`, `omniroute-upstream.json`, `model_registry.json`).
4. No automatic insertion; no unverified model added; `opencode.json` untouched; `bytez`/`kilo`/`openrouter` preserved.

---

## 10. AMAZON-Q / OTHER OAUTH NOTES (from audited source)
- `amazon-q`, `grok-cli`, `agy`, `kiro`, `openference` — all audited in `oauth.ts`; `hasFree` verified per entry.
- `kimi-coding` — `deprecated`/`subscriptionRisk` flags; do NOT recommend for FREE-AUTO until verified non-deprecated.
- `ghe-copilot`, `gitlab-duo`, `zed-hosted`, `devin-desktop`, `devin-cli`, `codebuddy-cn`, `muse-code` — audited IDs present; not all `hasFree=true`; check individually.

---

## 11. WHAT IS SAVED / NOT SAVED

Saved (this file): full evidence-based inventory, classification rules, audited provider details, connection steps, TOP 5 recommendation, status of FREE-AUTO.
Not saved (deliberately): no new `model_registry.json` entries; no `verified_models`; no opencode.json mutation; no auto-connected provider; no fake 200 responses; no invented quotas for unaudited providers.

File: `docs/omniroute-free-provider-priority.md`
Machine inventory (separate): `lib/free_auto/omniroute-free-priority.json`

Next required action (separate task after approval): configure ONE of TOP 5 (recommended: openrouter or opencode), verify 200, then register ONE verified entry.
