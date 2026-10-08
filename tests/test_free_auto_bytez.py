"""Bytez provider integration tests: config, registry, routing, fallback.

No live Bytez calls (no BYTEZ_API_KEY in CI): all transports mocked except
loopback HTTP. Live status without a key is AUTH_REQUIRED by construction
(unconfigured upstreams are dropped from ranking).
"""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from lib.free_auto.gateway import FreeAutoRouter, serve
from lib.free_auto.health import HealthStore
from lib.free_auto.registry import load_registry
from lib.free_auto.scoring import rank_candidates
from lib.free_auto.task_classify import TaskClass

import time

REPO = Path(__file__).resolve().parents[1]
BYTEZ_BASE = "https://api.bytez.com/models/v2/openai/v1"


def _mem_health() -> HealthStore:
    return HealthStore(path=None, now_fn=time.time)


def test_opencode_json_bytez_provider_intact():
    cfg = json.loads((REPO / "opencode.json").read_text())
    assert cfg["provider"]["free-auto"]["models"]["free-auto"]
    bytez = cfg["provider"]["bytez"]
    assert bytez["npm"] == "@ai-sdk/openai-compatible"
    assert bytez["options"]["baseURL"] == BYTEZ_BASE
    # Key by env reference only — never a literal secret in config.
    assert bytez["options"]["apiKey"] == "{env:BYTEZ_API_KEY}"
    assert "BYTEZ_API_KEY" not in json.dumps(bytez).replace(
        "{env:BYTEZ_API_KEY}", "")
    models = bytez["models"]
    assert "Qwen/Qwen3-4B" in models
    assert "google/gemma-3-4b-it" in models


def test_registry_bytez_entries_eligible_and_never_free():
    reg = load_registry()
    bytez = [e for e in reg.eligible()
             if any(u.gateway == "bytez" for u in e.upstreams)]
    assert {e.id for e in bytez} == {"qwen3-4b", "gemma-3-4b-it"}
    for e in bytez:
        for u in e.upstreams:
            if u.gateway == "bytez":
                # Bytez bills credits; free plan is a $1/4wk allowance for
                # <=7B open models. Never claim price-free.
                assert u.normalized_free_tier() == "unknown"
                assert u.api_key_env == "BYTEZ_API_KEY"
                assert (u.base_url_default or "").rstrip("/") == BYTEZ_BASE
    # Unknown stays eligible (untested != incapable, != paid).
    assert all(e in reg.free_only_entries() for e in bytez)


def _ok(model: str) -> dict:
    return {"id": "chatcmpl-b", "object": "chat.completion", "created": 0,
            "model": model,
            "choices": [{"index": 0,
                         "message": {"role": "assistant",
                                     "content": "bytez-ok"},
                         "finish_reason": "stop"}]}


def test_gateway_bytez_bearer_auth_and_base_url():
    seen: dict = {}

    def _t(base_url, api_key, payload, timeout_s):
        seen["base_url"] = base_url
        # Transport contract: Bearer auth header is built by the transport
        # from the passed key; here assert the key reached the transport.
        seen["api_key"] = api_key
        seen["model"] = payload["model"]
        return 200, _ok(payload["model"]), 25.0, {}

    env = {"BYTEZ_API_KEY": "test-bytez-key",
           "BYTEZ_BASE_URL": "https://127.0.0.1:9/v1"}
    router = FreeAutoRouter(registry=load_registry(),
                            health=_mem_health(), transport=_t, env=env)
    # Force bytez-only ranking by configuring only the bytez credential.
    status, body = router.complete(
        [{"role": "user", "content": "hi"}],
        extra={"session_id": "bz-1"})
    assert status == 200
    assert body["free_auto"]["gateway"] == "bytez"
    assert seen["api_key"] == "test-bytez-key"
    assert seen["base_url"] == "https://127.0.0.1:9/v1"
    assert body["free_auto"]["candidate"] in {"qwen3-4b", "gemma-3-4b-it"}


def test_bytez_401_fails_over_to_different_credential():
    # Bytez-only env with a bad key: the bytez attempt records
    # auth_failure (fail-closed, no retry on the same credential).
    calls: list = []

    def _bad(base_url, api_key, payload, timeout_s):
        calls.append(payload["model"])
        return 401, {"error": {"message": "Unauthorized"}}, 5.0, {}

    env = {"BYTEZ_API_KEY": "bad-key",
           "BYTEZ_BASE_URL": "https://127.0.0.1:9/v1"}
    router = FreeAutoRouter(registry=load_registry(),
                            health=_mem_health(), transport=_bad, env=env)
    status, body = router.complete(
        [{"role": "user", "content": "hi"}])
    assert status == 503
    assert calls, "bytez candidate must have been tried"
    assert body["free_auto"]["attempts"][0]["failure"] == "auth_failure"

    # With a second credential family present, the cascade continues
    # past a 401 instead of stranding the request.
    n = {"i": 0}

    def _flaky(base_url, api_key, payload, timeout_s):
        n["i"] += 1
        if n["i"] == 1:
            return 401, {"error": {"message": "Unauthorized"}}, 5.0, {}
        return 200, _ok(payload["model"]), 10.0, {}

    env2 = {"BYTEZ_API_KEY": "bad-key",
            "BYTEZ_BASE_URL": "https://127.0.0.1:9/v1",
            "OPENROUTER_API_KEY": "good-key",
            "OPENROUTER_BASE_URL": "https://127.0.0.1:8/v1"}
    router2 = FreeAutoRouter(registry=load_registry(),
                             health=_mem_health(), transport=_flaky, env=env2)
    status2, body2 = router2.complete(
        [{"role": "user", "content": "Fix this pytest bug"}])
    assert status2 == 200
    assert body2["free_auto"]["prior_attempts"][0]["failure"] == \
        "auth_failure"


def test_bytez_unconfigured_means_auth_required_gap():
    # No BYTEZ_API_KEY anywhere: bytez upstreams drop out of ranking
    # (AUTH_REQUIRED by construction), other providers unaffected.
    reg = load_registry()
    ranked = rank_candidates(
        reg.eligible(), task_class=TaskClass.FAST_SIMPLE,
        health=_mem_health(), env={},
        free_tier_for=reg.free_tier_for)
    assert ranked == []
    ranked_or = rank_candidates(
        reg.eligible(), task_class=TaskClass.FAST_SIMPLE,
        health=_mem_health(),
        env={"OPENROUTER_API_KEY": "k",
             "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1"},
        free_tier_for=reg.free_tier_for)
    assert ranked_or, "openrouter-only env must still rank"
    assert all(r.gateway == "openrouter" for r in ranked_or)


def test_bytez_loopback_session_affinity():
    seen: list = []

    def _t(base_url, api_key, payload, timeout_s):
        seen.append(payload["model"])
        return 200, _ok(payload["model"]), 5.0, {}

    env = {"BYTEZ_API_KEY": "k", "BYTEZ_BASE_URL": "https://b/v1"}
    router = FreeAutoRouter(registry=load_registry(),
                            health=_mem_health(), transport=_t, env=env)
    server = serve("127.0.0.1", 0, router)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def _post(session: str) -> dict:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=json.dumps(
                    {"model": "bytez-test", "session_id": session,
                     "messages": [{"role": "user",
                                   "content": "hi"}]}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode()
                                  )
        first = _post("bz-sess")
        second = _post("bz-sess")
        assert first["free_auto"]["gateway"] == "bytez"
        assert second["free_auto"]["candidate"] == \
            first["free_auto"]["candidate"]
        assert second["free_auto"]["reason"].endswith("(session-affine)")
    finally:
        server.shutdown()
    assert len(seen) == 2
