# Plan — Automated Production Factory (T3 / high-risk, multi-file)

Objective: Turn validated pipeline into reliable end-to-end AUTOMATIC FACTORY with one-command execution, config-driven orchestration, provider selection, failure classification, resume, QA gate, artifact registry, idempotency, approvals, observability, CLI, documentation, and proof run.

Constraints / reuse:
- Reuse lib/factory_stages.py (canonical stage machine), factory/pipeline_runner.py loop, factory/job_state.py resume/failure separation, factory/provider_abstraction.py selection, backlot/state.py observation, lib/checkpoint.py persistence, pipeline_defs/youtube-documentary.yaml stages.
- Do NOT rewrite working stage logic; wire existing handlers/producers.
- Free/local-first providers; never fabricate keys; never silently use paid.
- Must prove with real run, not scaffolding.

Affected files (expected):
- factory/ (pipeline_runner, job_state, provider_abstraction, provenance) — extend/reuse
- lib/producer/producer.py — reuse StageHandler / EpisodeStore
- backlot/state.py — reuse observation
- config.yaml — standardize factory config
- CLI entrypoint (new module or Makefile) — openmontage run / resume / status / qa
- tests/factory/test_factory_integration.py — new proof test
- docs/openmontage/plans/ (this file), docs/openmontage/factory.md, docs/openmontage/config.md

Steps (ordered):
1. Standardize factory config (config.yaml + factory_config.yaml) with pipeline type, topic, duration, resolution, providers, QA/retry/approval.
2. Build JobState / resume wrapper using factory/job_state.py; classify failures.
3. Wire Producer / factory runner to real stage execution (reuse existing capabilities: tts_selector, footage_hub, video_compose, export_bundle, etc. where already present; for missing real services, log status and skip with diagnostics rather than inventing).
4. Implement provider selection via ProviderAbstraction; record in provenance.
5. Implement automatic QA gate using existing ffprobe + subtitle + audio checks (reuse test_production_content_milestone.py logic).
6. Implement CLI commands (run, resume, status, qa) with concise output.
7. Add focused integration test (topic -> final MP4 -> QA PASS) using free/local; include resume, retry, idempotency, fallback, QA-block cases.
8. Run end-to-end factory; fix failures; run again; record evidence.
9. Update docs; commit.

Verification: real end-to-end run + test execution + ffprobe proof + provenance + backlot status.

Risks: some stage services may not have real local implementations (e.g., full LLM brief writer); factory must grade gracefully (record status, provide diagnostics) rather than invent outputs.
