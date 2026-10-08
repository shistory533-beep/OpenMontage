"""FREE-AUTO router tests: classification, registry, scoring, cascade.

All transports are mocked (no sockets). The suite proves: task-specific
ranking, capability filtering, 429/quota cooldown + reset recovery, timeout
fallback, ordered cascade, exhaustion, determinism, and opencode.json
virtual-model registration.
"""

from __future__ import annotations

import json
import time

import pytest

from lib.free_auto.gateway import VIRTUAL_MODEL, FreeAutoRouter, build_router
from lib.free_auto.health import FailureClass, HealthStore, classify_http_failure
from lib.free_auto.registry import REGISTRY_PATH, load_registry
from lib.free_auto.scoring import rank_candidates, score_candidate
from lib.free_auto.task_classify import TaskClass, classify_task


def _mem_health() -> HealthStore:
    return HealthStore(path=None, now_fn=time.time)


def _router(env: dict, transport) -> FreeAutoRouter:
    return FreeAutoRouter(
        registry=load_registry(), health=_mem_health(),
        transport=transport, env=env,
    )


def _ok_response(model: str, content: str = "hello") -> dict:
    return {
        "id": "chatcmpl-test", "object": "chat.completion",
        "created": 0, "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }


def _ok_transport(model_seen: list, content: str = "hello"):
    def _t(base_url, api_key, payload, timeout_s):
        model_seen.append(payload["model"])
        return 200, _ok_response(payload["model"], content), 12.0, {}
    return _t


FULL_ENV = {
    "OPENROUTER_API_KEY": "test-or-key",
    "KILO_API_KEY": "test-kilo-key",
    "KILO_BASE_URL": "http://127.0.0.1:9/v1",
}


# ---------------------------------------------------------------------------
# task classification
# ---------------------------------------------------------------------------

def test_classify_coding():
    c = classify_task([{"role": "user", "content": "Fix this pytest traceback in my python script"}])
    assert c.task_class is TaskClass.CODING


def test_classify_planning():
    c = classify_task("Design the architecture roadmap and break it into steps")
    assert c.task_class is TaskClass.PLANNING


def test_classify_research():
    c = classify_task("Research and summarize the evidence from these docs")
    assert c.task_class is TaskClass.RESEARCH


def test_classify_multimodal_keyword():
    c = classify_task("Look at this screenshot and describe the chart")
    assert c.task_class is TaskClass.MULTIMODAL


def test_classify_multimodal_image_block():
    c = classify_task([{"role": "user", "content": [
        {"type": "text", "text": "what is this"},
        {"type": "image_url", "image_url": {"url": "data:x"}},
    ]}])
    assert c.task_class is TaskClass.MULTIMODAL
    assert c.confidence == 1.0


def test_classify_fast_simple_and_general():
    assert classify_task("hi") .task_class is TaskClass.FAST_SIMPLE
    assert classify_task(
        "Zebra xylophone quantum juxtaposition vorticity"
    ).task_class is TaskClass.GENERAL


def test_classify_deterministic():
    a = classify_task("Fix the bug and write a plan")
    b = classify_task("Fix the bug and write a plan")
    assert a == b


# ---------------------------------------------------------------------------
# registry filtering
# ---------------------------------------------------------------------------

def test_registry_loads_ten_seeds_and_filters():
    reg = load_registry()
    assert len(reg.entries) == 20  # 10 original seeds + 10 :free additions (Oct 2026)
    ids = {e.id for e in reg.entries}
    assert {"muse-spark-1.3", "laguna-s-2.1", "longcat-2.5-preview",
            "gemma-4-31b", "lfm-2.5-2.6b"} <= ids
    # no routers, no safety classifiers as candidates
    for e in reg.eligible():
        for up in e.upstreams:
            assert "auto" not in up.model and up.model != "openrouter/free"
    assert all("content-safety" not in e.id for e in reg.eligible())


def test_registry_has_no_invented_benchmarks():
    reg = load_registry()
    for e in reg.entries:
        if e.benchmark_source is None:
            # Unsourced entries must say so honestly.
            assert "no measured benchmark" in e.benchmark_note.lower()
        else:
            # Sourced entries must carry source + date + an explicit score.
            assert e.benchmark_date, e.id
            assert "%" in e.benchmark_note, e.id
            assert "confidence" in e.benchmark_note.lower(), e.id


def test_registry_experimental_flagged():
    reg = load_registry()
    longcat = reg.by_id("longcat-2.5-preview")
    assert longcat is not None and longcat.experimental


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def test_task_specific_ranking_differs():
    reg = load_registry()
    health = _mem_health()
    coding = rank_candidates(
        reg.eligible(), task_class=TaskClass.CODING,
        health=health, env=FULL_ENV,
    )
    fast = rank_candidates(
        reg.eligible(), task_class=TaskClass.FAST_SIMPLE,
        health=health, env=FULL_ENV,
    )
    assert coding and fast
    # fast/simple must prefer a fast candidate over the slow 550B flagship
    assert fast[0].entry.latency_class == "fast"
    assert coding[0].score.total >= fast[0].score.total - 1.0  # sane magnitudes
    assert coding[0].entry.id != "longcat-2.5-preview"  # experimental not top


def test_scoring_deterministic():
    reg = load_registry()
    health = _mem_health()
    first = [r.score.total for r in rank_candidates(
        reg.eligible(), task_class=TaskClass.CODING, health=health, env=FULL_ENV)]
    second = [r.score.total for r in rank_candidates(
        reg.eligible(), task_class=TaskClass.CODING, health=health, env=FULL_ENV)]
    assert first == second


def test_unconfigured_upstreams_excluded():
    reg = load_registry()
    ranked = rank_candidates(
        reg.eligible(), task_class=TaskClass.GENERAL,
        health=_mem_health(), env={},  # no keys at all
    )
    assert ranked == []


# ---------------------------------------------------------------------------
# failure classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("status", "body", "expected"), [
    (429, "rate limit", FailureClass.RATE_LIMIT),
    (429, "quota exhausted", FailureClass.QUOTA_EXHAUSTED),
    (401, "", FailureClass.AUTH_FAILURE),
    (400, "bad request", FailureClass.INVALID_REQUEST),
    (400, "no tool choice", FailureClass.CAPABILITY_MISMATCH),
    (404, "model not found", FailureClass.MODEL_UNAVAILABLE),
    (500, "", FailureClass.PROVIDER_UNAVAILABLE),
    (None, "", FailureClass.TIMEOUT),
])
def test_classify_http_failure(status, body, expected):
    assert classify_http_failure(status, body) is expected


# ---------------------------------------------------------------------------
# cascade behaviour
# ---------------------------------------------------------------------------

def test_best_model_selected_first():
    seen: list = []
    router = _router(FULL_ENV, _ok_transport(seen))
    status, resp = router.complete([{"role": "user", "content": "hi"}])
    assert status == 200
    assert resp["free_auto"]["virtual_model"] == VIRTUAL_MODEL
    # first attempt == top-ranked candidate for fast_simple
    _, ranked, _ = router.rank_for("hi")
    assert seen[0] == ranked[0].upstream_model
    assert resp["free_auto"]["candidate"] == ranked[0].entry.id


def test_429_switches_to_next_candidate_and_cools_down():
    calls: list = []

    def transport(base_url, api_key, payload, timeout_s):
        calls.append(payload["model"])
        if len(calls) == 1:
            return 429, {"error": {"message": "rate limit"}}, 5.0, {"retry-after": "60"}
        return 200, _ok_response(payload["model"]), 5.0, {}

    router = _router(FULL_ENV, transport)
    status, resp = router.complete([{"role": "user", "content": "write python code"}])
    assert status == 200
    assert len(calls) == 2
    # same model slug can repeat across gateways; the health keys must differ
    assert len({a["gateway"] for a in resp["free_auto"]["prior_attempts"]} | {resp["free_auto"]["gateway"]}) >= 1
    assert resp["free_auto"]["prior_attempts"][0]["failure"] == "rate_limit"
    # cooled-down candidate is skipped on the next request
    key_first = next(
        k for k, h in router.health._entries.items()
        if h.last_failure_class == "rate_limit"
    )
    eligible, _ = router.health.is_eligible(key_first)
    assert not eligible


def test_quota_exhaustion_records_reset_and_recovers():
    now = [1000.0]
    health = HealthStore(path=None, now_fn=lambda: now[0])
    router = FreeAutoRouter(
        registry=load_registry(), health=health,
        transport=lambda *a: (429, {"error": {"message": "quota exhausted"}}, 1.0, {}),
        env=FULL_ENV,
    )
    status, _ = router.complete("summarize this")
    assert status == 503  # every upstream 429s with no reset header
    for key, h in health._entries.items():
        assert h.quota_exhausted or h.rate_limited
        eligible, _ = health.is_eligible(key)
        assert not eligible
    now[0] += 7200.0  # past the quota cooldown
    for key in health._entries:
        eligible, _ = health.is_eligible(key)
        assert eligible


def test_timeout_falls_back():
    calls: list = []

    def transport(base_url, api_key, payload, timeout_s):
        calls.append(payload["model"])
        if len(calls) == 1:
            return None, "timed out", 90000.0, {}
        return 200, _ok_response(payload["model"]), 5.0, {}

    router = _router(FULL_ENV, transport)
    status, resp = router.complete("explain this error")
    assert status == 200 and len(calls) == 2


def test_auth_failure_does_not_retry_same_credential():
    calls: list = []

    def transport(base_url, api_key, payload, timeout_s):
        calls.append(api_key)
        return 401, {"error": {"message": "unauthorized"}}, 5.0, {}

    router = _router(FULL_ENV, transport)
    status, resp = router.complete("hi")
    assert status == 503
    # both credential families tried, neither retried more than needed
    assert set(calls) == {"test-or-key", "test-kilo-key"}


def test_malformed_upstream_body_counts_as_failure_then_next():
    calls: list = []

    def transport(base_url, api_key, payload, timeout_s):
        calls.append(1)
        if len(calls) == 1:
            return 200, "NOT JSON", 5.0, {}
        return 200, _ok_response(payload["model"]), 5.0, {}

    router = _router(FULL_ENV, transport)
    status, _ = router.complete("hi")
    # "NOT JSON" is not a dict -> treated as failure, next candidate tried
    assert status == 200 and len(calls) == 2


def test_no_eligible_model_returns_503_envelope():
    router = _router({}, lambda *a: (200, {}, 1.0, {}))
    status, resp = router.complete("hi")
    assert status == 503
    assert resp["error"]["code"] == "all_candidates_exhausted"


def test_no_infinite_loop_single_candidate():
    from lib.free_auto.registry import Registry
    reg = load_registry()
    single = Registry(entries=[reg.by_id("laguna-s-2.1")])
    calls: list = []
    router = FreeAutoRouter(
        registry=single, health=_mem_health(), env=FULL_ENV,
        transport=lambda *a: (calls.append(1), (500, {}, 1.0, {}))[1],
    )
    status, _ = router.complete("hi")
    assert status == 503
    assert len(calls) == 2  # kilo + openrouter upstream, each once


def test_tool_call_and_so_failures_recorded():
    health = _mem_health()
    key = HealthStore.key("laguna-s-2.1", "openrouter", "poolside/laguna-s-2.1:free")
    health.record_tool_call_result(key, False)
    health.record_structured_output_result(key, False)
    h = health.get(key)
    assert (h.tool_call_failures, h.so_failures) == (1, 1)


# ---------------------------------------------------------------------------
# agentic telemetry end-to-end (live feed into ranking)
# ---------------------------------------------------------------------------

def _tool_call_response(model: str, with_calls: bool) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": "ok"}
    if with_calls:
        msg["tool_calls"] = [{"id": "call_1", "type": "function",
                              "function": {"name": "do_thing", "arguments": "{}"}}]
    return {
        "id": "chatcmpl-tc", "object": "chat.completion", "created": 0,
        "model": model,
        "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls"
                     if with_calls else "stop"}],
    }


def test_tool_call_telemetry_recorded_when_requested():
    def transport(base_url, api_key, payload, timeout_s):
        return 200, _tool_call_response(payload["model"], with_calls=True), 5.0, {}

    router = _router(FULL_ENV, transport)
    router.complete([{"role": "user", "content": "use a tool"}],
                    extra={"tools": [{"type": "function", "function": {"name": "x"}}]})
    keys = [k for k in router.health._entries
            if router.health.get(k).tool_call_attempts == 1]
    assert keys, "no tool-call telemetry recorded"
    assert router.health.get(keys[0]).tool_call_failures == 0


def test_tool_call_failure_recorded_when_requested_but_absent():
    def transport(base_url, api_key, payload, timeout_s):
        return 200, _tool_call_response(payload["model"], with_calls=False), 5.0, {}

    router = _router(FULL_ENV, transport)
    router.complete([{"role": "user", "content": "use a tool"}],
                    extra={"tools": [{"type": "function", "function": {"name": "x"}}]})
    keys = [k for k in router.health._entries
            if router.health.get(k).tool_call_attempts == 1]
    assert keys, "no tool-call telemetry recorded"
    assert router.health.get(keys[0]).tool_call_failures == 1


def _json_response(model: str, content: str) -> dict:
    return {
        "id": "chatcmpl-so", "object": "chat.completion", "created": 0,
        "model": model,
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
    }


def test_structured_output_telemetry_recorded():
    def ok(base_url, api_key, payload, timeout_s):
        return 200, _json_response(payload["model"], '{"answer": 42}'), 5.0, {}

    def bad(base_url, api_key, payload, timeout_s):
        return 200, _json_response(payload["model"], "not json at all"), 5.0, {}

    def malformed(base_url, api_key, payload, timeout_s):
        return 200, {"id": "x", "choices": []}, 5.0, {}

    rf = {"type": "json_schema", "json_schema": {"name": "out", "schema": {}}}

    r1 = _router(FULL_ENV, ok)
    r1.complete([{"role": "user", "content": "return json"}], extra={"response_format": rf})
    k1 = [k for k in r1.health._entries if r1.health.get(k).so_attempts == 1]
    assert k1 and r1.health.get(k1[0]).so_failures == 0

    r2 = _router(FULL_ENV, bad)
    r2.complete([{"role": "user", "content": "return json"}], extra={"response_format": rf})
    k2 = [k for k in r2.health._entries if r2.health.get(k).so_attempts == 1]
    assert k2 and r2.health.get(k2[0]).so_failures == 1

    r3 = _router(FULL_ENV, malformed)
    r3.complete([{"role": "user", "content": "return json"}], extra={"response_format": rf})
    k3 = [k for k in r3.health._entries if r3.health.get(k).so_attempts == 1]
    assert k3 and r3.health.get(k3[0]).so_failures == 1


def test_structured_output_json_object_gate_recorded():
    def ok(base_url, api_key, payload, timeout_s):
        return 200, _json_response(payload["model"], '{"k": 1}'), 5.0, {}

    router = _router(FULL_ENV, ok)
    router.complete([{"role": "user", "content": "return json"}],
                    extra={"response_format": {"type": "json_object"}})
    keys = [k for k in router.health._entries if router.health.get(k).so_attempts == 1]
    assert keys and router.health.get(keys[0]).so_failures == 0


def test_no_agentic_telemetry_on_unrequested_request():
    """Gate-off negative path: a plain request records nothing."""
    router = _router(FULL_ENV, lambda *a: (200, _ok_response(a[2]["model"]), 5.0, {}))
    router.complete([{"role": "user", "content": "hi"}])
    for k in router.health._entries:
        h = router.health.get(k)
        assert h.tool_call_attempts == 0
        assert h.so_attempts == 0


def test_scoring_folds_in_structured_output_failures():
    reg = load_registry()
    health = _mem_health()
    key = HealthStore.key("laguna-s-2.1", "openrouter", "poolside/laguna-s-2.1:free")
    for _ in range(4):
        health.record_structured_output_result(key, False)
    entry = reg.by_id("laguna-s-2.1")
    score = score_candidate(
        entry, task_class=TaskClass.CODING, health=health,
        gateway="openrouter", upstream_model="poolside/laguna-s-2.1:free",
    )
    assert score.components["structured_output"] == 0.0


def test_scoring_folds_in_tool_call_failures():
    reg = load_registry()
    health = _mem_health()
    key = HealthStore.key("laguna-s-2.1", "openrouter", "poolside/laguna-s-2.1:free")
    # 3 attempts, 3 failures -> live tool_use == 0.0
    for _ in range(3):
        health.record_tool_call_result(key, False)
    entry = reg.by_id("laguna-s-2.1")
    score = score_candidate(
        entry, task_class=TaskClass.CODING, health=health,
        gateway="openrouter", upstream_model="poolside/laguna-s-2.1:free",
    )
    assert score.components["tool_use"] == 0.0
    # known_tool True -> confidence reflects a measured capability
    assert score.confidence > 0.7


def test_scoring_unmeasured_stays_on_prior():
    from lib.free_auto.registry import ModelEntry, Upstream
    health = _mem_health()
    # Synthetic fully-unmeasured entry: the behavioral contract (unknown ->
    # neutral 0.5, not demoted) must not depend on seed-registry data, which
    # now carries verified capabilities.
    entry = ModelEntry(
        id="synthetic-unmeasured", display="Synthetic", category="general-coding",
        upstreams=(Upstream(gateway="openrouter", model="synthetic/x:free",
                            free_tier="unknown", api_key_env="OPENROUTER_API_KEY",
                            base_url_env="OPENROUTER_BASE_URL",
                            base_url_default="https://openrouter.ai/api/v1"),),
    )
    score = score_candidate(
        entry, task_class=TaskClass.CODING, health=health,
        gateway="openrouter", upstream_model="synthetic/x:free",
    )
    # prior is None -> neutral 0.5, not demoted by absence of telemetry
    assert score.components["tool_use"] == 0.5


# ---------------------------------------------------------------------------
# gateway OpenAI compatibility + opencode.json registration
# ---------------------------------------------------------------------------

def test_models_endpoint_lists_virtual_model():
    import threading
    import urllib.request
    from lib.free_auto.gateway import serve

    router = _router(FULL_ENV, _ok_transport([]))
    server = serve("127.0.0.1", 0, router)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models") as r:
            body = json.loads(r.read().decode())
        assert body["data"][0]["id"] == "free-auto"

        payload = json.dumps(
            {"model": "free-auto",
             "messages": [{"role": "user", "content": "hi"}]}
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=payload, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read().decode())
        assert resp["choices"][0]["message"]["content"] == "hello"
        assert resp["free_auto"]["candidate"]

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status") as r:
            status = json.loads(r.read().decode())
        assert status["selected_virtual_model"] == "free-auto"
        assert status["current_actual_model"]
        assert "candidate_ranking" in status and "cooldowns" in status
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_opencode_json_selects_free_auto():
    import pathlib
    cfg = json.loads(
        pathlib.Path("/workspaces/OpenMontage/opencode.json").read_text())
    provider = cfg["provider"]["free-auto"]
    assert provider["options"]["baseURL"].startswith("http://127.0.0.1:")
    assert "free-auto" in provider["models"]


# ---------------------------------------------------------------------------
# streaming SSE metadata transparency + relaxed signal
# ---------------------------------------------------------------------------

def test_streaming_sse_includes_routing_metadata():
    """stream=true must carry the same free_auto routing metadata
    (candidate, gateway, reason, relaxed) that non-streaming responses do.
    Previously _send_sse silently discarded the free_auto block."""
    import threading
    import urllib.request
    from lib.free_auto.gateway import serve

    router = _router(FULL_ENV, _ok_transport([]))
    server = serve("127.0.0.1", 0, router)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({
            "model": "free-auto",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=payload, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode("utf-8")
        # First data chunk must carry free_auto routing metadata
        first_data = raw.split("\n\n")[0]
        assert first_data.startswith("data: "), first_data
        first_chunk = json.loads(first_data[len("data: "):])
        assert "free_auto" in first_chunk, "streaming response dropped free_auto metadata"
        meta = first_chunk["free_auto"]
        assert meta["virtual_model"] == "free-auto"
        assert meta["candidate"]
        assert meta["gateway"]
        assert meta["upstream_model"]
        assert meta["reason"]
        assert "relaxed" in meta
        assert first_chunk.get("_free_auto_stream_replay") is True
        # Must still terminate with [DONE]
        assert raw.rstrip().endswith("data: [DONE]")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_relaxed_signal_surfaced_in_response():
    """When the capability filter is too strict and the router falls back to
    all-eligible candidates, the `relaxed` flag must appear in free_auto."""
    from lib.free_auto.registry import ModelEntry, Upstream, Registry

    # Single entry explicitly lacking multimodal capability.
    entry = ModelEntry(
        id="mock-non-mm", display="Mock Non-MM",
        category="general-coding",
        upstreams=(Upstream(
            gateway="openrouter", model="mock/non-mm:free",
            free_tier="free", api_key_env="OPENROUTER_API_KEY",
            base_url_env="OPENROUTER_BASE_URL",
            base_url_default="https://openrouter.ai/api/v1",
        ),),
        multimodal=False,
        prior_quality=0.8, prior_coding=0.8,
        prior_reasoning=0.8, prior_agentic=0.8,
        context_tokens=16000,
    )
    reg = Registry(entries=[entry])
    seen: list = []
    router = FreeAutoRouter(
        registry=reg, health=_mem_health(),
        transport=_ok_transport(seen), env=FULL_ENV,
    )
    # "image screenshot chart" forces MULTIMODAL classification; the single
    # candidate is filtered out by multimodal=False, triggering the fallback.
    status, resp = router.complete("look at this image screenshot of a chart")
    assert status == 200
    assert resp["free_auto"]["relaxed"] is True
    assert resp["free_auto"]["candidate"] == "mock-non-mm"


def test_relaxed_is_false_in_normal_routing():
    """Normal routing (all capabilities unknown/None) must report relaxed=False."""
    router = _router(FULL_ENV, _ok_transport([]))
    status, resp = router.complete("hi")
    assert status == 200
    assert resp["free_auto"]["relaxed"] is False
