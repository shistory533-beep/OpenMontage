# FREE-AUTO Model Catalog, Benchmarks & Rankings (v2)

Dated: 2026-10-08. Source of discovery: OpenRouter `GET /v1/models` (public,
no key) + per-model `supported_parameters`/`context_length`/`pricing`.
Kilo upstream slugs/tiers are UNVERIFIED (no `KILO_API_KEY` in this
environment) unless noted. No `Cloudflare`/`Google-direct` credentials are
configured in this repo, so no candidates are inventoried from them.

## 0. Validation runs

### Final gate check (timestamp: 2026-10-08T02:45Z)

- Credential discovery: `KILO_API_KEY`, `OPENROUTER_API_KEY`, `KILO_BASE_URL`,
  `OPENROUTER_BASE_URL`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`,
  `CLOUDFLARE_API_KEY`, `CLOUDFLARE_ACCOUNT_ID` — all unset; no `.env` files.
  Live probes impossible. No values fabricated.
- Per-model live status: all 20 candidates × all 40 upstreams =
  **AUTH_REQUIRED** (unconfigured; no keys). Verified-live: none.
  Measured TTFT/latency: none. E2E loopback re-run green (429 → failover 200;
  session-affine stickiness confirmed; router correctly confined itself to the
  only-configured provider family when Kilo was absent).
- Independent reviewer: 4th attempt failed (same provider restriction;
  permissions not weakened to bypass). Completed adversarial self-review
  stands as the review of record (see runs below).
- Confidence ledger (gate vocabulary: HIGH = sourced benchmark ± strong local
  evidence; MEDIUM = reliable prior/capability evidence; LOW = weak/limited):

| candidate | basis | confidence |
|---|---|---|
| nemotron-3-ultra-550b | NVIDIA tech report (primary) | HIGH |
| muse-spark-1.3 | Meta scorecard + Vals corroboration | HIGH |
| mimo-v2.6-flash | Xiaomi report (drift disclosed) | MEDIUM |
| nemotron-3-super-120b | secondary compilation of launch data | MEDIUM |
| nemotron-3-nano-omni-30b | single secondary source | LOW |
| gemma-4-31b | approximate secondary figures | LOW |
| gemma-4-26b | single independent source + omission corroboration | LOW |
| inkling | vendor launch post + Vals corroboration | HIGH |
| step-3.7-flash | vendor table, corroborated across outlets | HIGH |
| inkling-small | vendor table (internal-harness caveat) | MEDIUM |
| remaining 10 | verified API capabilities + tiers, operator priors | MEDIUM |

### Calibration top-up (timestamp: 2026-10-08T03:02Z)

- 3 more models sourced (10/20 now): step-3.7-flash coding 0.72→0.77 /
  agentic 0.70→0.60; inkling coding/agentic/reasoning null→0.78/0.64/0.87;
  inkling-small coding 0.74→0.77, agentic 0.74→0.53 (internal harness,
  medium), reasoning 0.76→0.88. Same score/100 domain-matched methodology.
- Vals leaderboard rows for Ling 3.0 Flash / Laguna XS.2 lack column mapping
  → recorded as insufficient evidence, unmapped. No other reliable figures
  found for ling/apodex/dots/lfm/lightning/laguna-xs/north/longcat.
- Ranking effect: Build now muse 0.842 > mimo 0.820 > step 0.819;
  inkling-small demoted on agentic per vendor's own TB 2.1 figure but holds
  Research #5 on GPQA 88.3; inkling-full (null quality/agentic priors) sits
  below top-6 despite strong reasoning — correctly penalized by the
  unknown-prior confidence path. Tables in §3 refreshed.

- Gate verdict: criteria B (reachable candidates have live status — all are
  AUTH_REQUIRED, none LIVE_OK) and C (independent review) unmet →
  **CONDITIONALLY READY**. Exact missing gates: (A) exercise ≥1 live provider
  with a real key; (C) independent review pass. No code changes this run;
  74/74 focused green; compile clean.

### Run 2026-10-08T02:24Z — live gate BLOCKED

- Credentials: `KILO_API_KEY`, `OPENROUTER_API_KEY` (and base-URL overrides,
  Google/Cloudflare keys) all **unset**; no `.env` file. Live completion
  probes impossible → every candidate remains AUTH_REQUIRED/unconfigured.
  **No live results fabricated; no registry/scoring changes made** (calibration
  requires evidence; none obtainable).
- Tier re-verification (public listing, 467 models, non-billable): all 20
  registry OpenRouter upstreams resolve; tiers match registry (`paid` ×5
  non-suffix IDs, `free` ×15, `ling-3.1-flash` 0/0-priced but markerless →
  stays `unknown` per marker rule). The sole `:free` ID absent from the
  registry is the safety classifier (correctly excluded). Nothing vanished.
- Measured TTFT/latency: none (no keys). Fields exist (`latency_ms_ema`
  blended when present; `record_ttft()` ready for streaming callers).
- Independent reviewer subagent attempted twice — unavailable both times
  (provider: "free tier only within OpenCode"). Substituted adversarial
  self-review: hand-verified score arithmetic ✓, determinism all 6 classes ✓,
  cooldown→reset recovery ✓, tool-gated session routing ✓, no secret
  logging/persistence ✓, `session_id`/`complexity` never forwarded upstream ✓.
  Findings: none critical.
- Verification: 71/71 focused; E2E loopback fallback re-run (429 rate_limit →
  200 failover; session-affine pin) ✓; `py_compile` ✓.

### Run 2026-10-08T02:34Z — benchmark calibration (evidence-driven)

- Web benchmark research (4 searches) yielded citable scores for 7 models
  (sources + dates + confidence in each entry's `benchmark.note`):
  muse-spark-1.3 (DeepSWE 75.4, TB 2.1 88.8 — Meta scorecard Sept 2026),
  mimo-v2.6-flash (DeepSWE 67.9 — Xiaomi report; harness drift disclosed),
  nemotron-3-ultra-550b (SWE-Ver 71.9, TB 2.1 56.4 — NVIDIA tech report;
  GPQA 86.7 aggregator), nemotron-3-super-120b (SWE-Ver 60.47 OpenHands;
  GPQA w/tools 82.7), nemotron-3-nano-omni-30b (SWE-bench 38.8, secondary),
  gemma-4-31b (SWE-Ver ~63 approx, GPQA 84.3, secondary),
  gemma-4-26b (SWE-Ver 17.4 single independent source + vendor-silence
  corroboration). Remaining 13: no reliable public benchmark found.
- Methodology: priors are success-rate estimates, so domain-matched standard
  benchmarks map as score/100 (coding←SWE-family/DeepSWE, agentic←Terminal-Bench
  2.1 only, reasoning←GPQA). Recorded-but-NOT-mapped (incomparable harness or
  version mismatch): TB 4.0, TB-hard/Core 2.0, SWE-Lite, Pro numbers on Flash,
  family numbers presented as corroboration only. Unmatched priors stay
  operator estimates — explicitly, not silently.
- Ranking effect: Build now muse-spark-1.3 0.842 > step-3.7-flash 0.821 >
  mimo-v2.6-flash 0.820; Research led by nemotron-3-super-120b 0.848;
  Ultra demoted on agentic per its own TB 2.1 number. Full tables in §3.
- Honesty-guard test strengthened (not weakened): sourced entries must carry
  source + date + score% + confidence; unsourced must disclaim.
- Reviewer subagent 3rd attempt failed (same provider restriction).
  Adversarial self-review of calibration: version-match ✓, harness
  comparability ✓, confidence flags ✓, low-prior models stay routable
  (gemma-4-26b coding 0.606 total — demoted, never stranded) ✓.
- Verification: 74/74 focused; E2E T3 planning request (429 → failover 200,
  `complexity:t3` in envelope) ✓; `py_compile` ✓.

Honesty rule (enforced by `test_registry_has_no_invented_benchmarks`):
`benchmark.source` stays `null` until a measured score with a citable source
exists. Capabilities below come from API metadata, not marketing.

## 1. Verified catalog (20 candidates)

Capabilities key: T=tool_use, S=structured_output, R=reasoning, Ctx=context.
T/S/R verified from `supported_parameters`; Ctx from `context_length`.
OR $ = OpenRouter pricing observed (0/0 = free endpoint; >0 = paid there).

| candidate | OR model | Ctx | T | S | R | OR $ | free path |
|---|---|---|---|---|---|---|---|
| muse-spark-1.3 | meta/muse-spark-1.3-contributor | 1M | Y | Y | Y | paid 0.10/M | Kilo (unverified) |
| mimo-v2.6-flash | xiaomi/mimo-v2.6-flash | 1.05M | Y | Y | Y | paid 0.14/M | Kilo (unverified) |
| laguna-s-2.1 | poolside/laguna-s-2.1:free | 262k | Y | – | Y | free | OR `:free` + Kilo |
| nemotron-3-ultra-550b | nvidia/nemotron-3-ultra-550b-a55b:free | 1M | Y | – | Y | free | OR `:free` + Kilo |
| nemotron-3-super-120b | nvidia/nemotron-3-super-120b-a12b:free | 262k | Y | Y | Y | free | OR `:free` + Kilo |
| inkling-small | thinkingmachines/inkling-small:free | 1M | Y | – | Y | free | OR `:free` + Kilo |
| step-3.7-flash | stepfun/step-3.7-flash | 262k | Y | Y | Y | paid 0.20/M | Kilo (unverified) |
| ling-3.1-flash | inclusionai/ling-3.1-flash | 262k | Y | – | Y | 0/0, no marker | unknown (kept) |
| north-mini-code | cohere/north-mini-code:free | 256k | Y | – | Y | free | OR `:free` + Kilo |
| longcat-2.5-preview | meituan/longcat-2.0 | 1M | Y | – | Y | paid 0.30/M | Kilo (unverified), experimental |
| apodex-1.1-mini | apodex/apodex-1.1-mini:free | 262k | Y | Y | Y | free | OR `:free` |
| ling-3.0-flash-sante | inclusionai/ling-3.0-flash-sante:free | 262k | Y | – | Y | free | OR `:free` |
| dots-3-note-preview | dots-studio/dots-3-note-preview:free | 512k | Y | Y | Y | free | OR `:free` |
| lfm-2.5-2.6b | liquid/lfm-2.5-2.6b:free | 65k | Y | Y | Y | free | OR `:free` (fast/small) |
| nemotron-3.5-lightning | nvidia/nemotron-3.5-lightning:free | 1M | Y | – | Y | free | OR `:free` |
| inkling | thinkingmachines/inkling:free | 1M | Y | – | Y | free | OR `:free` |
| laguna-xs-2.1 | poolside/laguna-xs-2.1:free | 262k | Y | – | Y | free | OR `:free` (fast) |
| nemotron-3-nano-omni-30b | nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | 256k | Y | – | Y | free | OR `:free` |
| gemma-4-26b | google/gemma-4-26b-a4b-it:free | 262k | Y | Y | Y | free | OR `:free` |
| gemma-4-31b | google/gemma-4-31b-it:free | 262k | Y | Y | Y | free | OR `:free` |

Excluded as ordinary models: router IDs (`openrouter/auto`, `openrouter/free`,
`kilo-auto/*`, … — see `ROUTER_IDS`) and safety-only
`nvidia/nemotron-3.5-content-safety` (`SAFETY_ONLY_IDS`). Multimodal: no
OpenRouter capability evidence → all `multimodal: null` (untested, eligible).

Live status 2026-10-08: all completion smokes `AUTH_REQUIRED` (no
`OPENROUTER_API_KEY`/`KILO_API_KEY` in env). `GET /v1/models` listing = LIVE_OK.
No keys → no latency/TTFT measurements this round.

## 2. Benchmarks

Public web benchmark lookup was unavailable in-session; no reliable citable
scores were obtained for these model IDs. Per the never-invent rule, none are
recorded: every entry keeps `benchmark.source: null` and prior-based scoring
with the confidence penalty for unmeasured models. Refresh procedure: when a
sourced score (SWE-bench, Terminal-Bench, Aider/Polyglot, LiveCodeBench,
agent/tool-use) is found, set `benchmark{source,date,note}` + corresponding
`priors{}` on the entry and cite the source here with date + confidence.

## 3. Rankings (03:02Z calibrated: 10 models carry measured benchmark priors — see §0; rest operator priors + verified capabilities; both keys configured, no telemetry)

Deterministic output of `rank_candidates` (12 components × task weights +
free-tier adjust ±). Live telemetry (tool/SO rates, cooldowns, EMA latency)
reorders these at runtime — rankings are starting positions, not hardcoding.
Deduped to one line per candidate (best upstream shown).

### Global (GENERAL)
1. muse-spark-1.3 (kilo) 0.823 · 2. mimo-v2.6-flash (kilo) 0.822 ·
3. nemotron-3-super-120b (kilo) 0.818 · 4. step-3.7-flash (kilo) 0.811 ·
5. inkling-small (kilo) 0.771 · 6. laguna-s-2.1 (kilo) 0.765

### Build / coding (CODING, T1–T2)
1. muse-spark-1.3 (kilo) 0.842 · 2. mimo-v2.6-flash (kilo) 0.820 ·
3. step-3.7-flash (kilo) 0.819 · 4. nemotron-3-super-120b (kilo) 0.814 ·
5. laguna-s-2.1 (kilo) 0.792 · 6. inkling-small (kilo) 0.771

### Explore (fast/cheap capable: FAST_SIMPLE)
1. step-3.7-flash (kilo) 0.835 · 2. inkling-small (kilo) 0.824 ·
3. mimo-v2.6-flash (kilo) 0.818 · 4. north-mini-code (kilo) 0.804 ·
5. lfm-2.5-2.6b (openrouter) 0.791 · 6. ling-3.1-flash (kilo) 0.785

### Plan / Architecture (PLANNING T3)
1. muse-spark-1.3 (kilo) 0.843 · 2. nemotron-3-super-120b (kilo) 0.833 ·
3. mimo-v2.6-flash (kilo) 0.822 · 4. laguna-s-2.1 (kilo) 0.780 ·
5. inkling-small (kilo) 0.770 · 6. nemotron-3-ultra-550b (kilo) 0.770

### Reviewer (strong + independent: prefer non-Build winner)
Build winner (muse-spark-1.3) excluded → nemotron-3-super-120b (0.833),
mimo-v2.6-flash (0.822) lead under T3 re-weight; same evidence basis as Plan.
Independence = different candidate family from the author, enforced by
operator choice, not code.

### Debug / Research (RESEARCH)
1. nemotron-3-super-120b (kilo) 0.848 · 2. mimo-v2.6-flash (kilo) 0.836 ·
3. muse-spark-1.3 (kilo) 0.834 · 4. step-3.7-flash (kilo) 0.819 ·
5. inkling-small (kilo) 0.815 · 6. nemotron-3-ultra-550b (kilo) 0.798

### Speed / token-efficiency (CODING T0)
1. muse-spark-1.3 (kilo) 0.835 · 2. step-3.7-flash (kilo) 0.824 ·
3. mimo-v2.6-flash (kilo) 0.823 · 4. nemotron-3-super-120b (kilo) 0.808 ·
5. inkling-small (kilo) 0.791 · 6. laguna-s-2.1 (kilo) 0.788
Cheapest verified-free fast lanes: lfm-2.5-2.6b, laguna-xs-2.1, north-mini-code
(small/fast latency class, `:free` on OpenRouter).

### Provider reliability (qualitative, 2026-10-08)
- openrouter: listing LIVE_OK; 10/10 registry IDs resolvable; 15 verified
  `:free` endpoints. paid-route risk on 5 non-suffix IDs → router prefers
  Kilo there via free-tier penalty (−0.05).
- kilo: UNREACHABLE without key (AUTH_REQUIRED assumed); slugs for the 10 new
  models mirrored from the OpenRouter pattern, explicitly unverified.
- Fallback order (code): top score → next on retryable; non-retryable
  (auth/invalid/capability) continues only to different-credential candidates;
  routers/safety never leaves; relaxed filter never strands a request.

## 4. Routing policy (typical)

T0 → fastest capable (T0 latency×2 re-weight) · T1 → efficient coding ·
T2 → strong coding/reasoning (default) · T3 → strongest eligible
(quality/reasoning/agentic×1.5) · Explore → fast/cheap (FAST_SIMPLE class) ·
Review → strong, preferably independent family · Research → strong,
long-context (context weight 0.18). Override per request with explicit
`[T0]`–`[T3]` tag or `complexity` field; `session_id` pins the winner while
eligible. Fallback: verified-free upstream → other provider → different
credential → 503 `all_candidates_exhausted` (never infinite retry; each
upstream tried ≤ once per request).
