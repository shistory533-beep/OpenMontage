---
description: Verify recent changes with focused tests, broader suites, and config checks
agent: build
---
Verify this work: $ARGUMENTS. Load the implementation-verify skill and
follow it (focused tests first, then broader suites/typecheck/lint, never
weaken tests). If real providers, FFmpeg, TTS, or HTTP endpoints are
involved, run one safe smoke via the production-smoke skill.
