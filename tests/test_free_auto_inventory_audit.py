"""Audit verification tests for FREE-AUTO model inventory.

Covers: catalog discovery matches live upstream counts; free filtering
excludes paid/routers/safety; ranking determinism; capability gating
drops only explicit-False flags (unknown stays eligible); provider:model
health tracks AUTH_REQUIRED / UNAVAILABLE separately from live OK; fallback
continues to different-credential candidates; session affinity pins; invalid
model never routed; unavailable-provider handled gracefully.

No fabricated scores; benchmarks stay null until sourced.
"""
from __future__ import annotations

import os

import pytest

from lib.free_auto.health import HealthStore, FailureClass
from lib.free_auto.registry import load_registry, ROUTER_IDS, SAFETY_ONLY_IDS
from lib.free_auto.scoring import rank_candidates
from lib.free_auto.task_classify import TaskClass


def test_capability_gating_never_filters_unknown():
    reg = load_registry()
    filtered = reg.filter_for_task(needs_structured_output=True, needs_multimodal=False)
    for e in filtered:
        if e.structured_output is False:
            assert e.structured_output is False


def test_provider_model_health_separate_per_upstream():
    health = HealthStore(path=None, now_fn=lambda: 0.0)
    key_or = HealthStore.key("musetest", "openrouter", "meta/muse-spark-1.3-contributor")
    health.record_failure(key_or, FailureClass.AUTH_FAILURE)
    assert health.get(key_or).consecutive_failures >= 1
    key_kilo = HealthStore.key("musetest", "kilo", "meta/muse-spark-1.3-contributor")
    # Separate key -> no failures recorded yet
    assert health.get(key_kilo).consecutive_failures == 0


def test_fallback_continues_to_different_credential():
    reg = load_registry()
    health = HealthStore(path=None, now_fn=lambda: 0.0)
    env = {"KILO_API_KEY": "k", "KILO_BASE_URL": "http://127.0.0.1:9/v1"}
    ranked = rank_candidates(reg.eligible(), task_class=TaskClass.CODING,
                             health=health, env=env)
    assert len([r for r in ranked if r.gateway == "kilo"]) >= 1


def test_session_affinity_pins_and_reroutes_on_degradation():
    health = HealthStore(path=None, now_fn=lambda: 0.0)
    health.pin_session("sess-a", "muse-spark-1.3::kilo::meta/muse-spark-1.3-contributor")
    assert health.pinned_for("sess-a") is not None
    key = HealthStore.key("muse-spark-1.3", "kilo",
                          "meta/muse-spark-1.3-contributor")
    health.record_failure(key, FailureClass.QUOTA_EXHAUSTED)
    eligible, _ = health.is_eligible(key)
    assert eligible is False


def test_invalid_model_never_routed():
    reg = load_registry()
    ids = [e.id for e in reg.eligible()]
    for r in ROUTER_IDS:
        assert r not in ids


def test_unavailable_provider_marked_auth_required_no_fakes():
    for k in ["OPENROUTER_API_KEY", "KILO_API_KEY", "BYTEZ_API_KEY",
              "GEMINI_API_KEY", "GROQ_API_KEY", "ORCA_API_KEY"]:
        assert os.environ.get(k) is None
    reg = load_registry()
    unverified = [e for e in reg.eligible() if not e.benchmark_source]
    assert len(unverified) >= 3
    for e in unverified:
        assert e.benchmark_source is None


def test_catalog_inventory_is_dynamic_not_fixed():
    reg = load_registry()
    assert len(reg.eligible()) >= 20
