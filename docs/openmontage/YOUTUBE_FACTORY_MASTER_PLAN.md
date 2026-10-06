# OpenMontage YouTube Factory — Master Plan (Local Source of Truth)

> Branch: `documentary-factory` | HEAD: `ba3887f` (editorial intelligence layer)
> Upstream reference: `9327439` | Date: 2026-10-06
> Status: ARCHITECTURE / RECONCILIATION ONLY — no production code changed.
> Uncommitted work preserved: `M schemas/artifacts/__init__.py` + untracked `lib/producer/` (10 files), 5 artifact schemas, 9 test files. DO NOT discard.

## 1. Current real architecture (verified locally)

### 1.1 Canonical pipeline: 19 stages, one manifest

`pipeline_defs/youtube-documentary.yaml` (19 stages) == `lib/factory_stages.py:FACTORY_STAGES` (19):

```
topic → research → evidence → script → fact_check → storyboard →
narration → footage → footage_intelligence → editorial → timeline →
audio → render → qa → packaging → thumbnail → human_review →
publish → analytics
```

Approval gates (`APPROVAL_GATES`): `topic, script, storyboard, footage, human_review, publish`.
Linear prerequisites: each stage requires the previous (`STAGE_PREREQUISITES`).

`pipeline_defs/documentary-montage.yaml` is a **legacy 5-stage** pipeline
(`idea → scene_plan → assets → edit → compose`, renderer_family `documentary-montage`,
render_runtime `remotion`). It is NOT the factory. It survives only as a render-target
lock (`lib/producer/assembly.py` sets `renderer_family=documentary-montage`).

### 1.2 Two state systems coexist — one is canonical for factory

| System | File | Scope | Factory role |
|---|---|---|---|
| Checkpoint (legacy, 9 stages) | `lib/checkpoint.py` (633 lines) | `projects/<id>/checkpoint_<stage>.json` + `project.json` | Still used by Backlot board + old pipelines. `lib/producer/producer.py` writes checkpoints alongside episode state for compat. |
| Episode Store (factory canonical) | `lib/episode_store.py` (400 lines) | `projects/<episode_id>/episode.json`, atomic tmp+`os.replace`, `history/` archival | **Source of truth for youtube-documentary.** Validated by `schemas/factory/episode_package.schema.json` (19 stages, `pipeline_type const youtube-documentary`). `transition()` / `set_artifact()` / `fail()` / `status()`. |

`lib/factory_stages.py` (239 lines, pure FSM, no I/O) is the single source of truth
for stage IDs, transitions, gates, legacy-ID migration (`sources/facts/claims → evidence`).
`lib/pipeline_guard.py` (148 lines) is additive pre-stage validation only
(predecessors completed+approved, publish blocked until `human_review` approved) — not a state machine.

### 1.3 Execution: Producer orchestration layer (NEW, untracked, uncommitted)

`lib/producer/` (10 files, tests-only callers so far, no `tools/` wrapper yet):

- `contracts.py` — `PRODUCER_STAGES` (17 = factory minus `publish, analytics`, which are
  explicitly out of scope); `QAReport`/`CheckResult` (6 areas, `QA_VERDICTS`, `READINESS`);
  `ReviewDecision`; `TitleCandidate`; `FootageMoment`/`ShotDecision`.
- `producer.py` (`ProducerAgent`, `PIPELINE_TYPE=youtube-documentary`) — deterministic
  orchestrator: EpisodeStore + guard + checkpoints, delegates to handlers in `runners.py`.
- `runners.py` — thin stage runners; content stages record `stage_inputs`, mechanical
  stages call real services (TTS Hub, FootageHub, `video_compose`, QA, packaging, review).
- `assembly.py` — **Timeline IR builder.** `select_moments()` (pass/weak only,
  gaps raise `AssemblyGapError`), `assemble_timeline()` → `edit_decisions` v1.0
  (`render_runtime=remotion`, `renderer_family=documentary-montage`),
  `retime_timeline()` / `replace_scene()` / `revise_scene()` (surgical, byte-identical
  except target scene, revision bump, re-validate).
- `audio_build.py` — mix verification, loudness (-16 LUFS target, ±3; peak -1 dBTP).
- `qa.py` (853 lines) — `QAAgent`, 6 areas (technical/audio/editorial/evidence/rights/integrity),
  fail-closed, `to_final_review()` → `final_review` schema.
- `packaging.py` — `PackageAgent` (titles 5 axes + misleading-risk gate, chapters, tags,
  thumbnail spec). `preview.py` — draft-only preview timeline (never production-ready).
- `review.py` — human review gate (`READY_FOR_REVIEW` / APPROVED / REJECTED, append-only `review_log.jsonl`).

Registered in uncommitted diff: `schemas/artifacts/__init__.py` adds
`package_bundle, preview_report, review_decision, review_package, thumbnail_set`
(+ committed schemas for `brief, research_brief, evidence_bundle, script, factcheck_report,
scene_plan, storyboard, asset_manifest, edit_decisions, render_report, final_review, publish_log`).

### 1.4 Domain hubs (committed, hardened on this branch)

- **Editorial intelligence** (`lib/editorial/`, 8 files, 65 tests): `ResearchAgent`
  (FACT/INFERENCE/OPINION/UNRESOLVED, contradictions, confidence, disk SourceCache),
  `script_agent.py` (9-beat HOOK→PAYOFF, WPM duration ±10%, numeric/quote/causal grounding),
  `factcheck.py` (6 verdicts, blockers, hash-pinned, never rewrites script),
  `storyboard.py` (12-function visual vocab, UNCERTAIN-default, `to_scene_plan()`),
  `visual_scoring.py` (12 weighted components, pass ≥0.6 / weak ≥0.4).
  Deterministic, offline, no LLM. (`EDITORIAL_INTELLIGENCE_IMPLEMENTATION.md`)
- **FootageHub** (`lib/footage_hub/` package — note: there is NO `lib/footage_hub.py` file;
  path is `lib/footage_hub/hub.py` + `contracts.py` + `registry.py` + `rights.py` + `verify.py`):
  `NormalizedAsset` (16 fields), search → normalize → rights-filter → rank → download,
  `coverage_verdict()` (MISSING/WRONG/WEAK/PASS), `RightsMode` STRICT/PERMISSIVE/AUDIT-ONLY,
  `verify.py` (ffprobe → ffmpeg-parse → magic-sniff, `MediaCorruptError` only on positive proof),
  8 factory providers (`archive_org, wikimedia, nasa, openverse, loc, dvids, pexels, pixabay_video`),
  vault `blobs/ + footage_hub_manifest.jsonl + checksums.json`, ClipCache ingest.
  Tool wrapper: `tools/video/footage_hub.py` (capability `clip_acquisition`).
  Real-footage default; fake-footage substitution is a structured blocker, never silent.
- **TTS Hub** (`lib/tts_hub/`, 9 files): `TTSProvider` protocol, `PROVIDER_ORDER =
  (kokoro, chatterbox-turbo, qwen3-tts)` — Kokoro real (11 voices, 24 kHz mono, offline retry),
  other two are stubs raising `ProviderUnavailableError`. Content-hash cache, `input_hash_for()`,
  stdlib WAV probe + **silence rejection** (`assert_not_silence`, PEAK/MEAN floors;
  `SilenceRejectedError`, never ships silence). `mapper.py` maps onto
  `asset_manifest` / `edit_decisions` / `audio_mixer`. Tool wrapper: `tools/audio/tts_hub.py`.
  Proven: 4.78 s real-audio proof; narration wired script→TTS→mixer→compose
  (25.08 s narration → 36.04 s MP4 smoke, -14.59 LUFS).

### 1.5 Timeline IR, render, QA, publish/analytics (verified)

- **Timeline IR**: canonical artifact `edit_decisions` v1.0
  (`schemas/artifacts/edit_decisions.schema.json`: `version, cuts[], render_runtime
  ∈ {remotion|hyperframes|ffmpeg}`, `renderer_family` incl. `documentary-montage`,
  `audio.{narration.segments,music,sfx}`, `subtitles, overlays, transitions`,
  bookkeeping in `metadata`). Built only by `lib/producer/assembly.py`. No second format.
  (No class named `TimelineIR` exists — "Timeline IR" is prose for `edit_decisions`.)
- **Render**: `tools/video/video_compose.py` routes on `edit_decisions.render_runtime`
  (`_render_via_hyperframes` / `_remotion_render` / `_render_via_ffmpeg`; atelier via
  `edit_decisions.bespoke`); silent swaps forbidden. Called by `runners.py:394`.
  Profiles: `lib/media_profiles.py` (`youtube_landscape/4k/shorts`, `ffmpeg_output_args()`).
- **QA**: `lib/producer/qa.py` (6 areas, ffprobe>ffmpeg-parse>wav-decode, PASS/WARN/FAIL +
  READY/BLOCKED) + `tools/analysis/` probes
  (`visual_qa, composition_validator, video_analyzer, scene_detect, frame_sampler,
  audio_probe, audio_energy, transcriber/azure_stt/dashscope_asr`).
- **Publish**: only `tools/publishers/export_bundle.py` (`supports.uploads=False`).
  **No YouTube uploader exists.** **Analytics**: no tool/skill/schema implementation;
  manifest stage is a placeholder. **Thumbnail**: no dedicated tool (pass-through
  `thumbnail_concept`; manifest `thumbnail` stage has `tools_available: []`).
- **Research/evidence as tools**: no dedicated `tools/` research tool; grounding lives in
  `lib/editorial/` + `tools/analysis/{video_downloader,transcript_fetcher}`.
  Fact-check/storyboard likewise lib-only (audit-proposed `tools/analysis/fact_check.py`
  and `tools/video/storyboard_assembler.py` were never built — correctly, per frozen-module rule).
- **Corpus/retrieval**: `lib/corpus.py` + `lib/clip_embedder.py` (CLIP ViT-B/32) +
  `tools/video/{clip_search,direct_clip_search,corpus_builder,clip_cache}.py` +
  `tools/video/stock_sources/` (18 adapters). Factory path goes through FootageHub registry (8 providers).
- **Skills**: `skills/pipelines/youtube-documentary/` has only `topic-director.md`;
  14+ stage skills unwritten. `documentary-montage/` has 7 director skills (legacy 5-stage).

## 2. Upstream/Copilot analysis vs local state

> NOTE: the external Copilot brief text was **not pasted** into the reconciliation request
> (section shows placeholder `[PASTE THE COPILOT IMPLEMENTATION BRIEF HERE]`).
> Classification below is therefore against the *known-typical* upstream-`9327439` picture
> documented in the local `FACTORY_ARCHITECTURE_AUDIT.md` (which audited main@9327439),
> plus the stage-count family (12/15/19) referenced across local implementation reports.
> Any Copilot claim outside that family is marked UNKNOWN pending receipt of the actual brief.

| # | Subject | Typical upstream/Copilot-era claim | Local truth | Verdict |
|---|---|---|---|---|
| 1 | `documentary-montage` | "this is the documentary pipeline" | Legacy 5-stage beta (`idea→…→compose`); factory pipeline is `youtube-documentary` (19). Montage survives only as render-target lock | STALE / INCORRECT if equated |
| 2 | 15-stage vs 19-stage | 12 (audit proposal) / 15 (early manifest report) | Canonical is **19** (`factory_stages.py` + current YAML, 19 `name:` entries verified). 12/15 are historical report snapshots | STALE (12/15); CURRENT (19) |
| 3 | Factory State (Episode Store) | absent at upstream | Present, committed (`episode_store.py`, envelope schema, 19-stage validation, atomic writes) | ALREADY IMPLEMENTED LOCALLY |
| 4 | Episode Store schema map | unknown | `ARTIFACT_SCHEMA_MAP` maps 8 stage groups; known gap: `storyboard→scene_plan` provisional, new review/packaging schemas unchecked at checkpoint layer | PARTIALLY TRUE (present with gaps) |
| 5 | FootageHub | generic clip search / per-provider tools | Present as package (`hub/contracts/registry/rights/verify`), 8 providers, rights modes, verification, retry, verdicts, vault + checksums | ALREADY IMPLEMENTED LOCALLY |
| 6 | TTS Hub | piper/direct provider calls | Present (`tts_hub/` 9 files), Kokoro default, hash cache, silence rejection, dry-run; wired script→TTS→mixer→compose | ALREADY IMPLEMENTED LOCALLY |
| 7 | Pipeline Guard / manifest | no manifest/guard at upstream | Present (`youtube-documentary.yaml` 19 stages + `pipeline_guard.py` + `pipeline_loader.py`) | ALREADY IMPLEMENTED LOCALLY |
| 8 | research | "no research module" | `lib/editorial/research.py` (committed, tested) | ALREADY IMPLEMENTED LOCALLY |
| 9 | evidence | sources/facts/claims fragments | Unified `evidence_bundle` schema + `LEGACY_MERGE_GROUPS`; `_merge_evidence()` migrates legacy docs | ALREADY IMPLEMENTED LOCALLY |
| 10 | storyboard | "missing" | `lib/editorial/storyboard.py` + `storyboard.schema.json` + `to_scene_plan()` adapter | ALREADY IMPLEMENTED LOCALLY |
| 11 | Timeline IR | "missing / use EDL" | `edit_decisions` v1.0 schema + `assembly.py` builder with surgical revision | ALREADY IMPLEMENTED LOCALLY |
| 12 | render | "needs new renderer" | `video_compose.py` 3-runtime router + profiles; wired in `runners.py` | ALREADY IMPLEMENTED LOCALLY (needs M1 smoke proof) |
| 13 | QA | "no QA" | `lib/producer/qa.py` 6-area fail-closed agent + analysis tools | ALREADY IMPLEMENTED LOCALLY (needs M1 proof) |
| 14 | Producer/orchestration layer | n/a (post-upstream work) | NEW untracked `lib/producer/` (10 files) + 5 schemas + 9 tests — the current working set | MISSING from any upstream analysis by construction |
| 15 | YouTube publish + analytics | "export_bundle covers it" | `export_bundle` is local-only; uploader + analytics are placeholders | MISSING (correctly deferred to M3) |
| 16 | Thumbnail | "covered" | Spec-only (`packaging.py` thumbnail spec, no generator tool) | PARTIALLY TRUE (spec present, generator deferred) |
| 17 | Anything beyond the above | — | — | UNKNOWN (brief not provided) |

Stage-count drift explained: 12 (audit proposal) → 15 (manifest report era; analytics
listed but file had fewer entries) → **19 (canonical; foundation commit `d830d71` + current YAML)**.
Treat any 12/15-stage claim as a historical snapshot, not the current contract.

## 3. Canonical production pipeline

```
TOPIC → RESEARCH → EVIDENCE → SCRIPT → FACT_CHECK → STORYBOARD →
NARRATION → FOOTAGE → FOOTAGE_INTELLIGENCE → EDITORIAL → TIMELINE →
AUDIO → RENDER → QA → PACKAGING → THUMBNAIL → HUMAN_REVIEW →
PUBLISH → ANALYTICS
```

One-to-one with `FACTORY_STAGES` + manifest order. Stage→artifact map
(manifest + `EPISODE_SCHEMA_MAP` + producer contracts):
`brief → research_brief → evidence_bundle → script → factcheck_report →
scene_plan → narration_manifest → asset_manifest → footage_report →
edit_decisions (editorial creates, timeline refines) → audio_mix →
render_report → final_review → package_bundle → thumbnail_set →
review_decision → publish_log → analytics_report`.

## 4. Frozen modules (DO NOT fork, clone, or re-implement)

- F1 `lib/factory_stages.py` — stage IDs, order, gates, transitions. Changes require migration.
- F2 `lib/episode_store.py` + `schemas/factory/episode_package.schema.json` — execution state envelope.
- F3 `lib/checkpoint.py` — legacy compat writer; do not build a third state system.
- F4 `lib/pipeline_guard.py` + `pipeline_defs/youtube-documentary.yaml` — manifest + additive validation.
- F5 `lib/footage_hub/` + `tools/video/footage_hub.py` — sole footage architecture.
- F6 `lib/tts_hub/` + `tools/audio/tts_hub.py` — sole TTS architecture.
- F7 `lib/editorial/` — research/script/factcheck/storyboard/scoring contracts.
- F8 `schemas/artifacts/edit_decisions.schema.json` + `lib/producer/assembly.py` — Timeline IR.
- F9 `tools/video/video_compose.py` + `lib/media_profiles.py` — sole render router.
- F10 `lib/producer/qa.py` + `final_review.schema.json` — QA authority.
- F11 `tools/tool_registry.py` + provider scoring (`lib/scoring.py`, `lib/delivery_promise.py`) — sole tool/provider registry.
- F12 `lib/corpus.py` / `lib/clip_embedder.py` — retrieval substrate (extend, don't replace).

Second state system / pipeline engine / footage stack / render engine / TTS stack /
tool registry are all **rejected patterns**. Gaps are closed by EXTEND/ADD, never by duplication.

## 5. Modules to extend vs add (target-stage disposition)

| Target stage | Disposition | Detail |
|---|---|---|
| topic | REUSE | Manifest + `topic-director.md` + gates exist. |
| research | REUSE | `lib/editorial/research.py` exists. Needs M1 smoke (real sources). |
| evidence | REUSE | `evidence_bundle` schema + merge migration exist. |
| script | REUSE | `script_agent.py` exists. |
| fact_check | REUSE | `factcheck.py` + QA evidence area exist. |
| storyboard | REUSE | `storyboard.py` + schema + adapter exist. |
| narration | REUSE + EXTEND | TTS Hub real; EXTEND: multi-voice/Qwen3/Chatterbox activation deferred past M1; keep Kokoro default. |
| footage | REUSE | FootageHub hardened; M1 proves coverage on real topic. |
| footage_intelligence | REUSE | `runners.run_footage_intelligence` + `visual_scoring.py` exist. |
| editorial | REUSE (wire) | Builder exists; work is wiring/verification, not new architecture. |
| timeline | REUSE | `assembly.py` surgical revision exists. |
| audio | REUSE + EXTEND | `audio_mixer.py` + `audio_build.py` exist; EXTEND: loudness proof on 10-min timeline (M1). |
| render | REUSE | Router + profiles exist; M1 proves 10-min render. |
| qa | REUSE | 6-area agent exists; M1 proves all gates on real artifacts. |
| packaging | EXTEND | `PackageAgent` + new schemas (untracked) need registration/test hardening; no new architecture. |
| thumbnail | ADD (deferred gen) | Spec exists; generator tool deferred — M1 accepts spec + still-frame extraction via FFmpeg. |
| human_review | EXTEND | `review.py` + Backlot gate exist; EXTEND: Backlot surface for 10-min review package. |
| publish | DEFER (M3) | Local `export_bundle` only. M1/M2 stop at READY_FOR_REVIEW / local package. |
| analytics | DEFER (M3) | Placeholder stage; no implementation until publishing exists. |
| Shorts (M2) | ADD (post-M1) | `clip-factory.yaml` exists as reference; 1→5 cutter built only after M1 passes. |

No NEW state, footage, TTS, render, or registry architectures. Ever.

## 6. Five implementation phases (exactly 5; minimum rework, maximum reuse)

### PHASE 1 — Stabilize the working set (freeze the foundation)
- GOAL: Untracked `lib/producer/` + 5 schemas + registry addition become committed, tested, reviewed foundation.
- REUSE: Everything committed (F1–F12).
- ADD: Nothing production (tests + registration only).
- MODIFY: `schemas/artifacts/__init__.py` (already modified — keep); register `package_bundle, preview_report, review_decision, review_package, thumbnail_set` in checkpoint canonical map if required; add `tools/` wrapper decision (defer wrapper, keep lib-only until Phase 2).
- FREEZE: F1–F12 (no interface changes during this phase).
- DEPENDENCIES: None.
- PARALLEL WORK: (a) schema-registration review [Kilo]; (b) producer unit-test hardening [OpenCode]; (c) docs-sync check [Kilo]. No file overlap: (a) `schemas/` only, (b) `tests/` + `lib/producer/` bodies, (c) `docs/` only.
- TESTS: `test_producer*.py, test_assembly, test_audio_build, test_qa_agent, test_packaging, test_preview, test_review_gate, test_stage_model, test_factory_state*` green.
- REAL SMOKE TEST: `pytest tests/test_producer_chain.py tests/test_stage_model.py -q` + `python -c "import lib.producer.producer"`.
- DONE: Full suite shows zero NEW failures vs `ba3887f` baseline (known 6 pre-existing fails unchanged); `git status` clean of accidental edits to F1–F12.
- RISKS: Accidental interface drift in uncommitted files → mitigate by review-before-commit, no renames.

### PHASE 2 — M1 preparation path (wire TOPIC→TIMELINE deterministically)
- GOAL: A real topic runs through research→…→timeline with every artifact validated and provenance intact, no silence, no fabricated evidence.
- REUSE: `lib/editorial/*`, FootageHub, TTS Hub, `assembly.py`, guard, Episode Store.
- ADD: Nothing architectural; only runners wiring + fixtures (already in `runners.py` — verify, don't duplicate).
- MODIFY: `lib/producer/runners.py` bodies only (error mapping, input validation); `EpisodeStore` call sites (no store changes).
- FREEZE: F1–F8, F11–F12.
- DEPENDENCIES: Phase 1.
- PARALLEL WORK: (a) research→fact_check path [OpenCode]; (b) narration→footage_intelligence path [Kilo]; (c) editorial→timeline path [OpenCode]. Shared file `runners.py` → split by function (`run_fact_check` / `run_narration,run_footage*` / `run_editorial,run_timeline`), merge by function boundary.
- TESTS: `test_producer_live_e2e.py`, editorial suites, `test_narration_integration`, `test_footage_hub`, `test_assembly`.
- REAL SMOKE TEST: Pick a public-domain-friendly topic (e.g. Apollo/NASA); run `ProducerAgent.run()` through `timeline` on a 2-minute excerpt; assert: `research_brief` has ≥3 validated sources, `evidence_bundle` grounds every script number/quote, `factcheck_report` has zero blockers, `narration_manifest` audio passes `assert_not_silence`, `asset_manifest` rights all classified, `edit_decisions` validates.
- DONE: Excerpt Timeline IR renders a real 2-min draft; every claim traceable to a source; provenance + rights present on every asset.
- RISKS: Thin-evidence topics stall coverage verdict → use NASA/Wikimedia/Archive.org-rich topic; WRONG/WEAK verdicts are blockers, not warnings.

### PHASE 3 — M1 proof (AUDIO→QA→PACKAGING→HUMAN_REVIEW on a real 10-minute documentary)
- GOAL: **M1: ONE REAL 10-MINUTE DOCUMENTARY** proving research, evidence mapping, real narration, real footage, relevance, provenance, rights, Timeline IR, real audio, FFmpeg/render, technical+audio+editorial QA, human review.
- REUSE: `audio_build.py`, `video_compose.py`, `qa.py`, `packaging.py`, `review.py`, Backlot gate.
- ADD: Thumbnail still-frame extraction via existing FFmpeg path only (no new generator).
- MODIFY: Mix/render parameters (profiles, loudness) — no contract changes.
- FREEZE: F1–F11.
- DEPENDENCIES: Phase 2.
- PARALLEL WORK: (a) audio+render execution [OpenCode]; (b) QA sweep + `final_review` [Kilo, independent: reads artifacts, writes only `qa.py`-adjacent test expectations]; (c) packaging + review-package assembly [OpenCode after (a)]. (a)/(b) overlap on artifacts read-only — safe.
- TESTS: `test_audio_build, test_qa_agent, test_packaging, test_preview, test_review_gate, tests/qa/test_08_end_to_end.py`.
- REAL SMOKE TEST: Full 10-min `edit_decisions` → `video_compose` (youtube_landscape) → FFmpeg MP4 with real Kokoro narration + real footage + music bed; `QAAgent` verdict READY (or BLOCKED with itemized causes); loudness -16±3 LUFS, peak ≤-1 dBTP; `review_package` opens in Backlot.
- DONE CRITERIA (all required): real research (≥3 primary sources) ✓; evidence-mapped script ✓; fact-check zero blockers ✓; real narration, zero silence fallbacks ✓; real footage with relevance verdicts ≥ WEAK, zero WRONG shipped ✓; provenance + rights on every asset ✓; valid Timeline IR ✓; real mixed audio ✓; rendered MP4 via FFmpeg/Remotion ✓; technical + audio + editorial QA reports ✓; human review decision recorded (APPROVED required only for publish — M1 stops at READY_FOR_REVIEW unless explicit approval) ✓.
- RISKS: 10-min Kokoro render time / GPU absence → chunk + cache (`synthesize_cached`); footage coverage gaps → PERMISSIVE mode is allowed for M1 only with rights flags preserved, never fabricated.

### PHASE 4 — M2 Shorts derivation (one long → 5 Shorts)
- GOAL: M1's approved 10-min timeline yields 5 vertical Shorts via the same IR, router, QA.
- REUSE: `assembly.py` (retime/replace), `media_profiles.youtube_shorts`, `silence_cutter/auto_reframe`, QA agent, packaging titles.
- ADD: One `shorts_derivation` routine in `lib/producer/` (pure IR transform: select 5 moments → retime 9:16 → caption burn) + tests. No new engine.
- MODIFY: `packaging.py` title/chapter logic for Shorts metadata.
- FREEZE: F1–F11.
- DEPENDENCIES: M1 (Phase 3) approved Timeline IR + audio mix.
- PARALLEL WORK: (a) derivation transform [OpenCode]; (b) Shorts QA thresholds (vertical, caption legibility) [Kilo]; independent files.
- TESTS: New `test_shorts_derivation.py` (5 outputs, each ≤60 s, validates `edit_decisions`, provenance inherited); existing QA suites.
- REAL SMOKE TEST: 5 rendered vertical MP4s from M1 assets, each with inherited provenance/rights, QA PASS.
- DONE: 5 Shorts + per-short `final_review` + review package.
- RISKS: Auto-reframe cropping faces/text → `face_tracker` + manual spot-check gate.

### PHASE 5 — M3–M5 roadway (publish, analytics, batch, autonomy) WITHOUT new architectures
- GOAL: Private/unlisted YouTube publishing + analytics (M3); durable batch queue (M4); autonomous prep-until-READY_FOR_REVIEW (M5).
- REUSE: `export_bundle.py`, `review.py` gates, Episode Store history, guard publish rule.
- ADD: (M3) one uploader tool under `tools/publishers/` (OAuth, private/unlisted default, explicit-approval enforcement via `assert_publish_allowed`); `analytics_report` schema population from YouTube API reads. (M4) persistent queue table keyed by `episode_id` reusing `EpisodeStore.status()` (no second state). (M5) policy: agents may run TOPIC→QA unattended, may never set APPROVED or publish.
- MODIFY: `publish_log.schema.json` (upload IDs, visibility, approval reference); manifest `publish/analytics` stage tool lists.
- FREEZE: F1–F12 through M3; queue/autonomy extend but never replace Episode Store.
- DEPENDENCIES: M1 + M2.
- PARALLEL WORK: (a) uploader tool [OpenCode]; (b) analytics read [Kilo]; (c) queue design doc [Kilo]; (a)/(b) different files, (c) docs-only.
- TESTS: Publish-gate tests (unapproved publish raises `PublishBlockedError`); analytics mapper tests; queue idempotency tests.
- REAL SMOKE TEST: Unlisted upload of M1 + analytics fetch; batch of 2 episodes queued, one reaches READY_FOR_REVIEW unattended.
- DONE: Public publishing impossible without recorded human APPROVED; analytics artifacts validated; batch reruns are idempotent.
- RISKS: Credential scope creep → least-privilege OAuth, private/unlisted hard default; API quota → backoff + local-first fallback (package without upload).

## 7. Parallel workstreams (general rules)

- OpenCode = primary implementation/orchestration (owns `lib/producer/`, runners, render, packaging).
- Kilo = independent review/debug/parallel engineering (QA sweeps, schema registration, threshold tuning, docs) — never a competing orchestrator; never writes a second pipeline/state/footage/TTS/render path.
- Safe-parallel pattern: split by file/function boundary (`runners.py` per-function; `qa.py` vs `packaging.py`; tests vs lib; docs vs code). Conflict risk is highest in `runners.py` and `contracts.py` — serialize those edits.
- Every stream ends with the phase's REAL SMOKE TEST, not just `pytest`.

## 8. Test strategy

- Baseline: `ba3887f` full suite (known pre-existing fails: 2× `test_seedance_ark_video` ffprobe strings + 4× `test_hyperframes_compose` npm — per implementation reports; re-confirm before Phase 1).
- Phase gates run factory suites first: `test_stage_model, test_factory_state*, test_youtube_documentary_*, test_footage_hub, test_tts_hub, test_narration_integration, test_producer*, test_assembly, test_audio_build, test_qa_agent, test_packaging, test_preview, test_review_gate`.
- No phase is DONE with new failures. Pre-existing fails must be byte-identical causes.
- Contract tests (`tests/contracts/`) guard tool/artifact compatibility on every phase.

## 9. Real production validation strategy (M1 checklist)

Real topic → `research_brief` (sources fetchable) → `evidence_bundle` (every number/quote/causal claim pinned) → `factcheck_report` (zero blockers) → `scene_plan`/`storyboard` → Kokoro narration (PEAK/MEAN floors pass, no silence) → FootageHub assets (rights classified, checksums, `coverage_verdict` ≥ WEAK, provenance) → `edit_decisions` (schema-valid, surgical revisions only) → mixed audio (-16±3 LUFS, -1 dBTP) → rendered MP4 (FFmpeg/Remotion, `render_report`) → `final_review` (6 QA areas, READY) → `package_bundle` + `thumbnail_set` → `review_package` → human decision. M1 stops at READY_FOR_REVIEW; publish requires explicit APPROVED.

## 10. Risks

1. Dual state (checkpoint 9-stage vs Episode 19-stage) confusion → rule: factory reads Episode Store; checkpoints are compat writes only. Revisit unification after M1, not before.
2. `storyboard→scene_plan` provisional mapping + new review/packaging schemas unchecked at checkpoint layer → covered in Phase 1 registration review.
3. Uncommitted `lib/producer/` drift/loss → commit Phase 1 promptly; until then no `checkout/reset/stash`.
4. Footage coverage on hard topics → pick source-rich M1 topic; PERMISSIVE only with flags, never fabrication.
5. Kokoro weight download / torch absence / English-only → documented; Qwen3/Chatterbox stay stubs through M1.
6. 10-min render cost/time → chunk, cache, profile `youtube_landscape` first; Shorts only after.
7. YouTube API credentials/quota (M3+) → uploader is Phase 5 only; hard default private/unlisted; no public publish without APPROVED.

## 11. Risks appendix (production rules restated)

AI decides; deterministic runtime executes; QA proves; human approves. Real footage default.
Never: silence-as-narration, invented evidence, fabricated claims, fake-footage substitution,
lost provenance/rights, QA bypass, or public publish without explicit human approval.
Free/local-first preferred; paid services optional-only, never hard dependencies without approval.

## 12. Exact next task

1. Re-confirm test baseline on `ba3887f`: `python -m pytest tests/test_stage_model.py tests/test_factory_state.py tests/test_producer_chain.py -q` (record pass/fail).
2. Review-then-commit the current working set with NO interface changes: `schemas/artifacts/__init__.py` modification + 10 `lib/producer/` files + 5 artifact schemas + 9 test files (Phase 1 scope).
3. Kilo (parallel, review-only): verify the 5 new schemas validate and `ARTIFACT_NAMES` registration matches `EPISODE_SCHEMA_MAP` + checkpoint canonical map; report gaps, change nothing.
4. Then begin Phase 2 with the Apollo/NASA 2-minute excerpt smoke test.
