# Factory Production Build Plan — compressed
Objective: Harden pipeline wrapper (topic→publish) with persistent state, resume, idempotency, failure semantics, provider abstraction, provenance, zero-key tests, one real smoke video.
Constraints: Reuse lib/checkpoint.py, lib/factory_stages.py, pipeline_defs/youtube-documentary.yaml. No rewrite of frozen core. No hardcoded keys. OmniRoute optional upstream, never router of record.
Files new: factory/job_state.py, factory/pipeline_runner.py, factory/provider_abstraction.py, factory/provenance.py, tests/factory/test_no_key_recovery.py, tests/factory/test_smoke_e2e.py
Reuse: checkpoint (resume/gates/history), factory_stages (19 canonical stages, prerequisites, approval gates), pipeline_loader, youtube-documentary manifest, existing TTS/display tools, FFmpeg, local pipers.
Steps: 1) job_state + checkpoint wrapper. 2) provider abstraction (free-first, optional paid, no hard keys). 3) provenance/telemetry logger. 4) pipeline runner with transient/permanent failure separation + resume. 5) focused tests + no-key/recovery/fallback. 6) real small smoke (local TTS + FFmpeg compose / remotion if installed). 7) commit.
Verification: pytest tests; smoke render exists; git commit coherent.
Risks: remotion/HyperFrames may require node; use FFmpeg fallback. No paid provider guaranteed. Real smoke may be short clip only.
