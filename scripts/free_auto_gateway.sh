#!/usr/bin/env bash
# Start the FREE-AUTO local gateway on the endpoint opencode.json dials.
# Canonical endpoint: http://127.0.0.1:4100/v1 (virtual model: free-auto).
# The gateway needs upstream credentials in the environment to return 200s:
#   KILO_API_KEY (+ KILO_BASE_URL), OPENROUTER_API_KEY, and/or BYTEZ_API_KEY.
# Without keys it stays up and answers /health + /v1/models, and returns an
# honest 503 free_auto_exhausted for chat completions (fail-closed, no mocks).
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m lib.free_auto.gateway --host 127.0.0.1 --port "${FREE_AUTO_PORT:-4100}"
