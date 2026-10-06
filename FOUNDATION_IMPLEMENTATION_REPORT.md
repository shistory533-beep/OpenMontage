# Foundation Implementation Report (documentary-factory)

Branch: `documentary-factory` (from `main` @ 9327439). Tree clean.
No redesign of OpenMontage core; all changes are additive to the factory layer,
except two one-line-scale alignments in existing contract tests (tts_hub
registration, topic-stage runtime contract).

## 1. Completed work

### Part 1 — Repository protected
- Created branch `documentary-factory`; checkpointed all prior uncommitted
  Factory work as `af4d923` (Episode Store, stage model, FootageHub, TTS Hub,
  youtube-documentary manifest + guard, tests, fixtures). Nothing discarded.

### Part 2 — Unified stage model (commit d830d71)
- `lib/factory_stages.py` is now the single source of truth: 19 canonical
  stages in order — topic, research, evidence, script, fact_check,
  storyboard, narration, footage, footage_intelligence, editorial, timeline,
  audio, render, qa, packaging, thumbnail, human_review, publish, analytics.
- Legacy mapping (no blind renames): sources/facts/claims merged into
  evidence (artifacts preserved under sub-keys, conservative least-advanced
  state, failure preserved); metadata renamed to packaging; all other IDs
  unchanged. `migrate_legacy_doc()` in `lib/episode_store.py` is pure,
  fail-closed on unknown IDs, backfills `approved_at` for pre-gate DONE
  stages, and its output validates against the canonical envelope.
- Explicit `STAGE_PREREQUISITES` chain + `assert_prerequisites_met`;
  `APPROVAL_GATES` = {topic, script, storyboard, footage, human_review,
  publish} enforced in `EpisodeStore.transition` (DONE without prior
  APPROVED raises `ApprovalGateError`; rework clears the approval stamp).
- Manifest validated against the canonical model
  (`validate_manifest_against_canonical`); youtube-documentary.yaml grew the
  4 missing stages (evidence, footage_intelligence, thumbnail, analytics)
  and script now consumes `evidence_bundle`. Publish still requires
  human_review APPROVED (guard); analytics requires publish (chain).

### Part 3 — TTS Hub hardened (commit dd9761c)
- Kokoro is the default English documentary provider (registry order, tool
  default, deterministic `af_heart`-family voice selection).
- Contract now exposes provider, model (`kokoro-82m-v1.0`), voice,
  language, sample rate, channels, duration, alignment, output path,
  checksum, input_hash, generation metadata, and error state
  (`SpeechResult.failed()`); old sidecars still load via defaults.
- Deterministic content-hash cache; cache hits re-validated and checked
  against declared provider format; corrupt entries self-heal by
  re-synthesis; fresh renders verified (decoded rate/channels/duration must
  match claims) — corruption detection on both paths.
- Retry policy in tool wrapper (max_retries=2, fail-fast typed errors);
  provider registry with capability/model advertisement; voice selection;
  new `dry_run` op (plans without writing). Silence is never a fallback
  (rejected with `SilenceRejectedError`; stubs raise instead of synthesizing).

### Part 4 — Real narration wired into production (commit de5acb3)
- Production chain traced through existing architecture only: script
  sections → TTS Hub → `mapper.to_manifest_asset` → `section_timeline` →
  `AudioMixer.full_mix` → `VideoCompose.compose(audio_path=…)` → MP4.
- New `tests/test_narration_integration.py`: offline assertions fail if
  narration becomes silence; ffmpeg layer proves mix + final MP4 carry
  non-silent narration; source scan forbids synthetic narration fallbacks
  in TTS paths (`anullsrc` remains only for audio-less clip padding).
- No hidden narration fallbacks found (`tts_selector` fails closed).

### Part 5 — FootageHub hardened (commit 0d5744f)
- Contract normalized: provider, source_id, title, description,
  source_url, download_url, media_type (`kind` alias), duration, width,
  height, fps, creator, license, rights_status, attribution,
  retrieved_at, checksum + derived orientation.
- Rights modes strict (default) / permissive / audit-only; restricted is
  never allowed except flagged audit-only.
- New `lib/footage_hub/verify.py`: ffprobe → ffmpeg-parse → stdlib sniff;
  `MediaCorruptError` only on positive proof (never false-positives on
  unknown bytes); probe recorded in manifest sidecars; zero-dims enriched.
- Search enforces kind + resolution/duration/orientation (forwarded and
  post-filtered); providers fail independently; SHA-256 dedupe unchanged;
  transient download retry with backoff; Content-Length partial-download
  checks in openverse/dvids adapters; `coverage_verdict` PASS/WEAK/WRONG/
  MISSING. No AI-generated filler (source scan extended). Reuses existing
  stock_sources / ClipCache / corpus infrastructure; all 8 factory
  providers live (archive_org, wikimedia, nasa, openverse, loc, dvids,
  pexels, pixabay_video).

## 2. Changed files
- `lib/factory_stages.py`, `lib/episode_store.py`,
  `schemas/factory/episode_package.schema.json`,
  `pipeline_defs/youtube-documentary.yaml`
- `lib/tts_hub/{contracts,audio,cache,kokoro_provider,registry,stubs}.py`,
  `tools/audio/tts_hub.py`
- `lib/footage_hub/{contracts,hub,rights}.py`, new
  `lib/footage_hub/verify.py`, `tools/video/footage_hub.py`,
  `tools/video/stock_sources/{openverse,dvids}.py`
- Tests: new `tests/test_stage_model.py`,
  `tests/test_narration_integration.py`; extended `test_factory_state*.py`,
  `test_youtube_documentary_*.py`, `test_tts_hub.py`, `test_footage_hub.py`;
  contract-test alignment (`test_phase3_contracts.py`,
  `test_runtime_presentation_contract.py`), `.env.example` keys.
- Prior checkpoint files (unchanged this task): `lib/pipeline_guard.py`,
  factory `*.md` reports, fixtures, topic-director skill.

## 3. Tests
- Factory/stage/TTS/FootageHub/narration suites: **96 passed, 2 skipped**
  (skips are the ffmpeg-gated render tests when ffmpeg is absent — repo
  `skipif` convention).
- `tests/contracts/`: 1232 passed; 2 failures in
  `test_seedance_ark_video.py` reproduce on pristine `main` (pre-existing,
  unrelated, not fixed per scope).
- Touched-area tool tests (corpus failure, pixabay clamp, documentary
  governance, stock adapters): 57 passed, 3 xfailed.
- `mypy` on changed lib files: only pre-existing missing-stub import
  errors (same on untouched files); one new `type-var` fixed.

## 4. Real smoke results (this machine, CPU-only)
- **Kokoro generation**: `af_heart`, 104 chars → 6.425 s WAV, 24 kHz mono,
  peak 0.378 / mean_abs 0.0288, checksum + input_hash + alignment recorded.
  Independently re-probed (stdlib `wave`): identical figures, silence check
  passed, result verification passed. Loudness −25.8 LUFS raw (normalized
  at mix stage, as designed).
- **Footage**: real search+download via hub — Wikimedia Commons aerial of
  Crooked River Canyon, 36.069 s, 1920×1080, verified public domain,
  SHA-256 vaulted (81 MB).
- **36 s production render** (`/tmp/opencode/factory_smoke/render36.py`):
  4 Kokoro sections (25.08 s) → full_mix loudnorm −14 LUFS target
  (measured −14.59, true peak −1.50 dBTP) → muxed MP4 36.04 s,
  h264 1080p30 + AAC. Extracted audio: 36.04 s, peak 0.88 — spans the
  timeline, definitively not silence.

## 5. Remaining risks
- No system ffmpeg/ffprobe on PATH here (static ffmpeg 7.0.2 via
  `imageio-ffmpeg` + `ffmpeg -i` parsing used instead); production hosts
  need real ffmpeg+ffprobe for full verification strength (sniff-only
  fallback cannot prove video corruption).
- Chatterbox-Turbo and Qwen3-TTS remain capability stubs (contract-only);
  non-English documentary narration has no verified provider yet.
- `footage_intelligence`, `packaging` (bundle writer), `thumbnail`
  (aside from concept stage), `analytics`, and the Producer/Research
  agents are stage shells + gates only — explicitly out of scope.
- Pre-existing failures untouched: 2 seedance contract tests; any other
  environment gaps (GPU, API keys) behave as before.
- Narration (25 s) shorter than footage (36 s) in the smoke render — mix
  pads to target; a real episode balances script duration to footage.
