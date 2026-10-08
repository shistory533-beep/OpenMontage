#!/usr/bin/env bash
# FREE-AUTO gateway lifecycle: single launch system for the endpoint
# opencode.json dials (http://127.0.0.1:${FREE_AUTO_PORT:-4100}/v1).
#
#   bash scripts/free_auto_gateway.sh start    # idempotent ensure (default)
#   bash scripts/free_auto_gateway.sh check    # health probe, exit 0/1
#   bash scripts/free_auto_gateway.sh status   # human-readable state
#   bash scripts/free_auto_gateway.sh restart  # stop ours + start
#   bash scripts/free_auto_gateway.sh stop     # stop only our gateway
#   bash scripts/free_auto_gateway.sh logs     # tail gateway log
#
# The gateway needs upstream credentials to return 200s (KILO_API_KEY +
# KILO_BASE_URL, OPENROUTER_API_KEY, and/or BYTEZ_API_KEY). Without keys it
# stays up and answers /health + /v1/models, returning an honest 503
# free_auto_exhausted for chat completions (fail-closed, never mocked).
#
# Autostart: .devcontainer/devcontainer.json postStartCommand runs
# `start` on container start; agents/session-start run the same command.
set -euo pipefail

HOST="127.0.0.1"
PORT="${FREE_AUTO_PORT:-4100}"
BASE_URL="http://${HOST}:${PORT}/v1"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="${TMPDIR:-/tmp}/opencode"
PID_FILE="${RUN_DIR}/free-auto-gateway-${PORT}.pid"
LOG_FILE="${RUN_DIR}/free-auto-gateway-${PORT}.log"

mkdir -p "${RUN_DIR}"

_py() { python3 -c "$1"; }

# check: exit 0 iff OUR gateway answers /v1/models with the virtual model.
cmd_check() {
    _py "
import json, sys, urllib.request
try:
    with urllib.request.urlopen('${BASE_URL}/models', timeout=5) as r:
        body = json.loads(r.read().decode() or '{}')
        ids = [m.get('id') for m in body.get('data', [])]
        sys.exit(0 if (r.status == 200 and 'free-auto' in ids) else 1)
except Exception as e:
    print(f'check failed: {type(e).__name__}: {e}')
    sys.exit(1)"
}

# port_open: exit 0 iff something accepts TCP on HOST:PORT (ours or not).
port_open() {
    _py "
import socket, sys
s = socket.socket(); s.settimeout(3)
try:
    s.connect(('${HOST}', ${PORT})); sys.exit(0)
except OSError:
    sys.exit(1)"
}

our_pid() {
    # Prints the pidfile PID only if that process is our gateway; else empty.
    if [[ -f "${PID_FILE}" ]]; then
        local pid; pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
        if [[ "${pid}" =~ ^[0-9]+$ ]] && ps -p "${pid}" -o args= 2>/dev/null \
                | grep -q "lib.free_auto.gateway"; then
            printf '%s' "${pid}"
        fi
    fi
}

cmd_start() {
    if cmd_check >/dev/null 2>&1; then
        echo "free-auto: already running and healthy at ${BASE_URL} (virtual model: free-auto)"
        return 0
    fi
    if port_open; then
        echo "free-auto: ERROR port ${PORT} is held by a process that is NOT a healthy gateway." >&2
        echo "free-auto: refusing to kill or shadow it. Inspect with: ss -ltnp | grep ${PORT}" >&2
        return 2
    fi
    local stale; stale="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${stale}" ]]; then
        echo "free-auto: stale pidfile (pid ${stale} gone) — starting fresh"
    fi
    echo "free-auto: starting gateway on ${HOST}:${PORT} (log: ${LOG_FILE})"
    cd "${REPO_ROOT}"
    # Detached so it survives the invoking shell; lifecycle owned via pidfile.
    nohup python3 -m lib.free_auto.gateway --host "${HOST}" --port "${PORT}" \
        >>"${LOG_FILE}" 2>&1 &
    echo "$!" > "${PID_FILE}"
    local i
    for i in $(seq 1 30); do
        if cmd_check >/dev/null 2>&1; then
            echo "free-auto: healthy at ${BASE_URL} (pid $(cat "${PID_FILE}"))"
            return 0
        fi
        sleep 1
    done
    echo "free-auto: ERROR gateway did not become healthy within 30s." >&2
    echo "free-auto: tail of ${LOG_FILE}:" >&2
    tail -20 "${LOG_FILE}" >&2 || true
    return 1
}

cmd_stop() {
    local pid; pid="$(our_pid)"
    if [[ -z "${pid}" ]]; then
        echo "free-auto: no gateway of ours to stop (pidfile absent or stale)"
        rm -f "${PID_FILE}"
        return 0
    fi
    kill "${pid}" && echo "free-auto: stopped pid ${pid}"
    rm -f "${PID_FILE}"
}

cmd_restart() {
    cmd_stop || true
    cmd_start
}

cmd_status() {
    if cmd_check >/dev/null 2>&1; then
        echo "free-auto: UP ${BASE_URL} (pid: $(our_pid || echo 'external'))"
        _py "
import json, urllib.request
with urllib.request.urlopen('${BASE_URL}/models', timeout=5) as r:
    ids = [m.get('id') for m in json.loads(r.read().decode()).get('data', [])]
    print('models:', ids)"
    elif port_open; then
        echo "free-auto: DEGRADED — port ${PORT} busy but no healthy gateway (foreign holder?)"
        return 2
    else
        echo "free-auto: DOWN — nothing listening on ${HOST}:${PORT}"
        return 1
    fi
}

cmd_logs() {
    tail -50 "${LOG_FILE}" 2>/dev/null || echo "free-auto: no log yet at ${LOG_FILE}"
}

cmd="${1:-start}"
case "${cmd}" in
    start)   cmd_start ;;
    check)   cmd_check && echo "free-auto: check OK ${BASE_URL}" ;;
    status)  cmd_status ;;
    restart) cmd_restart ;;
    stop)    cmd_stop ;;
    logs)    cmd_logs ;;
    *) echo "usage: $0 {start|check|status|restart|stop|logs}" >&2; exit 2 ;;
esac
