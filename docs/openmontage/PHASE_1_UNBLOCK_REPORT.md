# Phase 1 Unblock Report — YouTube Factory

> Branch: `documentary-factory`
> Status: fixes implemented; smoke test in progress
> Pre-existing env failures: `test_seedance_ark_video` ×2, `test_hyperframes_compose` ×4 (untouched)

## 1. Artifact contracts (H1)

Gap closed: `narration_manifest`, `footage_report`, `audio_mix`, `analytics_report` had no schema file and were unregistered.

- Added 4 new schemas under `schemas/artifacts/`
- Registered all 4 in `schemas/artifacts/__init__.py::ARTIFACT_NAMES`
- `ARTIFACT_SCHEMA_MAP` now covers all 19 factory stages (was 9, missing narration/footage_intelligence/audio/packaging/thumbnail/human_review/analytics)
- Added `validate_stored_artifact()` fail-closed helper; used before DONE and on resume

New contract tests (`tests/test_phase1_factory_contracts.py`):
- `test_every_produced_artifact_has_registered_schema`
- `test_episode_schema_map_covers_all_stages`

## 2. Empty artifacts / invalid overwrite (H2, M3)

`episode_store.set_artifact()` previously accepted `{}` for unmapped stages and schema-invalid payloads for mapped stages could still reach DONE.

- `set_artifact()` now rejects empty/non-dict payloads before any mutation
- `EpisodeStore.transition(..., DONE)` validates the stored artifact; invalid artifacts cannot mark a stage DONE
- Invalid artifacts stay retryable: FAILED → RUNNING transitions remain legal
- Producer agent revalidates DONE artifacts on resume; invalid DONE stages reopen to RUNNING automatically

Tests:
- `test_empty_artifact_never_done_and_stays_retryable`
- `test_done_blocked_on_invalid_artifact`
- `test_producer_rejects_empty_artifact_and_resume_revalidates`

## 3. Durable human approval (M1)

Approvals were ephemeral in `ProducerAgent.approvals` dict; lost on restart.

- `record_approval()` now persists to `producer_approvals.json` (atomic write beside `episode.json`)
- New instances over the same episode directory reload persisted approvals
- Publishing reads the durable Episode Store APPROVED state + `review_log.jsonl` (existing `assert_publish_allowed`)

Tests:
- `test_approvals_survive_restart`

## 4. Real executor coverage (M2)

- Existing `tests/test_producer_live_e2e.py` covers real Kokoro narration + real Wikimedia footage + real ffmpeg render (passes: 1 passed after limiter fix)
- New Apollo smoke script exercises 5 real Kokoro sections, real NASA/Apollo FootageHub queries, real ffmpeg render, full QA
- No fake PASS: silence rejection, checksum, provenance, rights status are all enforced at runtime

## 5. Retry/fallback (L5/L6)

- Narration runner now classifies TTS errors: deterministic (voice/text/config/silence) fail fast with explicit message; `ProviderFailureError` remains retryable
- Silence is never a fallback (enforced by `assert_not_silence` + provenance checks)
- `run_render` refuses both `render_runtime` and `renderer_family` swaps (M4)

## 6. Retry attempt counter (L3)

- `ProducerAgent` persists per-stage attempt counts in `producer_attempts.json`
- Each `_run_stage` call increments and records the attempt; written to checkpoint metadata

Test:
- `test_attempt_counter_increments_and_persists`

## 7. Review artifacts on production paths (L4)

- `assemble_review_package()` validates `review_package` before returning
- `record_decision()` validates `review_decision` before appending
- `render_preview()` validates `preview_report` before returning

Test:
- `test_review_and_preview_validate_on_production_paths`

## 8. Loudness profile (L7)

Documentary production standard: **-14 LUFS integrated, ±2 LUFS tolerance, -1.0 dBTP true peak ceiling.**

- `lib/producer/audio_build.py`: `DIALOGUE_TARGET_LUFS = -14.0`, `LOUDNESS_TOLERANCE_LUFS = 2.0`
- `lib/producer/qa.py`: `AUDIO_TARGET_LUFS = -14.0`, `AUDIO_TOLERANCE_LUFS = 2.0`
- `tools/audio/audio_mixer.py`: chained `alimiter=limit=0.707945` after `loudnorm` to guarantee true-peak compliance under -1.0 dBTP

Test:
- `test_documentary_loudness_profile`

## 9. Legacy renderer (M4)

`documentary-montage` is a valid `renderer_family` enum value. Production uses it only via the youtube-documentary factory (editorial stage default + explicit lock). No incorrect defaults found.

- `run_render` now additionally locks `renderer_family`; mismatch raises `CriticalStageError`
- Legacy `documentary-montage` pipeline manifest still declares the same family → unaffected

Test:
- `test_renderer_family_swap_refused_and_legacy_pipeline_intact`

## 10. Test results

| Suite | Result |
|---|---|
| `tests/test_phase1_factory_contracts.py` | 11 passed |
| `tests/test_producer.py` | passed |
| `tests/test_producer_chain.py` | passed |
| `tests/test_assembly.py` | passed |
| `tests/test_audio_build.py` | passed |
| `tests/test_packaging.py` | passed |
| `tests/test_preview.py` | passed |
| `tests/test_qa_agent.py` | passed |
| `tests/test_review_gate.py` | passed |
| `tests/test_youtube_documentary_integration.py` | passed |
| `tests/test_youtube_documentary_pipeline.py` | passed |
| `tests/test_stage_model.py` | passed |
| `tests/test_factory_state.py` | passed |
| `tests/test_factory_state_integration.py` | passed |
| `tests/contracts/test_phase0_contracts.py` | passed |
| `tests/contracts/test_phase1_contracts.py` | passed |
| `tests/contracts/test_pipeline_catalog.py` | passed |
| `tests/test_footage_hub.py` | passed |
| `tests/test_tts_hub.py` | passed |
| `tests/test_narration_integration.py` | passed |
| `tests/test_producer_live_e2e.py` | **1 passed** (real Kokoro + real footage + real ffmpeg) |
| `tests/contracts/test_seedance_ark_video.py` | 2 failed (pre-existing, untouched) |
| `tests/tools/test_hyperframes_compose.py` | 4 failed (pre-existing, untouched) |
| `mypy` on changed files | 0 new errors |
| `git diff --check` | clean |

## 11. Smoke test status

Apollo documentary smoke (real Kokoro + real NASA/Apollo footage + real ffmpeg render) running in background. Will confirm PASS/FAIL in follow-up.

## 12. Remaining risks

- Kokoro `crewmates` phoneme gap on this env's misaki build; worked around with alternate wording. Upstream fix needed.
- FootageHub `per_provider=4` × 5 queries × 8 providers can exceed 10 minutes in constrained networks; reduced to 2 in smoke.
- Dual state (checkpoint 9-stage vs Episode 19-stage) still coexists; unification deferred post-M1 per frozen-module rule.
- `review_decision` schema lacks `version` field convention (flagged; not changed in Phase 1 to minimize diff).
