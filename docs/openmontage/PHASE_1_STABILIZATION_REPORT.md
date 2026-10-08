# Phase 1 Stabilization Report — YouTube Factory

> Branch: `documentary-factory` | Commit: `cac1fc8` (Phase 1 checkpoint)
> Parent: `ba3887f` | Date: 2026-10-06
> Scope: stabilization + checkpointing only. No new Factory features.

## 1. Git safety

Pre-commit state (verified, no reset/stash/checkout):
- Modified: `schemas/artifacts/__init__.py` (+5 registrations), `tests/test_youtube_documentary_integration.py` (fixture alignment, see §4)
- Added: `lib/producer/` (10 files), 5 artifact schemas, 9 producer test files,
  `PRODUCER_AND_REVIEW_IMPLEMENTATION.md`, `docs/openmontage/YOUTUBE_FACTORY_MASTER_PLAN.md`
- `git diff --check`: clean. Post-commit `git status --short`: clean (no exceptions).

Commit: `cac1fc8` — `feat(factory): stabilize canonical pipeline and factory foundations`

## 2. Test baseline (exact commands + results)

| Command | Result |
|---|---|
| `pytest tests/test_stage_model.py tests/test_factory_state.py tests/test_factory_state_integration.py` | 38 passed |
| `pytest tests/test_youtube_documentary_integration.py tests/test_youtube_documentary_pipeline.py tests/test_stage_model.py tests/test_factory_state.py tests/test_factory_state_integration.py` | 53 passed |
| `pytest tests/test_footage_hub.py tests/test_tts_hub.py tests/test_narration_integration.py tests/test_youtube_documentary_pipeline.py tests/test_youtube_documentary_integration.py tests/test_producer.py tests/test_producer_chain.py` | 73 passed, 2 skipped |
| `pytest tests/test_producer.py tests/test_producer_chain.py tests/test_assembly.py tests/test_audio_build.py tests/test_packaging.py tests/test_preview.py tests/test_qa_agent.py tests/test_review_gate.py` | 72 passed |
| `pytest tests/contracts/test_phase0_contracts.py test_phase1_contracts.py test_pipeline_catalog.py test_assembly.py test_audio_build.py test_packaging.py test_preview.py test_qa_agent.py test_review_gate.py` | 204 passed |

- New failures found during Phase 1: 2 (`test_ordered_run_and_resume`, `test_publish_blocked_then_allowed`) — caused by the Phase 1 working set itself (newly registered `package_bundle`/`review_decision` schemas vs stale minimal fixtures). Fixed by fixture alignment (§4); now green.
- Pre-existing failures: 6 known from implementation reports (2× `test_seedance_ark_video` ffprobe strings, 4× `test_hyperframes_compose` npm) — untouched, out of scope.
- Environment notes: no system `ffmpeg`/`ffprobe` (shimmed via `imageio-ffmpeg` + `static-ffmpeg` for smoke); 2 skips are network-gated; misaki G2P gaps on `Neil/Armstrong/moonwalker/grey` (see §6).

## 3. Contract review (verified, no broad refactoring)

- 19-stage consistency: `FACTORY_STAGES == manifest stages` (True); `PRODUCER_STAGES == manifest − {publish, analytics}` (True, 17 stages).
- Artifact registration: 28 names in `schemas/artifacts/__init__.py`; every `EPISODE_SCHEMA_MAP` value registered; zero unregistered mappings.
- No duplicate schemas; no second state/engine/footage/TTS/render/registry.
- Producer isolation: imports only from `lib.editorial`, `lib.footage_hub`, `lib.tts_hub`, `lib.checkpoint`, `lib.episode_store`, `lib.pipeline_guard`, `lib.pipeline_loader`, `tools.audio.*`, `tools.video.video_compose` (mostly lazy). No duplicate orchestration. `storyboard→scene_plan` provisional mapping untouched.
- `review_decision` schema note: `additionalProperties: false`, requires `decision/approver/rationale/timestamp/episode_id`, no `version` field (unlike all sibling artifacts). Matches `ReviewDecision.to_dict()` exactly. Flagged as convention drift to normalize post-M1 (no change made in Phase 1).
- mypy: `lib/producer/` itself zero errors; 18 errors all in pre-existing dependencies (`video_compose.py`, etc.). `lib/episode_store.py`, `lib/factory_stages.py`, `lib/pipeline_guard.py`, `schemas/artifacts/__init__.py`: only pre-existing `styles/playbook_loader.py` errors via import-following.

## 4. Focused fix (smallest for contract correctness)

`tests/test_youtube_documentary_integration.py` CHAIN fixtures predated the newly registered schemas:
`package_bundle: {"path": ...}` → minimal-valid bundle (version 1.0, 5 title candidates, thumbnail subfields, mirroring the passing `test_producer.py` fixture);
`review_decision: {"verdict": "APPROVED"}` → `{decision, approver, rationale, timestamp, episode_id}` (×2 sites).
No test logic, thresholds, or assertions changed. No production code changed for this.

## 5. Real media smoke test

{{SMOKE}}

## 6. Environment issues discovered (not Factory bugs)

1. **misaki G2P `None`-phoneme crash** on `Neil`, `Armstrong`, `moonwalker`, `grey` (kokoro `KPipeline`, this env's misaki version). Raises through `KokoroAdapter.synthesize` → `ProviderFailureError` (fail-closed, correct behavior). Workaround: rephrase (used `the mission commander`, `gray`). Upstream risk already noted in `TTS_HUB_IMPLEMENTATION.md` (misaki OOV). Recommendation: add a pre-synthesis G2P canary that fails fast with the offending token named (M2).
2. **Provider flakiness**: NARA (bad JSON), Pond5/LoC/NOAA/Dareful (HTTP 403) search failures during smoke; FootageHub continued via wikimedia/archive_org. Strict-rights coverage is query-sensitive: near-duplicate Saturn V queries returned weak vs nothing.
3. No system ffmpeg/ffprobe — smoke shimmed via `imageio-ffmpeg` + `static-ffmpeg`.

## 7. Remaining risks

- Dual state (checkpoint 9-stage vs Episode 19-stage) still coexists; factory reads Episode Store, checkpoints are compat writes. Unification deferred to post-M1.
- `review_decision` missing `version` convention (§3 note).
- Kokoro English-only, weight download on first run, misaki OOV (§6.1).
- Strict-rights footage coverage varies by topic/query; storyboard must avoid near-duplicate requirements (this smoke proved the gap detector works — it halted rather than fabricate).
- YouTube uploader + analytics intentionally absent (M3).

## 8. Next phase (Phase 2 — M1 preparation path)

Wire TOPIC→TIMELINE deterministically per `YOUTUBE_FACTORY_MASTER_PLAN.md` Phase 2:
runners wiring verification only (no new architecture), Apollo/NASA excerpt as the reference topic,
then full 10-minute M1 proof (Phase 3). First command: re-run §2 baseline on `cac1fc8`.
