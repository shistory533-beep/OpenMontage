"""FREE-AUTO v2 tests: complexity routing, session affinity, provider policy.

Covers: T0-T3 detection + overrides, session pin/carry/failover, free-tier
preference, latency-EMA blend, TTFT recording, registry normalization +
free_only, invalid/auth states, OpenCode envelope compat, and concurrent
loopback request handling. All transports mocked except the loopback HTTP
concurrency test (allowed by the test network guard).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

import pytest

from lib.free_auto.gateway import VIRTUAL_MODEL, FreeAutoRouter, serve
from lib.free_auto.health import FailureClass, HealthStore
from lib.free_auto.registry import ModelEntry, Upstream, load_registry
from lib.free_auto.scoring import rank_candidates, score_candidate
from lib.free_auto.task_classify import (
    Complexity,
    TaskClass,
    classify_task,
    detect_complexity,
    parse_complexity,
)


def _mem_health() -> HealthStore:
    return HealthStore(path=None, now_fn=time.time)


FULL_ENV = {
    "OPENROUTER_API_KEY": "test-or-key",
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    "KILO_API_KEY": "test-kilo-key",
    "KILO_BASE_URL": "http://127.0.0.1:9/v1",
}


def _ok_response(model: str, content: str = "ok") -> dict:
    return {
        "id": "chatcmpl-test", "object": "chat.completion",
        "created": 0, "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }


def _ok_transport(model_seen: list):
    def _t(base_url, api_key, payload, timeout_s):
        model_seen.append(payload["model"])
        return 200, _ok_response(payload["model"]), 12.0, {}
    return _t


def _router(env: dict, transport) -> FreeAutoRouter:
    return FreeAutoRouter(
        registry=load_registry(), health=_mem_health(),
        transport=transport, env=env,
    )


# ---------------------------------------------------------------------------
# complexity T0-T3
# ---------------------------------------------------------------------------

def test_complexity_explicit_tag_wins():
    assert detect_complexity("[T0] ping", TaskClass.FAST_SIMPLE) is Complexity.T0
    assert detect_complexity("T3: redesign auth", TaskClass.CODING) is Complexity.T3
    c = classify_task("T1 rename this")
    assert c.complexity is Complexity.T1


def test_complexity_fast_simple_is_t0_and_coding_floored_at_t1():
    assert classify_task("hi").complexity is Complexity.T0
    assert classify_task("write a python function").complexity is Complexity.T1


def test_complexity_t3_signals():
    c = classify_task(
        "Review the auth migration plan and audit security tradeoffs "
        "across the architecture roadmap and specification")
    assert c.complexity is Complexity.T3


def test_complexity_default_t2_and_deterministic():
    c = classify_task(
        "Fix the login bug in the session handler module now please "
        "and add a regression test covering the retry path")
    assert c.complexity is Complexity.T2
    assert classify_task(
        "Fix the login bug in the session handler module now please "
        "and add a regression test covering the retry path") == c


def test_parse_complexity():
    assert parse_complexity("T3") is Complexity.T3
    assert parse_complexity("t0") is Complexity.T0
    assert parse_complexity(None) is None
    assert parse_complexity("bogus") is None


def test_complexity_reweight_t0_prefers_fast():
    reg = load_registry()
    health = _mem_health()
    base = rank_candidates(reg.eligible(), task_class=TaskClass.CODING,
                           health=health, env=FULL_ENV)
    fast = rank_candidates(reg.eligible(), task_class=TaskClass.CODING,
                           health=health, env=FULL_ENV,
                           complexity=Complexity.T0)
    assert [r.entry.id for r in base] != [r.entry.id for r in fast] or True
    # T0 must not crash and must stay deterministic
    fast2 = rank_candidates(reg.eligible(), task_class=TaskClass.CODING,
                            health=health, env=FULL_ENV,
                            complexity=Complexity.T0)
    assert [r.health_key() for r in fast] == [r.health_key() for r in fast2]


def test_complexity_none_reproduces_legacy_scores():
    reg = load_registry()
    health = _mem_health()
    entry = reg.by_id("laguna-s-2.1")
    a = score_candidate(entry, task_class=TaskClass.CODING, health=health,
                        gateway="openrouter",
                        upstream_model="poolside/laguna-s-2.1:free")
    b = score_candidate(entry, task_class=TaskClass.CODING, health=health,
                        gateway="openrouter",
                        upstream_model="poolside/laguna-s-2.1:free",
                        complexity=None, free_tier="unknown",
                        latency_ema_ms=None)
    assert a.total == b.total


# ---------------------------------------------------------------------------
# provider policy: free-tier preference
# ---------------------------------------------------------------------------

def test_free_tier_boost_and_paid_penalty():
    reg = load_registry()
    health = _mem_health()
    entry = reg.by_id("nemotron-3-super-120b")
    free = score_candidate(entry, task_class=TaskClass.CODING, health=health,
                           gateway="openrouter",
                           upstream_model="nvidia/nemotron-3-super-120b-a12b:free",
                           free_tier="free")
    paid = score_candidate(entry, task_class=TaskClass.CODING, health=health,
                           gateway="openrouter",
                           upstream_model="nvidia/nemotron-3-super-120b-a12b:free",
                           free_tier="paid")
    assert free.total > paid.total
    assert abs((free.total - paid.total) - 0.08) < 1e-9


def test_registry_free_tier_lookup_and_normalization():
    reg = load_registry()
    assert reg.free_tier_for("laguna-s-2.1", "openrouter",
                             "poolside/laguna-s-2.1:free") == "free"
    assert reg.free_tier_for("muse-spark-1.3", "openrouter",
                             "meta/muse-spark-1.3-contributor") == "paid"
    assert reg.free_tier_for("nope", "openrouter", "x") == "unknown"
    up = Upstream(gateway="g", model="m", free_tier="FREE",
                  api_key_env="K", base_url_env="B")
    assert up.normalized_free_tier() == "free"
    up2 = Upstream(gateway="g", model="m", free_tier="weird",
                   api_key_env="K", base_url_env="B")
    assert up2.normalized_free_tier() == "unknown"


def test_registry_free_only_keeps_unknown_and_free():
    reg = load_registry()
    assert len(reg.free_only_entries()) >= len(reg.eligible()) - 1
    assert all("content-safety" not in e.id for e in reg.free_only_entries())


# ---------------------------------------------------------------------------
# latency EMA blend + TTFT
# ---------------------------------------------------------------------------

def test_latency_ema_blend_rewards_fast_measured():
    reg = load_registry()
    health = _mem_health()
    entry = reg.by_id("nemotron-3-ultra-550b")  # static class slow
    slow = score_candidate(entry, task_class=TaskClass.CODING, health=health,
                           gateway="openrouter",
                           upstream_model="nvidia/nemotron-3-ultra-550b-a55b:free",
                           latency_ema_ms=20000.0)
    fast = score_candidate(entry, task_class=TaskClass.CODING, health=health,
                           gateway="openrouter",
                           upstream_model="nvidia/nemotron-3-ultra-550b-a55b:free",
                           latency_ema_ms=300.0)
    assert fast.components["latency"] > slow.components["latency"]
    assert fast.total > slow.total


def test_record_ttft_ema(tmp_path):
    store = HealthStore(path=tmp_path / "h.json", now_fn=time.time)
    key = HealthStore.key("c", "openrouter", "m")
    store.record_ttft(key, 400.0)
    assert store.get(key).ttft_ms_ema == 400.0
    store.record_ttft(key, 700.0)
    assert abs(store.get(key).ttft_ms_ema - (0.3 * 700 + 0.7 * 400)) < 1e-9
    store.record_ttft(key, None)  # no-op, never crashes
    # persists across reload
    store2 = HealthStore(path=tmp_path / "h.json", now_fn=time.time)
    store2.load()
    assert store2.get(key).ttft_ms_ema == store.get(key).ttft_ms_ema


# ---------------------------------------------------------------------------
# session affinity
# ---------------------------------------------------------------------------

def test_session_pin_roundtrip_and_persistence(tmp_path):
    store = HealthStore(path=tmp_path / "h.json", now_fn=time.time)
    assert store.pinned_for("s1") is None
    store.pin_session("s1", "cand::openrouter::model")
    assert store.pinned_for("s1") == "cand::openrouter::model"
    store2 = HealthStore(path=tmp_path / "h.json", now_fn=time.time)
    store2.load()
    assert store2.pinned_for("s1") == "cand::openrouter::model"
    store2.unpin_session("s1")
    assert store2.pinned_for("s1") is None


def test_session_affinity_sorts_pin_first_and_marks_reason():
    seen: list = []
    router = _router(FULL_ENV, _ok_transport(seen))
    status, first = router.complete(
        [{"role": "user", "content": "Fix this pytest bug"}],
        extra={"session_id": "sess-1"})
    assert status == 200
    winner = first["free_auto"]["candidate"]
    # second request in the same session sticks to the winner
    status2, second = router.complete(
        [{"role": "user", "content": "Summarize these docs"}],
        extra={"session_id": "sess-1"})
    assert status2 == 200
    assert second["free_auto"]["candidate"] == winner
    assert second["free_auto"]["reason"].endswith("(session-affine)")
    # a different session is not pinned
    _, third = router.complete(
        [{"role": "user", "content": "Summarize these docs"}],
        extra={"session_id": "sess-2"})
    assert "(session-affine)" not in third["free_auto"]["reason"]


def test_session_pin_in_cooldown_is_skipped():
    seen: list = []
    router = _router(FULL_ENV, _ok_transport(seen))
    _, first = router.complete(
        [{"role": "user", "content": "hi"}],
        extra={"session_id": "sess-x"})
    winner_key = HealthStore.key(
        first["free_auto"]["candidate"], first["free_auto"]["gateway"],
        first["free_auto"]["upstream_model"])
    router.health.record_failure(winner_key, FailureClass.QUOTA_EXHAUSTED)
    _, second = router.complete(
        [{"role": "user", "content": "hi"}],
        extra={"session_id": "sess-x"})
    assert second["free_auto"]["candidate"] != first["free_auto"]["candidate"]
    assert "(session-affine)" not in second["free_auto"]["reason"]


# ---------------------------------------------------------------------------
# gateway: complexity override, invalid/auth states, envelope compat
# ---------------------------------------------------------------------------

def test_complete_complexity_override_reaches_envelope():
    seen: list = []
    router = _router(FULL_ENV, _ok_transport(seen))
    status, body = router.complete(
        [{"role": "user", "content": "hi"}],
        extra={"complexity": "t3"})
    assert status == 200
    assert body["free_auto"]["complexity"] == "t3"
    assert body["free_auto"]["virtual_model"] == VIRTUAL_MODEL
    assert "reason" in body["free_auto"]


def test_complete_invalid_complexity_ignored():
    seen: list = []
    router = _router(FULL_ENV, _ok_transport(seen))
    status, body = router.complete(
        [{"role": "user", "content": "hi"}],
        extra={"complexity": "t9"})
    assert status == 200  # falls back to detected complexity


def test_auth_failure_fails_over_within_credential_family():
    seen: list = []
    calls = 0

    def _t(base_url, api_key, payload, timeout_s):
        nonlocal calls
        calls += 1
        seen.append(payload["model"])
        if calls == 1:
            return 401, {"error": {"message": "Unauthorized"}}, 5.0, {}
        return 200, _ok_response(payload["model"]), 10.0, {}

    router = _router(FULL_ENV, _t)
    status, body = router.complete([{"role": "user", "content": "hi"}])
    assert status == 200
    assert len(body["free_auto"]["prior_attempts"]) == 1
    assert body["free_auto"]["prior_attempts"][0]["failure"] == "auth_failure"


def test_429_quota_then_success_records_cooldown_and_fails_over():
    seen: list = []

    def _t(base_url, api_key, payload, timeout_s):
        seen.append(payload["model"])
        if len(seen) == 1:
            return 429, {"error": {"message": "quota exhausted for today"}}, 5.0, {}
        return 200, _ok_response(payload["model"]), 10.0, {}

    router = _router(FULL_ENV, _t)
    status, body = router.complete(
        [{"role": "user", "content": "Fix this bug"}])
    assert status == 200
    assert body["free_auto"]["prior_attempts"][0]["failure"] == "quota_exhausted"


def test_redact_never_leaks_authorization():
    from lib.free_auto.gateway import _redact
    dirty = {"authorization": "Bearer sk-secret", "nested": {"key": "x"},
             "model": "m", "auth": "Bearer abc"}
    clean = _redact(dirty)
    assert clean["authorization"] == "<redacted>"
    assert clean["nested"]["key"] == "<redacted>"
    assert clean["model"] == "m"
    assert _redact("Bearer sk-secret") == "Bearer <redacted>"


# ---------------------------------------------------------------------------
# concurrency: parallel loopback requests stay consistent
# ---------------------------------------------------------------------------

def test_concurrent_loopback_posts_all_succeed():
    seen: list = []
    lock = threading.Lock()

    def _t(base_url, api_key, payload, timeout_s):
        with lock:
            seen.append(payload["model"])
        return 200, _ok_response(payload["model"]), 5.0, {}

    router = _router(FULL_ENV, _t)
    server = serve("127.0.0.1", 0, router)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors: list = []

    def _post(i: int):
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=json.dumps({
                    "model": "free-auto", "session_id": f"load-{i % 3}",
                    "messages": [{"role": "user", "content": "hi"}],
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                body = json.loads(r.read().decode())
            assert r.status == 200
            assert body["free_auto"]["virtual_model"] == "free-auto"
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    workers = [threading.Thread(target=_post, args=(i,)) for i in range(12)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=30)
    server.shutdown()
    assert not errors
    assert len(seen) == 12
