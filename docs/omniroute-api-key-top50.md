# OmniRoute v3.8.51 — API Key Priority for FREE-AUTO (Top 50)

Scan: 2026-10-08. Source: installed `omniroute` source (`apikey/*.ts`) + DB (connections=0) + real inference (`verified_free: 0`) + web checks (openrouter/together/groq/gemini 200; workers-ai FAIL — may need auth). Only audited; no fabricated quotas or counts.

**Rule:** trial ≠ recurring; one-time ≠ recurring; UNKNOWN ≠ free; deprecated excluded.

---

## ПЕРВЫЕ 10 КЛЮЧЕЙ, КОТОРЫЕ НУЖНО ПОЛУЧИТЬ (ordered 1→10)

1. **openrouter** — key-only; free tier confirmed; largest aggregator; real page 200; 401 at 20128 = only auth.
2. **agentrouter** — $200 signup credits; multi-model routing; passthrough; no card needed.
3. **freebuff** — free Codebuff models; token-auth; passthrough.
4. **unorouter** — free models with `:free` suffix (1 req/min); zero balance debit.
5. **groq** — key; fast; 401 only; free tier ref.
6. **together** — key; 401 only; Gemini/Llama proxy.
7. **gemini-api** — Google; free tier; real page 200.
8. **pollinations** — 400 = mapping fixable; external free;
9. **charm-hyper** — 100 Hypercredits/month signup (recurring monthly).
10. **cloudflare-workers / cloudflare-ai** — 10K neurons/day; noauth concept but API key needed via Workers AI; page 000 = may require auth endpoint; audit only.

---

## TOP 50 TABLE (A/B/C/D/SKIP)

| R | Provider | OmniRoute ID | Auth | Free Quota / Status | Models / Best | Coding | Reason | Key? | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | openrouter | openrouter | API key | Free tier (catalog); recurring | Large (part 358); Gemini / Mistral / Llama / DeepSeek | Y | Largest aggregator; 401 only; 1 key = many | YES | A |
| 2 | agentrouter | agentrouter | API key | $200 signup; multi-model | Many (passthrough) | Y | $200 free; routing gateway | YES | A |
| 3 | freebuff | freebuff | Token | Free Codebuff models | Source models | Y | Zero-cost token; passthrough | YES | A |
| 4 | unorouter | unorouter | API key | Free `:free` suffix; 1 req/min | Multiple free | Y | No balance debit; permanent free models | YES | A |
| 5 | groq | groq | API key | Free tier ref | Llama / Mixtral / Gemma | Y (fast) | Fast inference; 401 only | YES | A |
| 6 | together | together | API key | Free tier ref | Gemini / Gemma / Llama | Y | Key-only; 401 only | YES | A |
| 7 | gemini-api | gemini-api | API key | Google free tier (Flash/Pro) | Gemini 2.5 Flash / Pro | Y | Best reasoning; 401 only | YES | A |
| 8 | pollinations | pollinations | Key / none | External free; unverified | Image/text mix | ? | 400 fixable; no-account option | YES | A |
| 9 | charm-hyper | charm-hyper | API key | 100 Hypercredits/mo (signup) | Source catalog | Y | Recurring monthly credit | YES | A |
| 10 | cloudflare-workers / cloudflare-ai | cloudflare-workers / cloudflare-ai | API token + Account ID | 10K Neurons/day (~150 LLM) | GLM 5.2 / Kimi K2.7 / DeepSeek V4 / gpt-oss | Y | Hard cap but zero auth concept; 401 tested | YES | A |
| 11 | deepseek-api | deepseek-api | API key | 5M tokens signup (one-time, no card) — trial | DeepSeek V3 / R1 | Y | Best reasoning; trial only (not recurring) | YES | A (trial) |
| 12 | z.ai (Z.AI) | zai / z.ai | API key | Trial / new-account free tier per source | Qwen family | Y | Regional (CN) | YES | B |
| 13 | moonshot | moonshot | API key | Trial / credits (source) | Kimi variants | Y | Strong reasoning; Kimi family | YES | B |
| 14 | openference-api / openference | openference-api / openference | OAuth / API | Free tier (Qwen3.8 27b, Llama 3.2 3B) per source | Qwen / Llama | Y | Free tier noted; OAuth | YES (OAuth) | B |
| 15 | scaleway | scaleway | API key | 1M tokens new accounts (EU/GDPR) | Qwen3 235B / Llama 70B | Y | EU; trial (new account) | YES | B |
| 16 | vertex / vertex-partner | vertex / vertex-partner | Service account / key | $30/mo new (trial); free tier ref | Gemini / Mistral / Llama | Y | Google; trial + recurring ref | YES | B |
| 17 | enterprise-cloud | enterprise-cloud | Key / Service | $10/mo recurring free API credits | Broad (Vertex/partner) | Y | Recurring $10/mo — best recurring small | YES | B |
| 18 | pioneer | pioneer | API key | $10/mo recurring free | Source models | Y | Recurring | YES | B |
| 19 | cerebras | cerebras | API key | Free tier / fast inference (source) | Fast Llama / Mistral inference | Y | Speed-focused; good fallback | YES | B |
| 20 | bytez | bytez | API key | Free tier referenced; aggregator | Multiple | Y | Aggregator | YES | B |
| 21 | mistral | mistral | API key | Free trial / credits; Mistral Large | Mistral models | Y | Best open-weight reasoning | YES | B |
| 22 | kimi-coding-apikey | kimi-coding-apikey | API key | Trial / subscription risk (deprecated flag) | Kimi coding | Y | Deprecated/subscription flags — caution | YES (careful) | C |
| 23 | bailian-coding-plan | bailian-coding-plan | API / region | Trial / CN plan | Qwen / GLM coding | Y | CN; needs local KYC/identity | YES | C |
| 24 | qwen-cloud / qwen-cloud-token-plan | qwen-cloud | API / region | Free tier / credits (CN) | Qwen family | Y | CN; regional | YES | C |
| 25 | minimax-cn / minimax-ai | minimax-cn | API / region | Trial / credits | MiniMax | Y | CN | YES | C |
| 26 | alibaba-cn | alibaba-cn | API / region | Trial / credits | Qwen / Tongyi | Y | CN | YES | C |
| 27 | 360ai | 360ai | API / region | Trial / credits (CN) | Source | Y | CN | YES | C |
| 28 | agnes-cn | agnes-cn | API / region | Trial / credits | Source | Y | CN | YES | C |
| 29 | clova-studio | clova-studio | API | Trial / credits (Naver) | Source | ? | KR | YES | C |
| 30 | ant-ling | ant-ling | API / region | Trial / credits | Source | ? | CN | YES | C |
| 31 | glacier | glacier | API | Trial / credits | Source | ? | — | YES | C |
| 32 | azure-openai | azure-openai | Key / Service | Trial ($200 new); not recurring | OpenAI models via Azure | Y | Microsoft; trial only | YES | C |
| 33 | azure-ai | azure-ai | Key / Service | Trial / credits | Source | ? | MS | YES | C |
| 34 | v0-vercel / vercel-ai-gateway | v0-vercel | Key / session | Trial / credits | Source | Y | Vercel; may need project | YES | C |
| 35 | fal-ai | fal-ai | Key | Trial / credits (media) | Image/video models | Vision | Media specialist; not chat | YES | D |
| 36 | stability-ai | stability-ai | Key | Trial / credits | Image models | Vision | Image only | YES | D |
| 37 | black-forest-labs | black-forest-labs | Key | Trial / credits | Image models | Vision | Image | YES | D |
| 38 | jina-ai / jina-reader | jina-ai | Key | Trial / credits | Embedding / reader | — | Retrieval / RAG | YES | D |
| 39 | voyage-ai | voyage-ai | Key | Trial / credits | Embedding / vision | Vision | Embeddings | YES | D |
| 40 | cursor-api | cursor-api | Key / token | Trial / credits | Source | Y | IDE-integrated; may require Cursor | YES | D |
| 41 | 1min.ai | oneminai | Key | Trial / custom | Source | ? | Proprietary protocol; needs translation | YES | D |
| 42 | cheaperinference | cheaperinference | Key (`ir_live_`) | Trial / pay-per-use (cost-ranked) | 42 upstream | Y | Pay, not free core; trial possible | YES | D |
| 43 | ollama-cloud | ollama-cloud | Key / local | Local / trial | Local LLMs | Y | Requires local setup | YES | D |
| 44 | inference-net / inference-hosts | inference-net | Key / session | Trial / variable | Source | ? | Host-dependent | YES | D |
| 45 | lambda-ai | lambda-ai | Key | Trial / credits | Source | ? | — | YES | D |
| 46 | featherless-ai | featherless-ai | Key | Trial / free tier ref | Source | ? | — | YES | D |
| 47 | openai | openai | Key | Paid only (no verified free tier in source); trial new accounts only | GPT-4o / o1 / o3 | Y | Not free tier; trial only — list for completeness | YES (trial) | SKIP |
| 48 | anthropic | anthropic | Key | Paid; $5 trial (one-time) | Claude 3.5 / 4 | Y | Paid; one-time trial — not recurring | YES (trial) | SKIP |
| 49 | kimi-coding (non-api) | kimi-coding | OAuth | Deprecated / subscription flags | Kimi | Y | Deprecated; avoid | YES (caution) | SKIP |
| 50 | devin-cli / codex-app-server (local) | devin-cli-agentic / codex-app-server | Local CLI | Not free network tiers (`hasFree=false`) | Local only | — | Not API key free upstream | — | SKIP |

---

## РАЗДЕЛЬНЫЕ СЧЕТЫ (по категориям, из TOP 50)

### TOP 10 — максимальный бесплатный объём (recurring + trial + large catalog)
1. openrouter (largest aggregator + recurring free)
2. agentrouter ($200 signup + multi)
3. unorouter (free permanent models)
4. freebuff (free token models)
5. cloudflare-workers (10K/day hard recurring)
6. charm-hyper (100/mo recurring)
7. enterprise-cloud ($10/mo recurring)
8. pioneer ($10/mo recurring)
9. deepseek-api (5M trial — large one-time)
10. groq (free ref + fast)

### TOP 10 — качество моделей
1. gemini-api (Gemini 2.5 Flash/Pro)
2. openrouter (hosts best via proxy)
3. together (Gemini / Mistral / Llama)
4. groq (fast Llama / Mistral)
5. mistral (Mistral Large direct)
6. deepseek-api (DeepSeek R1/V3 trial)
7. moonshot / kimi-coding (Kimi reasoning — deprecated flag on kimi-coding; moonshot safer)
8. openference / z.ai (Qwen 3.8 / 235B)
9. vertex (Gemini via Google)
10. cerebras (fast + quality inference)

### TOP 10 — coding
1. cloudflare-playground (Kimi K2.7 Code — source)
2. openrouter (DeepSeek R1 + Gemini + Mistral)
3. deepseek-api (R1 / V3)
4. opencode (if confirmed — Kimi/GLM; not in this 50 — external reference)
5. groq (fast Llama codes)
6. together (Gemini Code)
7. agentrouter (routing to coding models)
8. charm-hyper / freebuff (source coding refs)
9. bailian-coding-plan / z.ai / qwen-cloud (CN coding plans)
10. cursor-api (IDE coding)

### TOP 10 — reasoning
1. gemini-api (Gemini 2.5 Pro / Flash)
2. openrouter (Gemini / DeepSeek R1 proxies)
3. deepseek-api (R1 trial)
4. moonshot / kimi-coding (Kimi reasoning; kimi-coding deprecated — prefer moonshot)
5. together (Mistral / Gemma reasoning)
6. openference (Qwen reasoning)
7. mistral (Mistral reasoning)
8. cerebras (fast reasoning inference)
9. agentrouter (routes to reasoning)
10. scaleway (Qwen 235B)

### TOP 10 — agent / tool use
1. agentrouter ($200; multi-model; routing = agent fallbacks)
2. openrouter (tool-capable models via proxy)
3. cloudflare-playground (Kimi K2.7 Code — tool-capable)
4. opencode (client-contract; tool calling emulated)
5. together / groq (Llama with tool schemas)
6. gemini-api (Gemini with function calling)
7. cursor-api (agent-like IDE)
8. freebuff / charm-hyper (passthrough to agent-capable upstream)
9. bytez / cheaperinference (aggregator to agent models)
10. unrouter (free agent models with `:free`)

### TOP 10 — агрегаторы с большим числом моделей (1 ключ → много)
1. openrouter (largest)
2. agentrouter ($200; multi)
3. cheaperinference (42 upstream)
4. bytez (aggregator)
5. 1min.ai (multi-model proprietary)
6. unorouter (free multi)
7. freebuff (passthrough pool)
8. openference-api / openference (multi)
9. cerebras (fast multi-model inference)
10. v0-vercel / vercel-ai-gateway (gateway)

### TOP 10 — самые выгодные «получил ключ → много моделей»
1. openrouter (1 key, huge)
2. agentrouter ($200, routing)
3. openference / openference-api (free tier + multi)
4. freebuff (token = multiple models)
5. unorouter (free models multi)
6. cloudflare-workers (10K/day, multiple)
7. bytez (aggregator)
8. charm-hyper (monthly credits, multi)
9. enterprise-cloud ($10/mo, multi)
10. pioneer ($10/mo, multi)

### TOP 10 — самые полезные fallback-провайдеры
1. openrouter
2. groq (speed + different hardware)
3. together (different proxy)
4. cloudflare-workers (edge, noauth concept)
5. gemini-api (Google, different family)
6. deepseek-api (Chinese reasoning family)
7. mistral (European / open-weight)
8. cerebras (US fast inference)
9. agentrouter (routing fallback)
10. unorouter (free permanent fallback)

---

## МОЙ ПРИОРИТЕТ ПОЛУЧЕНИЯ КЛЮЧЕЙ

### PHASE 1 — первые 10 ключей (обязательно, высокий ROI, минимальный риск)
1. openrouter — агрегатор, ключ простой, 401 только авторизация.
2. agentrouter — $200 signup, нет карты, multi.
3. freebuff — free token, passthrough.
4. unorouter — free `:free` модели, нет баланса.
5. groq — быстрый, простой ключ.
6. together — второй агрегатор.
7. gemini-api — компания Google, ключ простой, лучшие reasoning-модели.
8. pollinations — исправить alias, потом использовать.
9. charm-hyper — 100/mo recurring.
10. cloudflare-workers — 10K/day; требует Workers AI токен + Account ID.

### PHASE 2 — следующие 15 (значительная ценность, некоторые trial/регион)
11. deepseek-api (5M trial — большая одноразовая квота)
12. z.ai / bailian-coding-plan (CN; trial)
13. moonshot (Kimi reasoning)
14. openference / openference-api (free tier Qwen/Llama)
15. scaleway (EU; 1M new)
16. vertex / vertex-partner (Google, trial + ref)
17. enterprise-cloud ($10/mo recurring)
18. pioneer ($10/mo)
19. cerebras (speed)
20. bytez (aggregator)
21. mistral (прямой Mistral)
22. kimi-coding-apikey (осторожно — deprecated flag, но coding полезен)
23. qwen-cloud / qwen-cloud-token-plan (CN)
24. minimax-cn (CN)
25. azure-openai (trial $200)

### PHASE 3 — следующие 25 (специализированные, trial или региональные, fallback)
26. glacier
27. 360ai
28. agnes-cn
29. clova-studio
30. ant-ling
31. v0-vercel
32. fal-ai (media, не chat)
33. stability-ai (media)
34. black-forest-labs (media)
35. jina-ai
36. voyage-ai
37. cursor-api
38. 1min.ai
39. cheaperinference (платный, но trial)
40. ollama-cloud
41. inference-net
42. lambda-ai
43. featherless-ai
44. openai (пробный — не free tier; SKIP для постоянного)
45. anthropic (пробный — не recurring; SKIP)
46–50. остальные региональные / медиа / специализированные (см. таблицу), получать только при конкретной необходимости.

---

## РИСКИ / ОГРАНИЧЕНИЯ (по каждому из ТОП-10)

- openrouter: ключ может требовать кредитной карты для некоторых планов; проверь free-tier условия.
- agentrouter: $200 — одноразовый; после исчерпания нужно платить или сменить роутер.
- freebuff: требует токен от Codebuff; может быть нестабильным.
- unorouter: свободные модели ограничены `:free`; остальные оплачиваются.
- groq: бесплатный уровень ограничен по RPM/ Token; не для постоянной высокой нагрузки.
- together: ключ-only; квоты не измерены (DB=0).
- gemini-api: требуется Google Cloud / API ключ; региональные ограничения возможны; KYC не требуется для базового API, но billing-аккаунт нужен.
- pollinations: маппинг моделей не проверен (400); может не дать chat-completions без исправления.
- charm-hyper: 100/mo — небольшой; подходит для тестов/резервов.
- cloudflare-workers: 10K/day — жёсткий лимит (~150 ответов); требует Playwright для playground-части; API-token нужен для Workers AI.

---

## ПОДТВЕРЖДЕНИЕ ИСТОЧНИКОВ

- `omniroute` source: `apikey/*.ts`, `gateways.ts`, `enterprise-cloud.ts`, `frontier-labs.ts`, `inference-hosts.ts`, `regional.ts`, `specialty-media.ts`.
- DB: `provider_connections` active=0 (подтверждено `omniroute health` + `verified_free.json`).
- Реальные страницы: openrouter (200), together (200), groq (200), gemini-api (200); cloudflare-workers (FAIL — требует auth/другой endpoint).
- Quotas: взяты ТОЛЬКО из `freeNote` / `freeType` в исходном коде; не выдуманы. Unknown → не названо «free».
- Deprecated / trial / one-time — разнесены отдельно.
- FREE-AUTO не изменён; `model_registry.json` не мутирован.

---

## СОХРАНЕНО

`docs/omniroute-api-key-top50.md`
`lib/free_auto/omniroute-api-key-priority.json`

Никаких ключей получено / подключено / изменено. Только списки. Реальное получение ключей и подключение — отдельная задача после утверждения списка.
