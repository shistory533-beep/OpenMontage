# FACTORY_ARCHITECTURE_AUDIT — YouTube Documentary Production Factory

> Status: **audit only — no code modified.**
> Branch: `main` @ `9327439` (Merge PR #527). Verified `git status` clean vs `origin/main`.
> Method: read `AGENT_GUIDE.md`, `PROJECT_CONTEXT.md`, `docs/ARCHITECTURE.md`, `docs/PROVIDERS.md`,
> `docs/provider-update-plan-2026-10-03.md`, all `pipeline_defs/*.yaml`, `lib/checkpoint.py`,
> `lib/corpus.py`, `lib/media_profiles.py`, `tools/video/corpus_builder.py`,
> `tools/video/clip_search.py`, `tools/video/direct_clip_search.py`,
> `tools/publishers/export_bundle.py`, registry capability dump (live `tool_registry.discover()`),
> `schemas/artifacts/*`, `skills/pipelines/documentary-montage/*`, `tests/{contracts,qa,tools}`,
> backlot layout. Code/tests/artifacts treated as authoritative over prose docs.

> Note on prompt assumptions: **`docs/openmontage/*` does not exist** in this tree
> (`docs/` = `ARCHITECTURE.md`, `PROVIDERS.md`, `provider-update-plan-2026-10-03.md`,
> `stage-gates/`, `comfyui-adapter-plan.md`, misc). There is also no `factory/` directory,
> no OpenCode/Kilo config file (`opencode.json` / `.opencode/` absent; agent config lives in
> `AGENT_GUIDE.md` + `CLAUDE.md`/`CODEX.md`/`CURSOR.md`/`COPILOT.md` → `PROJECT_CONTEXT.md`).
> References below are to what actually exists.

---

## 0. TL;DR

- The closest thing to a "documentary factory" is **`documentary-montage` (beta, 5 stages:
  `idea → scene_plan → assets → edit → compose`)**. It is the only retrieval-first,
  real-footage pipeline and the correct foundation. It is **not** a YouTube factory:
  it has **no `research`, `proposal`, `script`, or `publish` stage** (all other
  content pipelines have 7–8 stages ending in `publish`; cf. `animated-explainer.yaml`).
- The **core infrastructure a factory needs already exists and is production-capable**:
  checkpoint/state machine, schema-validated artifacts, tool registry + selectors,
  corpus + CLIP retrieval + direct acquisition, local-first TTS (`piper_tts`),
  `audio_mixer`, `subtitle_gen`, multi-runtime compose, `export_bundle`, YouTube
  render profiles, cost governance, Backlot observer board.
- What is **genuinely missing** is the factory *wrapper*: producer orchestration,
  research grounding, script-with-citations, fact-check gate, storyboard approval,
  narration lane inside the doc pipeline, render QA wiring, YouTube upload, analytics.
  All of these can be added as **new pipeline + new tools + new schemas/skills**
  without touching the working core.
- Recommended path: **new `youtube-documentary` pipeline manifest** that reuses
  `documentary-montage` stages/tools verbatim and adds the missing stages around them.
  Never edit `documentary-montage.yaml`, `lib/corpus.py`, `lib/checkpoint.py`,
  `tools/video/{corpus_builder,clip_search,direct_clip_search}.py`, or the
  `BaseTool` contract in this effort.

---

## 1. What already exists and is production-capable

Verified against code + live registry, not docs prose.

### 1.1 Orchestration / state (do not rebuild)

| Component | File | Verdict |
|---|---|---|
| Checkpoint state machine (write/read/resume, gate enforcement, prerequisite enforcement, history archival, decision-log merge) | `lib/checkpoint.py` (633 lines, read fully) | **Production.** Gate violation + prerequisite violation are hard errors; atomic tmp-write + `history/` archival. Factory gets resumability/determinism for free by using it. |
| Pipeline manifest loader + per-pipeline stage order | `lib/pipeline_loader.py`, `pipeline_defs/*.yaml` | **Production.** `get_pipeline_stages()` already supports pipelines with non-canonical stages (e.g. `character-animation` custom stages). New factory stages need no loader change. |
| Artifact schema validation (21 artifact schemas) | `schemas/artifacts/` | **Production.** `script.source_ref`, `asset_manifest.{provider,license,original_url}`, `edit_decisions.{render_runtime,renderer_family}`, `publish_log`, `research_brief`, `proposal_packet`, `decision_log` all exist. |
| Tool registry + discovery + selectors | `tools/tool_registry.py`, live `capability_catalog()` dump | **Production.** Capabilities present: `tts` (14 tools), `clip_retrieval`, `corpus_population`, `clip_acquisition`, `music_generation/_library/_search`, `subtitle`, `video_post`, `audio_processing`, `analysis` (13 tools incl. `visual_qa`, `composition_validator`), `publish` (1 tool). Selector pattern (`tts_selector`, `image_selector`, `video_selector`) keeps providers replaceable. |
| Cost governance | `tools/cost_tracker.py`, `config.yaml` budget block | **Production.** `warn` mode default, $10 total. Factory's free/local-first rule maps to $0 estimates on retrieval/local tools. |
| Backlot board (observer, never blocker) | `backlot/` (`server.py`, `state.py`, `ui/`) | **Production pattern.** Reads `projects/<id>/` + checkpoints. New pipeline is visible with zero board change provided it follows the project-directory convention. |

### 1.2 Real-footage retrieval (the philosophy to preserve)

| Component | File | Verdict |
|---|---|---|
| Append-only corpus + fused visual/tag ranking + MMR + diversify + crash-safe load/save | `lib/corpus.py` (431 lines, read fully) | **Production-capable core.** JSONL = source of truth, `.npy` truncated to match on drift. Factory must reuse as-is. |
| `corpus_builder` (fan-out search → download → thumb → CLIP embed → index; per-source/per-candidate error isolation; `max_new_clips` cap; `skip_existing` idempotence; shared clip-bytes cache) | `tools/video/corpus_builder.py` (714 lines) | **Production-capable.** `stability: EXPERIMENTAL` but failure semantics are careful (total-failure returns `success=False` instead of persisting an empty index). Free-tier (`estimate_cost = 0.0`). |
| `clip_search` (`rank_for_slot`, `find_similar_set`, `diversify`, `get`, `stats`) | `tools/video/clip_search.py` | **Production-capable**, `LOCAL` runtime, $0. |
| `direct_clip_search` (fast path, no CLIP, ffmpeg mid-thumb, wall-clock deadline + partial-progress timeout result) | `tools/video/direct_clip_search.py` (663 lines) | **Beta but sound.** Correct fast lane for act-by-act factory work. |
| Stock adapters (17): `pexels`, `pixabay_video`, `archive_org`, `nasa`, `wikimedia`, `unsplash`, `coverr`, `dareful`, `esa`, `jaxa`, `loc`, `mixkit`, `nara`, `noaa`, `pond5_pd`, `videvo` (+ `base.py` protocol) | `tools/video/stock_sources/` | **Production-capable breadth.** Key fact for the factory: `archive_org`, `nasa`, `wikimedia` and most public-archive adapters work **without API keys** — the free/local-first constraint is satisfiable. Pexels/Pixabay/Unsplash need free keys. Pinned-but-unavailable sources are hard errors, not silent degradation (correct governance). |
| Provenance on every record | `ClipRecord.{source,source_id,source_url,creator,license,query,source_tags}` + `asset_manifest.{provider,license,original_url}` | **Production.** Rights tracking already flows corpus → manifest. Factory must extend, never weaken. |

### 1.3 Narration / audio / editorial / render / QA modules

| Capability | Tools | Verdict |
|---|---|---|
| TTS | 13 providers + `tts_selector`: `piper_tts` (**LOCAL**, offline, no key), `google_tts` (1M chars/mo free per voice tier), `azure_tts`, `elevenlabs_tts`, `doubao_tts`, `fish_audio_tts`, `gemini_tts`, `cartesia_tts`, `inworld_tts`, `dashscope_tts`, `kling_tts`, `openai_tts`, `fal_elevenlabs_tts` | **Production.** Free/local-first narration = `piper_tts` default → `google_tts` free tier → paid opt-in. No hard paid dependency today; keep it that way. Voice-performance contract already in `script.schema.json` (`voice_performance`, per-section `delivery_cues`, `provider_text`). |
| STT / transcription (QA + subtitle timing) | `transcriber` (local faster-whisper, default offline), `azure_stt`, `dashscope_asr` (word timestamps) | **Production.** |
| Music (mandatory plan at proposal per AGENT_GUIDE) | `music_library/` drop path + `music_library` tool, `freesound_music` + `pixabay_music` (free search), `music_gen`/`google_music`/`suno_music`/`comfyui_music` (generative) | **Production.** Factory should default to library + royalty-free search, matching the no-paid-hard-dep rule. |
| Mix | `audio_mixer` (ducking, loudnorm, segmented music, target-duration) + `audio_enhance` | **Production** (dedicated tests: ducking, loudnorm, fades, target duration). |
| Subtitles | `subtitle_gen` + `remotion_caption_burn` | **Production.** |
| Analysis / QA | `scene_detect`, `frame_sampler`, `video_analyzer`, `video_understand`, `audio_probe`, `audio_energy`, `face_tracker`, `composition_validator`, `visual_qa` | **Production tools, unwired in doc pipeline** (see §2 — this is a wiring gap, not a missing-capability gap). |
| Compose runtimes | `video_compose` (Remotion / HyperFrames / FFmpeg routing locked by `edit_decisions.render_runtime`) + `video_stitch`, `video_trimmer`, `auto_reframe`, `silence_cutter`; `color_grade`; `lib/media_profiles.py` (`youtube_landscape`, `youtube_4k`, `youtube_shorts`, …) | **Production.** Constraint: `documentary-montage` compose-director currently **locks `render_runtime="remotion"`** (CinematicRenderer + ProRes-4444 end-tag overlay stack; HyperFrames parity explicitly deferred). Factory must inherit this lock until parity lands. |
| Publish (local) | `export_bundle` (`capability="publish"`, `provider="local"`, `supports.uploads=False`) | **Production for local handoff; not a YouTube publisher.** Its own docstring says: *"A networked publisher (e.g. a YouTube uploader) can be added later as a separate `provider` under the same `publish` capability."* That is exactly the seam to use. |
| Tests | `tests/contracts/` (tool/registry/manifest/governance incl. `test_documentary_governance.py`), `tests/qa/` (8 end-to-end QA scripts + `QA_PLAN.md`), `tests/tools/` (per-tool incl. corpus/cache/mixer/export), `tests/eval/` replay harness | **Production discipline.** Any factory addition must add contract tests in the same pattern, not retrofit old ones. |

---

## 2. What is missing for a YouTube Factory

Mapped to the requested chain
`Producer → Research → Script → Fact Check → Storyboard → Footage → TTS →
Editorial → Render → QA → YouTube → Analytics`.

| # | Chain link | Current state | Gap class |
|---|---|---|---|
| 1 | **Producer** | Each pipeline has an `executive-producer.md`, but it governs **one short piece** (doc-montage: 30–180 s tone poem). No series/show producer: no episode plan, no format bible, no per-episode budget rollup, no release cadence, no cross-episode reuse policy. | **Missing.** New skill + new artifact (`series_bible` / `episode_plan`). |
| 2 | **Research** | `research_brief.schema.json` exists and is strong (landscape, data_points, angles, 5+ sources). But `documentary-montage.yaml` **has no `research` stage** — its stage list is `idea → scene_plan → assets → edit → compose`, vs 8 stages on every generated pipeline. Research is therefore unenforced for the footage pipeline. | **Missing stage** (schema exists, wiring absent). |
| 3 | **Script** | `script.schema.json` supports `source_ref` per section + voice-performance contract. But doc-montage has **no `script` stage** — it goes `idea → scene_plan` directly (music + visuals carry the register; narration optional by design). A narrated YouTube documentary needs a scripted spine with citations. | **Missing stage** on this pipeline (do not repurpose `scene_plan.slots` as script). |
| 4 | **Fact Check** | No fact-check tool, skill, artifact, or gate anywhere. `grep -ri fact.check` hits only unrelated governance docs. `script.source_ref` and `research_brief.data_points[].credibility` are *fields*, not a *verification pass*. No claim↔source traceability check, no credibility threshold, no quarantine path for failed claims. | **Missing capability.** New validator tool + gate. |
| 5 | **Storyboard** | `scene_plan` on doc-montage is **slot-based** (`metadata.slots[]` with queries + `preferred_sources`), not a visual storyboard: no per-shot thumbnail approval, no shot-language lock, no hero-hold durations bound to narration. Generic `scene_plan.schema.json` has `shot_language`/`narrative_role` but the doc pipeline's director skill does not enforce them. | **Missing approval artifact.** Needs a `storyboard` view derived from slots + retrieved thumbs (new artifact or `scene_plan` extension + human gate), not a schema rewrite. |
| 6 | **Footage** | Exists and is the strongest link (§1.2). Gaps are factory-scale, not capability: no episode-level corpus reuse policy (per-project corpus only), no rights **clearance status** beyond storing `license` strings (no allow/deny/reviewed flag), no duration-coverage solver (slots→seconds arithmetic lives in prose). | **Missing policy + minor fields**, not missing tools. |
| 7 | **TTS** | 14-way TTS exists, but `documentary-montage.yaml` assets stage lists only `direct_clip_search / corpus_builder / clip_search / music_gen` — **no TTS tool**. Narration lane is structurally absent (consistent with "narration optional" philosophy, but a YouTube factory needs it as an opt-in lane). | **Missing lane**, not missing providers. Add `tts_selector` (+ `subtitle_gen`) to the new pipeline's assets stage. |
| 8 | **Editorial** | `edit_decisions` schema is expressive (cuts, overlays, `audio.{narration,music,sfx}`, subtitles, transitions, `renderer_family` + `render_runtime` locks). Doc pipeline's edit-director enforces montage-specific rules (hero holds, ≤4 transitions, end-tag timing). Missing for long-form YouTube: chapter markers → description chapters, retention-beat validation, narration↔cut duration reconciliation (exists for mixer in tests, not as an edit gate). | **Missing gates**, not missing schema. |
| 9 | **Render** | `video_compose` + YouTube profiles exist. Doc pipeline compose gates on ffprobe + end-tag + music-mixed flags. No long-form render concerns: no part-based rendering, no resume-after-render-failure, no loudness-target enforcement at compose. | **Missing scale policy.** |
| 10 | **QA** | `visual_qa`, `composition_validator`, `transcriber`-based A/V sync checks exist as tools but are **not in any doc-montage stage's `tools_available`** and no QA report artifact is required before `compose → completed`. `final_review.schema.json` exists but doc-montage compose does not produce it (explainer compose does). | **Missing wiring.** Biggest cheap win: require `final_review` + QA tool pass. |
| 11 | **YouTube** | `export_bundle` only (`status: "exported"`, `uploads: False`). **No uploader, no OAuth, no metadata optimizer, no thumbnail generator** (thumbnail is a pass-through `thumbnail_path` or `thumbnail_concept` JSON). `publish_log` schema already supports `published / draft / pending_review` + `video_id` + `url` + `visibility` — the artifact is ready, the tool is not. | **Missing tool.** Must be additive (`capability="publish"`, new provider), optional, never required for local runs. |
| 12 | **Analytics** | Nothing: no artifact, no tool, no schema, no skill. No view/retention ingestion, no episode-to-episode learning loop back into Producer. | **Missing capability**, correctly last in sequence. |

Also missing cross-cutting: a **`proposal` stage** on doc-montage (no cost/plan approval gate before corpus spend — worth noting that corpus spend is $0/network-time, so this is lower risk than generated pipelines, but a YouTube factory with narration + long renders needs the budget gate the explainer pipeline already has).

---

## 3. Components that must remain unchanged

Freezing these is the "without destabilizing the core" guarantee. Evidence cited per item.

| # | Frozen component | Why (evidence) |
|---|---|---|
| F1 | `lib/checkpoint.py`, `lib/pipeline_loader.py`, `lib/corpus.py`, `lib/clip_embedder.py` | Resume/determinism/history/gate guarantees live here. `Corpus` JSONL↔npy alignment + truncation recovery is load-bearing for every retrieval run. |
| F2 | `tools/base_tool.py` contract + `tools/tool_registry.py` discovery | All 100+ tools + selectors + `support_envelope()` depend on it. Factory adds tools *through* it, never around it. |
| F3 | `tools/video/{corpus_builder,clip_search,direct_clip_search}.py` + `tools/video/stock_sources/*` adapter protocol | Retrieval semantics + provenance + pinned-source hard errors are audited behavior (`test_documentary_governance.py`, `test_corpus_builder_total_failure.py`, `test_clip_cache.py`). Extend by adding sources, not editing dispatch. |
| F4 | `pipeline_defs/documentary-montage.yaml` + `skills/pipelines/documentary-montage/*` | The only retrieval-first pipeline and its quality bar (slot queries, hero slots, per-slot picks, no double-pick, music + end-tag mandates, Remotion lock). Factory must **reference, not fork** these until a deliberate v2. |
| F5 | `tools/video/video_compose.py` runtime routing + Remotion lock on doc-montage | Silent runtime swap is already a `CRITICAL` governance violation in two director skills. Factory inherits; HyperFrames parity is a separate project. |
| F6 | `schemas/artifacts/*` + `schemas/checkpoints/*` + `schemas/pipelines/*` (existing versions) | 21 artifact schemas + contract tests validate them. New factory needs mean **new schemas / backward-compatible optional fields**, never breaking edits to `brief@1.0`, `scene_plan@1.0`, `asset_manifest@1.0`, `edit_decisions@1.0`, `render_report@1.0`. |
| F7 | `tools/audio/audio_mixer.py`, `tools/subtitle/subtitle_gen.py`, `tools/publishers/export_bundle.py`, `lib/media_profiles.py` | Tested render/audio/publish path. YouTube upload must be a *sibling* tool, not an edit to `export_bundle`. |
| F8 | Governance in `AGENT_GUIDE.md` (Rule Zero, preflight, decision-log re-log rule, both-runtimes rule, blocker escalation, music-plan-mandatory, checkpoint protocol) | The factory adds stages *inside* this governance; it must not weaken approval defaults or log semantics. |

---

## 4. Where new modules should be added (additive-only map)

Convention: new pipeline reuses core; new tools go in capability packages; new schemas are new files or new versions; new skills under a new namespace. No existing file is edited except registries that auto-discover (no edit needed) and docs.

```
pipeline_defs/
  documentary-montage.yaml        # FROZEN (F4)
  youtube-documentary.yaml        # NEW — factory pipeline (12 stages, §5)

skills/pipelines/youtube-documentary/
  executive-producer.md           # NEW — series/episode producer (format bible, episode slate)
  research-director.md            # NEW — may largely reference explainer research-director
  proposal-director.md            # NEW — cost/plan gate incl. narration + long-render budget
  script-director.md              # NEW — narrated script w/ source_ref per claim (extends explainer script-director)
  factcheck-director.md           # NEW — claim verification gate
  storyboard-director.md          # NEW — slot→thumb board approval (human gate)
  asset-director.md               # NEW — thin wrapper: delegates footage to doc-montage asset rules + adds TTS lane
  edit-director.md                # NEW — doc-montage edit rules + chapters + narration sync
  compose-director.md             # NEW — doc-montage compose rules + loudness + part-render policy
  qa-director.md                  # NEW — visual_qa + composition_validator + A/V sync → final_review (human gate)
  publish-director.md             # NEW — export_bundle (default) + youtube_upload (opt-in)
  analytics-director.md           # NEW — performance ingest → learnings back to producer

tools/
  analysis/fact_check.py          # NEW — capability="fact_verification", LOCAL; checks script claims vs research_brief
  video/storyboard_assembler.py   # NEW — capability="storyboard"; slots × picks → review board (thumbs + holds)
  publishers/youtube_upload.py    # NEW — capability="publish", provider="youtube", API/HYBRID; resumable upload, draft default
  analytics/youtube_analytics.py  # NEW — capability="analytics", provider="youtube"; read-only ingest → analytics_report
  (reuse unchanged: corpus_builder, clip_search, direct_clip_search, tts_selector,
   subtitle_gen, audio_mixer, video_compose/stitch/trimmer, color_grade,
   visual_qa, composition_validator, transcriber, music_library/search, export_bundle)

schemas/artifacts/
  (existing 21 files FROZEN)
  factcheck_report.schema.json    # NEW — claim verdicts (verified/needs-source/quarantined)
  storyboard.schema.json          # NEW — per-shot thumb + hold + narration binding + approval flag
  youtube_metadata.schema.json    # NEW — title/description/tags/chapters/thumbnail concept
  analytics_report.schema.json    # NEW — episode metrics + learnings

lib/
  youtube_metadata.py             # NEW (optional helper: chapters→description, title rules) — pure function, no orchestration
  (lib/checkpoint.py, corpus.py — FROZEN)

tests/
  contracts/test_youtube_documentary_contracts.py  # NEW — manifest/stage/artifact/tool-presence gates
  tools/test_fact_check.py / test_storyboard_assembler.py / test_youtube_upload.py  # NEW (mocked network)
  qa/test_10_youtube_factory_e2e.py               # NEW — offline path only (export_bundle, never upload)

projects/<episode>/               # unchanged layout + new artifacts alongside canonical ones
```

Provider-replaceability note: `youtube_upload` and `youtube_analytics` must declare
`fallback_tools: ["export_bundle"]` and `agent_skills` pointing at Layer-3 OAuth/upload
guidance; absence of credentials degrades to `exported` locally, never blocks compose/QA.
No paid service appears in any `required_tools`.

---

## 5. Interfaces / contracts between stages

Each row is a **handoff contract**: producer artifact → consumer validation → gate.
All artifacts schema-validated at `write_checkpoint` time (existing enforcement, `lib/checkpoint.py:124-158`).
Every stage writes explicit state (`in_progress` on entry, `completed`/`awaiting_human` on exit) —
no stage is considered done without its canonical artifact + validation.

| Handoff | Producer → artifact | Consumer validation (fail-closed) | Human gate |
|---|---|---|---|
| **Producer → Research** | `executive-producer` → `episode_plan` (series bible ref, format, target duration 8–15 min YouTube default, budget cap, reuse policy) + `project.json` via `init_project` | `pipeline_loader` stage order; `episode_plan.episode_id == project_id`; budget ≤ series cap | Producer slate approval (`awaiting_human`) |
| **Research → Script** | `research-director` → `research_brief` (existing schema: ≥3 data_points, ≥3 angles, ≥5 sources) | Script may only cite `data_points[].claim` URLs present in `sources[]`; credibility carried forward | No (auto, per explainer precedent) |
| **Script → Fact Check** | `script-director` → `script` (existing schema; **every factual section requires `source_ref`**; `voice_performance` block mandatory for TTS lane) | `fact_check` tool: each `source_ref` resolves to a `research_brief` source; quote/number match; verdict per claim | Script approval (`awaiting_human`) |
| **Fact Check → Storyboard** | `factcheck-director` → `factcheck_report` (`verified[]`, `needs_source[]` → sent back, `quarantined[]` → cut from script, re-checkpoint script v+1) | Storyboard stage refuses `script` version whose `factcheck_report.status != "passed"`; quarantine list must be empty or explicitly waived with `decision_log` entry | Fact-check sign-off (`awaiting_human` if any quarantine) |
| **Storyboard → Footage** | `storyboard-director` → `storyboard` (slot × candidate thumbs + hold durations + narration binding; approval flag per shot) | Footage acquisition queries **must equal** storyboard slot queries (query-drift check); `preferred_sources` distribution preserved (era_mix) | **Storyboard approval (`awaiting_human`)** — the visual promise |
| **Footage → TTS** | doc-montage asset rules → `asset_manifest` (one picked clip per slot, no double-pick, full provenance; `metadata.corpus_stats` or `search_stats`) + rights `clearance: {cleared, needs_review, blocked}` per asset (new optional field) | TTS lane validates total narration seconds vs sum of slot holds (±10%); blocked-clearance assets must be replaced before edit | Asset filmstrip approval (`awaiting_human`, inherited from doc-montage) |
| **TTS → Editorial** | `tts_selector` (+ `subtitle_gen` draft) → narration assets appended to `asset_manifest` with `voice_performance` receipt fields (existing sub-schema) | Every `script` section has exactly one narration asset; sample section approved before batch (existing `sample_approved` field) | No (mechanical; reviewer skill only) |
| **Editorial → Render** | `edit-director` → `edit_decisions` (cuts + `audio.narration` segments + chapters + `render_runtime="remotion"` + `renderer_family="documentary-montage"` carried unchanged) | `total_duration == Σ cuts` (±10% of brief); narration segments cover script order with no gaps; chapters map to `youtube_metadata.chapters` | Edit approval (`awaiting_human`, inherited) |
| **Render → QA** | `compose-director` → `render_report` (ffprobe-passed outputs + `music_mixed=true` + end-tag flags + loudness attestation) | File exists + duration/resolution match + LUT uniformity note + loudness target; `render_report` written only on pass | No (auto; failures → `failed` checkpoint + structured blocker) |
| **QA → YouTube** | `qa-director` → `final_review` (existing schema; `visual_qa` + `composition_validator` + transcribe-and-compare narration check all pass) | Publish stage refuses `render_report` without a passing `final_review` ref (same pattern as explainer `publish.required_artifacts_in: [render_report, final_review]`) | **QA sign-off (`awaiting_human`)** |
| **YouTube → Analytics** | `publish-director` → `publish_log` (`exported` always; `published/draft` only via `youtube_upload` with explicit approval + `visibility` default `unlisted`) + `youtube_metadata` | Upload tool validates metadata schema + thumbnail presence + chapter timestamps < duration; credential absence → local-export degradation path | **Publish approval (`awaiting_human`)** — nothing uploads without it |
| **Analytics → Producer (loop)** | `analytics-director` → `analytics_report` (retention, CTR, chapter drop-off → learnings) | Learnings append to series bible as advisory notes only; never mutate past checkpoints (append-only history, `history/` preserved) | No (informational) |

Determinism rules per stage (enforced by tool contracts, not new framework):
seeds/model versions recorded in `asset_manifest`; corpus snapshot id (`index.jsonl` hash)
recorded in storyboard checkpoint; TTS voice+settings pinned in `voice_performance` receipt;
upload is idempotent on `(episode_id, cut_hash)` — re-publish without new render is a no-op.

---

## 6. How to add the system without breaking existing behavior

1. **Additive-only diff.** New files only (§4). Zero edits to F1–F8. The registry auto-discovers
   new `BaseTool` subclasses — no registration edit, no selector code change
   (selectors query `get_by_capability`; `youtube_upload` appears under `publish` automatically).
2. **New pipeline, not a modified one.** `youtube-documentary.yaml` declares its own 12 stages;
   `get_pipeline_stages("youtube-documentary")` already resolves correctly through the existing
   loader. `documentary-montage` remains the short-form path; the factory delegates its footage
   stages by *referencing the same tools + director rules*, not by importing the manifest.
3. **Schema discipline.** New artifacts are new files. If an existing artifact needs a factory
   field (e.g. rights `clearance` on manifest assets), add it as an **optional property** in a
   backward-compatible way with contract-test proof that old fixtures still validate —
   or keep it in the new `storyboard`/`factcheck_report` artifacts instead. Prefer the latter.
4. **Capability-gated degradation.** `youtube_upload` / `youtube_analytics` are `optional_tools`
   with `export_bundle` fallback. Preflight (`provider_menu_summary()`) shows them as
   "0/1 configured → local export available"; missing creds never fail preflight.
5. **Governance inheritance.** New manifest copies the doc-montage gate pattern
   (`human_approval_default: true` on producer/research-approval/script/storyboard/assets/edit/QA/publish;
   `false` on mechanical research-draft/TTS/render). `decision_log` re-log rule and runtime-lock
   rule apply unchanged — new skills must quote them, not restate them.
6. **No AI-footage substitution surface.** Factory manifest's assets stage lists only
   `direct_clip_search / corpus_builder / clip_search / tts_selector / subtitle_gen /
   music_library / freesound_music / pixabay_music`; **no `*_video` generation tool,
   no `image_selector`** appears. A reviewer test asserts this closed set (see §7, step 3).
7. **Test-before-touch.** Factory PRs add `tests/contracts/test_youtube_documentary_contracts.py`
   first (manifest loads, stage order exact, required/optional tools resolve in registry,
   schemas validate fixtures). Existing suites run unmodified as the regression floor.

---

## 7. Smallest safe implementation sequence

Each step is independently shippable, each ends in a green test run, none edits frozen code.
Stop after any step with a working increment.

| Step | Deliverable | Why this order | Validation |
|---|---|---|---|
| **1. Pipeline skeleton + contracts** | `pipeline_defs/youtube-documentary.yaml` (12 stages, tools wired to *existing* tools only; upload/analytics stages call `export_bundle` stub) + `schemas/artifacts/{factcheck_report,storyboard,youtube_metadata,analytics_report}.schema.json` (minimal v1) + `tests/contracts/test_youtube_documentary_contracts.py` | Proves the stage machine, checkpoint gates, and Backlot visibility with zero new tool code. Catches manifest/schema errors cheapest. | `pytest tests/contracts/test_youtube_documentary_contracts.py` + `pytest tests/contracts/` full green |
| **2. Fact-check gate** | `tools/analysis/fact_check.py` (LOCAL, $0, mocked-source tests) + `skills/pipelines/youtube-documentary/factcheck-director.md` + wire `factcheck_report` into stage 5 | Smallest new capability; converts existing `source_ref` fields into an enforced gate. No footage/render interaction. | `pytest tests/tools/test_fact_check.py tests/contracts/` |
| **3. Storyboard approval** | `tools/video/storyboard_assembler.py` (LOCAL: slots × picks → thumb board JSON) + `storyboard` schema v1 + `storyboard-director.md` with `awaiting_human` gate + **closed-asset-set test** (no generative video/image tools in factory assets stage) | Locks the visual promise before any download spend; provenance/rights `clearance` flag lands here as optional metadata. | QA plan § storyboard: thumbs resolve, one-pick-per-slot, no double-pick |
| **4. Narration lane** | Factory `asset-director.md` TTS lane (`tts_selector` default `piper_tts`, sample-before-batch via existing `sample_approved` receipt) + duration-reconciliation check (narration Σ vs slot holds ±10%) | Reuses 14 existing TTS providers; only new code is the lane rule + check. Keeps doc-montage's "narration optional" intact by making narration opt-in at Producer slate. | `pytest tests/tools/ -k "tts or mixer or subtitle"` + golden script fixture |
| **5. QA wiring** | `qa-director.md` requiring `visual_qa` + `composition_validator` + transcribe-compare → `final_review`; add `final_review` to publish `required_artifacts_in` | All tools exist; this is pure wiring + gate. Highest defect-catch per line changed. Mirrors explainer precedent. | `pytest tests/qa/` (offline subset) |
| **6. Local YouTube-ready publish** | `youtube_metadata` helper (`lib/youtube_metadata.py`: chapters→description, title/tags rules) + factory `publish-director.md` driving `export_bundle` with metadata + thumbnail-concept requirement | Ships a real "YouTube factory" output (upload-ready bundle) with no credentials, no network, no paid dep. | `pytest tests/tools/test_export_bundle.py` + bundle inspection |
| **7. Opt-in upload (gated)** | `tools/publishers/youtube_upload.py` (draft/`unlisted` default, resumable, idempotent on `(episode_id, cut_hash)`, `fallback_tools: [export_bundle]`) behind publish approval | Network/OAuth risk isolated to one tool, last among publish concerns, never on the default path. | Mocked-upload tests; no live upload in CI |
| **8. Analytics loop (last)** | `tools/analytics/youtube_analytics.py` (read-only) + `analytics_report` + `analytics-director.md` (advisory learnings → series bible notes) | Read-only, post-publish, zero blast radius. Correctly sequenced after the factory can actually ship episodes. | Fixture-ingest test; Backlot shows learnings note |

Out of scope for the factory MVP (explicitly deferred, not forgotten):
HyperFrames end-tag parity for doc-montage (separate render project);
Kling-4/local-LTX-2.5-gated providers (per 2026-10-03 plan, still gated);
Gemini Live interactive (separate product scope per same plan).

---

## Appendix A. Evidence index (file:line where it matters)

- Doc-montage 5-stage list + Remotion lock: `pipeline_defs/documentary-montage.yaml:45-178`
  (stages `idea,scene_plan,assets,edit,compose`; compose `review_focus` mandates `remotion`).
- Explainer 8-stage reference: `pipeline_defs/animated-explainer.yaml:61-269`.
- Checkpoint guarantees: `lib/checkpoint.py:251-347` (prerequisites), `:388-420` (decision-log merge),
  `:422-564` (gate enforcement + atomic write + history archival).
- Corpus guarantees: `lib/corpus.py:130-181` (load/save + drift truncation), `tools/video/corpus_builder.py:394-433`
  (total-failure → `success=False`), `tools/video/direct_clip_search.py:317-351` (timeout partial progress).
- Provenance fields: `lib/corpus.py:44-70` (`ClipRecord`), `schemas/artifacts/asset_manifest.schema.json:17-36`.
- Script citation + voice contract: `schemas/artifacts/script.schema.json:13-33,46-68,92-95`.
- Edit/runtime locks: `schemas/artifacts/edit_decisions.schema.json:196-210`.
- Publish seam: `tools/publishers/export_bundle.py:1-16` (docstring names the future uploader seam),
  `:54-60` (`uploads: False`), `publish_log.schema.json:18` (`published/exported/draft/pending_review`).
- Media profiles: `lib/media_profiles.py:42-68` (YouTube landscape/4K/Shorts).
- Live capability proof: `tool_registry.discover()` dump (§1 table; `tts`=14, `publish`=`export_bundle` only).
- Missing-module proof: `grep -ri fact.check|storyboard|analytics|youtube upload` → no tool/skill/schema hits
  (only governance-doc mentions); `docs/openmontage/*` and `factory/` absent on disk.

## Appendix B. Constraints compliance checklist

- [x] Real-footage philosophy: retrieval tools frozen (§3 F3); generative video/image tools excluded from factory assets by manifest + test (§6.6, §7 step 3).
- [x] Provenance/rights: existing chain preserved; `clearance` added as *status atop* stored license data, never a replacement.
- [x] No AI filler: no new generation capability proposed anywhere in this audit.
- [x] Providers replaceable: selectors + `fallback_tools` + `provider_menu` preflight retained; upload/analytics degrade to local export.
- [x] Local/free first: default paths (`corpus_builder`, `clip_search`, `piper_tts`, `music_library`/free search, `export_bundle`) are all $0; no paid `required_tools`.
- [x] No paid hard dependencies: upload/analytics are `optional_tools` with credential-absent degradation.
- [x] No core redesign without evidence: F1–F8 frozen with per-item justification; all factory work is new files.
- [x] Resumable + deterministic: inherited from `lib/checkpoint.py`; per-stage explicit state + validation table in §5; seeds/versions/snapshot-hashes recorded.
