# PRODUCER_AND_REVIEW_IMPLEMENTATION — Production Orchestrator + Quality System

> Scope: Parts 1–7 of the YouTube Factory task (Producer orchestrator, editorial
> assembly, audio production, preview render, final QA, human review gate,
> packaging) + Part 8 verification. Publishing and analytics stay out of scope.
> No public YouTube upload was implemented.

## 1. What was added

| File | Purpose |
|---|---|
| `lib/producer/producer.py` | `ProducerAgent`: Episode-Store-backed orchestrator over `PRODUCER_STAGES` (topic→human_review, 17 stages = manifest minus publish/analytics). `plan()` dry-run, `run()`, `retry_failed()`, `record_approval()`, `inspect()`, `start_from`/`stop_after` scoping, JSONL structured events. Any stage failure → FAILED + failed checkpoint + `ProducerHalted`; never continues past failure. |
| `lib/producer/runners.py` | Default stage handlers. Content stages record caller-supplied payloads only (Producer never authors). Mechanical stages run real services: narration→TTS Hub, footage→FootageHub+VisualScorer+download, footage_intelligence→verdicts, editorial/timeline→assembly, audio→audio_mixer via plan, render→video_compose (runtime-swap refused), qa→QAAgent, packaging→PackageAgent, human_review→explicit decision only. |
| `lib/producer/contracts.py` | Plain-data contracts: `PRODUCER_STAGES`, `ProducerEvent`, `StagePlan`, `FootageMoment`, `ShotDecision`, QA (`CheckResult`/`QAReport`, verdicts PASS/WARN/FAIL, readiness READY/BLOCKED), review (`ReviewDecision`, 4 states), titles (`TitleCandidate`, 5 axes). Plus `manifest_assets()` / `script_claims()` adapters that read provenance and claim linkage from their canonical sidecars without forking schemas. |
| `lib/producer/assembly.py` | Editorial assembly on the existing Timeline IR only (`edit_decisions`, schema-validated): `select_moments` (pass/weak only, gaps raise), `assemble_timeline` (deterministic + `assembly_input_hash`), `retime_timeline` (refine, never replace), `replace_scene` / `revise_scene` (surgical; unrelated cuts byte-identical). Every moment stores requirement id, asset id, exact in/out, function, score, provenance, repetition count. |
| `lib/producer/audio_build.py` | `verify_narration` (1 verified stem per script section; silence padded never; synthetic/fixture provenance rejected), `build_mix_plan` (speech laid end-to-end, music ducked when present), `verify_mix` (duration, loudness vs −16 LUFS ±3, true-peak ceiling −1 dBTP), `measure_loudness` (ffmpeg-measured, else labeled estimate). |
| `lib/producer/preview.py` | `build_preview_timeline` (scene subset / max-scenes / max-seconds, re-laid gap-free draft), `build_captions` (SRT from narration timings), `render_preview` (file must exist, probe, non-silent audio → `ready_for_review`). Never labeled production-ready; only QA PASS on the final render earns that. |
| `lib/producer/qa.py` | Independent `QAAgent`, 6 areas: technical (probe ffprobe→ffmpeg-parse→wav-decode; duration/resolution/fps/codec/audio/samplerate/channels), audio (real non-silent stems, coverage ≥80%, loudness, true peak, clipping, silence), editorial (alignment, relevance binding, missing scenes, anomalies, continuity), evidence (claim→verdict mapping, blockers, contradictions, hash continuity), rights (license+attribution, unknown fails strict, restricted always fails), integrity (files exist, no fixture/synthetic/stale/broken-refs/missing artifacts). Blocking fail → FAIL/BLOCKED, else WARN/READY or PASS/READY. `to_final_review()` maps onto canonical `final_review` schema. |
| `lib/producer/review.py` | `assemble_review_package` (video, script, storyboard, footage, QA, rights, narration, titles, thumbnail, description, chapters, subtitles; incomplete → refused), `record_decision` (append-only JSONL, APPROVED needs identity+rationale and prior READY_FOR_REVIEW), `assert_publish_allowed` (raises without APPROVED). |
| `lib/producer/packaging.py` | `PackageAgent`: exactly 5 accepted titles scored on clarity/curiosity/specificity/relevance/originality minus misleading-risk (clickbait rejected, reported, never shipped), description from supplied inputs only, chapters from script blocks, tags/hashtags, subtitle metadata, thumbnail spec (focal subject, composition, grounded text, contrast, concept, fit-reason). |
| `schemas/artifacts/{package_bundle,preview_report,review_package,review_decision,thumbnail_set}.schema.json` + 5 names registered in `schemas/artifacts/__init__.py` | New artifact names validated at checkpoint (closes the previous fail-open gap for producer stages). |
| `pipeline_defs/youtube-documentary.yaml` | Extended to the full 19-stage factory order (evidence, footage_intelligence, thumbnail, analytics added) so `PRODUCER_STAGES == manifest − {publish, analytics}` (pinned by test). |
| Tests (9 files, ~110 tests) | `test_producer` (plan/run/resume/retry/gates/halt/inspect), `test_assembly`, `test_audio_build`, `test_preview`, `test_qa_agent` (incl. adversarial fixtures), `test_review_gate`, `test_packaging`, `test_producer_chain` (offline assembly→preview→QA→review→pack over locally rendered media, permissive declared), `test_producer_live_e2e` (`live_api`: real Kokoro + real strict-rights footage + real render + QA → APPROVED; publish asserted blocked-then-allowed, never executed). |

## 2. Requirement mapping

- **Coordination only**: Producer holds no domain logic — state→EpisodeStore, order/gates→manifest+guard+checkpoints, content→editorial agents/TTS Hub/FootageHub/assembly/mixer/video_compose/QA/review/packaging. Stage inputs/outputs explicit via manifest `required_artifacts_in`/`produces` and `StagePlan`.
- **Checkpoints/resume/retry/skip**: in-progress/completed/failed/awaiting_human checkpoints per stage; DONE stages skipped; FAILED stages re-run via `retry_failed`; artifacts versioned in the store with append-only history.
- **Strict-mode bans enforced in code, not convention**: no placeholder narration (empty/missing/silent stems fail), no fake footage (gaps raise, never synthesized; footage tool menu closed to retrieval), unknown rights fail strict, synthetic/test audio rejected by provenance + path + silence checks, stale assets caught by checksum, publish impossible without APPROVED (guard + review gate, defense in depth).
- **No second timeline format**: assembly constructs/validates/re-times/surgically revises `edit_decisions`; bookkeeping lives in open `metadata`, cuts stay schema-pure.
- **Preview ≠ production-ready**: `ready_for_review` is a draft-file property; `READY` readiness comes only from QA on the final render.

## 3. Verification (Part 8)

- `mypy lib/producer/ --ignore-missing-imports`: **clean** (remaining repo errors are pre-existing in `video_compose.py` / `hyperframes_compose.py`, untouched).
- Offline: **96 passed** (`test_producer`, `test_assembly`, `test_audio_build`, `test_preview`, `test_packaging`, `test_qa_agent`, `test_review_gate`, `test_producer_chain`, `test_factory_state`, `test_youtube_documentary_pipeline`), covering failure/recovery (transient-failure→retry, critical-halt with no downstream run, prerequisite fail-closed, gated approval wait/resume, inspect).
- Live E2E (`OPENMONTAGE_ALLOW_NETWORK=1 pytest tests/test_producer_live_e2e.py`):
  **1 passed in 121.7s** — full topic→human_review run with real Kokoro narration
  (2 sections), real strict-rights footage (Wikimedia/Mixkit, verified),
  real assembly, real audio mix, real FFmpeg render, QA verdict PASS/READY,
  review to APPROVED; publish asserted blocked-then-allowed, never executed.
  First attempt failed at `render` (container had no `ffprobe`, so
  video_compose's self-review failed closed — the run correctly halted rather
  than shipping an unvalidated render). Fixed by: (a) `static-ffmpeg` toolchain
  for `ffprobe` + test shim guaranteeing ffmpeg/ffprobe on PATH; (b) render now
  supplies `narration_transcript_path` built from persisted TTS alignment so the
  transcript-vs-script check executes instead of skipping.

## 4. Known risks

1. Single-writer assumption inherited from Episode Store (no file locking).
2. No system ffprobe in base containers — live E2E resolves it via the
   `static-ffmpeg` package (test shim); CI with the real toolchain should
   confirm ffprobe-path results.
3. Music has no configured source in this environment (mix proceeds speech-only with ducking disabled); wire `music_library/` or a provider before hero productions.
