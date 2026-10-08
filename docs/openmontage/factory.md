# Automated Production Factory

One command:

    openmontage_factory_cli.py run --topic "..."

Or via Makefile:

    make factory-run
    make factory-qa

Configuration in `factory_config.yaml`: pipeline type, topic, duration, resolution, providers (free/local-first), retry/failure classes, QA policy, approval mode (`automatic` or manual gates preserved), output directory.

Stage order (canonical from `lib/factory_stages.py`): topic → research → evidence → script → fact_check → storyboard → narration → footage → footage_intelligence → editorial → timeline → audio → render → qa → packaging → thumbnail → human_review → publish → analytics.

Resume:

    python3 openmontage_factory_cli.py resume <job_id>

Status / QA:

    python3 openmontage_factory_cli.py status [job_id]
    python3 openmontage_factory_cli.py qa [job_id]

Provider selection: free/local first (`piper_tts`, `archive_org`, `direct_clip_search`, `ffmpeg`); paid only if env key present (`ELEVENLABS_API_KEY`, `GOOGLE_API_KEY`, etc.). No fabricated keys; `NO_ELIGIBLE_PROVIDER` stops with diagnostics.

Failure classification (from config): TRANSIENT (retry up to 2), AUTH_REQUIRED, NO_ELIGIBLE_PROVIDER, PERMANENT, VALIDATION_FAILED. Retry never loops deterministic failures.

Idempotency: rerunning same job uses existing artifacts if inputs/config unchanged; provenance records each run.

QA gate (automatic before publish): duration alignment, H.264/AAC valid, resolution/fps, subtitle endpoint, narration non-empty, no clipping (mean/max from volumedetect), provenance complete, no paid usage when zero-paid mode on. Final MP4 never marked success if QA fails.

Observability: Backlot (`backlot/status`) reads `checkpoint_*.json` and `provenance.json`; factory CLI exposes current stage, completed stages, retries, provider/model, elapsed, final artifact, status.
