"""FREE-AUTO gateway lifecycle tests: idempotent start, health, recovery.

Exercises the single launch system (scripts/free_auto_gateway.sh) on an
ephemeral port so the live :4100 gateway is untouched. Proves: start is
idempotent, a foreign port holder is refused (never killed), and a dead
gateway is detected (check/status nonzero) then recoverable via restart.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "free_auto_gateway.sh"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env(port: int) -> dict:
    env = dict(os.environ)
    env["FREE_AUTO_PORT"] = str(port)
    return env


def _run(port: int, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args],
                          capture_output=True, text=True,
                          timeout=90, env=_env(port), cwd=REPO)


def _models(port: int) -> dict:
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/v1/models", timeout=10) as r:
        assert r.status == 200
        return json.loads(r.read().decode())


def test_lifecycle_start_check_status_idempotent_and_recover():
    port = _free_port()
    try:
        # check before start: down.
        assert _run(port, "check").returncode != 0
        assert _run(port, "status").returncode != 0

        # start: gateway answers with the virtual model.
        started = _run(port, "start")
        assert started.returncode == 0, started.stderr
        assert "free-auto" in started.stdout
        models = _models(port)
        assert [m["id"] for m in models["data"]] == ["free-auto"]

        # idempotent: second start exits 0 without relaunching.
        again = _run(port, "start")
        assert again.returncode == 0, again.stderr
        assert "already running and healthy" in again.stdout

        assert _run(port, "check").returncode == 0
        assert _run(port, "status").returncode == 0

        # dead-gateway drill: kill -9 the gateway, detection must fail loud.
        assert _run(port, "stop").returncode == 0
        assert _run(port, "check").returncode != 0
        down = _run(port, "status")
        assert down.returncode != 0
        assert "DOWN" in down.stdout

        # recovery: start brings it back on the same port.
        assert _run(port, "start").returncode == 0
        assert [m["id"] for m in _models(port)["data"]] == ["free-auto"]
        assert _run(port, "restart").returncode == 0
        assert [m["id"] for m in _models(port)["data"]] == ["free-auto"]
    finally:
        _run(port, "stop")


def test_lifecycle_refuses_foreign_port_holder():
    port = _free_port()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    try:
        refused = _run(port, "start")
        assert refused.returncode == 2, (refused.returncode,
                                         refused.stdout, refused.stderr)
        assert "NOT a healthy gateway" in refused.stderr
    finally:
        blocker.close()
        _run(port, "stop")
