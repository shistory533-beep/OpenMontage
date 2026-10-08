"""FREE-AUTO gateway connectivity regression tests (2026-10-08 incident).

Incident: OpenCode failed with ``ConnectionRefused: Unable to connect``
because no gateway process was listening on the endpoint configured in
``opencode.json`` (``http://127.0.0.1:4100/v1``). Nothing starts the
gateway automatically — that is the root cause, not a provider outage.

These tests lock in the fix without needing a live gateway on port 4100:
config/endpoint drift guard, real-socket boot-and-answer, cascade
fallback over real HTTP, honest no-credential 503 shape, and the
structured connection-refused probe signature. Transports are stubbed
at the upstream boundary only; the OpenCode -> gateway socket path is
real (ephemeral port).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

from lib.free_auto.gateway import (
    DEFAULT_PORT,
    VIRTUAL_MODEL,
    FreeAutoRouter,
    build_router,
    probe_endpoint,
    serve,
)
from lib.free_auto.health import HealthStore
from lib.free_auto.registry import load_registry

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _mem_health() -> HealthStore:
    return HealthStore(path=None, now_fn=time.time)


def _ok_body(model: str, content: str = "gateway-ok") -> dict:
    return {"id": "chatcmpl-health", "object": "chat.completion",
            "created": 0, "model": model,
            "choices": [{"index": 0,
                         "message": {"role": "assistant",
                                     "content": content},
                         "finish_reason": "stop"}]}


def _serve(router: FreeAutoRouter):
    server = serve("127.0.0.1", 0, router)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


def _get(base: str, path: str) -> tuple[int, dict]:
    with urllib.request.urlopen(f"{base}{path}", timeout=20) as r:
        return r.status, json.loads(r.read().decode())


def _post(base: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_opencode_endpoint_matches_gateway_default_port():
    """Config drift guard: the endpoint OpenCode dials must be the port
    the gateway actually binds. A mismatch is ConnectionRefused."""
    cfg = json.loads((REPO / "opencode.json").read_text())
    base = cfg["provider"]["free-auto"]["options"]["baseURL"]
    assert base == f"http://127.0.0.1:{DEFAULT_PORT}/v1", base
    assert cfg["provider"]["free-auto"]["models"]["free-auto"]


def test_gateway_boots_and_answers_over_real_http():
    """serve() binds and answers models/health/chat over real sockets."""
    def _t(base_url, api_key, payload, timeout_s):
        return 200, _ok_body(payload["model"]), 8.0, {}

    router = FreeAutoRouter(registry=load_registry(),
                            health=_mem_health(),
                            transport=_t, env={"OPENROUTER_API_KEY": "k",
                                               "OPENROUTER_BASE_URL": "https://or/v1",
                                               "KILO_API_KEY": "k",
                                               "KILO_BASE_URL": "https://kilo/v1"})
    server, base = _serve(router)
    try:
        status, models = _get(base, "/models")
        assert status == 200
        assert VIRTUAL_MODEL in [m["id"] for m in models["data"]]

        status, health = _get(base, "/health")
        assert status == 200
        assert health["virtual_model"] == VIRTUAL_MODEL

        status, body = _post(base, {"model": "free-auto",
                                    "messages": [{"role": "user",
                                                  "content": "ping"}]})
        assert status == 200, body
        assert body["free_auto"]["virtual_model"] == VIRTUAL_MODEL
        assert body["choices"][0]["message"]["content"] == "gateway-ok"
    finally:
        server.shutdown()


def test_gateway_fallback_over_real_http():
    """Primary candidate 429s -> cascade retries next over the same socket."""
    n = {"i": 0}

    def _flaky(base_url, api_key, payload, timeout_s):
        n["i"] += 1
        if n["i"] == 1:
            return 429, {"error": {"message": "rate limit"}}, 5.0, {}
        return 200, _ok_body(payload["model"], "fallback-ok"), 5.0, {}

    router = FreeAutoRouter(registry=load_registry(),
                            health=_mem_health(),
                            transport=_flaky,
                            env={"OPENROUTER_API_KEY": "k",
                                 "OPENROUTER_BASE_URL": "https://or/v1",
                                 "KILO_API_KEY": "k",
                                 "KILO_BASE_URL": "https://kilo/v1"})
    server, base = _serve(router)
    try:
        status, body = _post(base, {"model": "free-auto",
                                    "messages": [{"role": "user",
                                                  "content": "hi"}]})
        assert status == 200, body
        assert body["choices"][0]["message"]["content"] == "fallback-ok"
        assert body["free_auto"]["prior_attempts"], \
            "fallback must be recorded, not silent"
        assert body["free_auto"]["prior_attempts"][0]["failure"] == \
            "rate_limit"
    finally:
        server.shutdown()


def test_no_credential_returns_honest_503_shape():
    """Empty env strands nothing silently: 503 + free_auto_exhausted."""
    router = FreeAutoRouter(registry=load_registry(),
                            health=_mem_health(),
                            transport=lambda *a: (_ for _ in ()).throw(
                                AssertionError("must not dial upstream")),
                            env={})
    server, base = _serve(router)
    try:
        status, body = _post(base, {"model": "free-auto",
                                    "messages": [{"role": "user",
                                                  "content": "ping"}]})
        assert status == 503
        assert body["error"]["type"] == "free_auto_exhausted"
        assert body["free_auto"]["virtual_model"] == VIRTUAL_MODEL
    finally:
        server.shutdown()


def test_probe_reports_connection_refused_structured():
    """Incident signature: dead port -> connection_refused dict, no raise."""
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    # socket closed on exit -> nothing listening on `dead`.
    result = probe_endpoint(f"http://127.0.0.1:{dead}/v1", timeout_s=3.0)
    assert result["ok"] is False
    assert result["error"] == "connection_refused"


def test_probe_ok_against_live_gateway():
    def _t(base_url, api_key, payload, timeout_s):
        return 200, _ok_body(payload["model"]), 8.0, {}

    router = FreeAutoRouter(registry=load_registry(),
                            health=_mem_health(), transport=_t,
                            env={"OPENROUTER_API_KEY": "k",
                                 "OPENROUTER_BASE_URL": "https://or/v1"})
    server, base = _serve(router)
    try:
        result = probe_endpoint(base, timeout_s=5.0)
        assert result["ok"] is True, result
        assert VIRTUAL_MODEL in result["models"]
    finally:
        server.shutdown()


def test_build_router_loads_real_registry():
    router = build_router(env={})
    assert router.registry is not None
    assert len(router.registry.eligible()) > 0
