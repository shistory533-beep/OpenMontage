"""Unit tests for the additive factory state layer.

Covers: stage enumeration, deterministic transitions, schema validation,
versioned artifacts, failure reasons, timestamps, provider-agnosticism,
non-destructive history. All offline (tmp_path projects dir).
"""

from __future__ import annotations

import json

import pytest

from lib.episode_store import ARTIFACT_SCHEMA_MAP, EpisodeStore
from lib.factory_stages import (
    FACTORY_STAGES,
    STAGE_STATES,
    IllegalTransitionError,
    allowed_targets,
    validate_transition,
)

EXPECTED_STAGES = [
    "topic", "research", "evidence", "script",
    "fact_check", "storyboard", "narration", "footage",
    "footage_intelligence", "editorial",
    "timeline", "audio", "render", "qa", "packaging", "thumbnail",
    "human_review", "publish", "analytics",
]


def make_store(tmp_path, episode_id="ep-unit-001"):
    return EpisodeStore(episode_id, projects_dir=tmp_path)


# -- stage machine ----------------------------------------------------

def test_factory_stages_cover_episode_package_domains():
    assert list(FACTORY_STAGES) == EXPECTED_STAGES


def test_stage_states_cover_required_lifecycle():
    for s in ("PENDING", "RUNNING", "REVIEW", "APPROVED", "DONE", "FAILED"):
        assert s in STAGE_STATES


def test_legal_transitions_pass():
    validate_transition("script", "PENDING", "RUNNING")
    validate_transition("script", "RUNNING", "REVIEW")
    validate_transition("script", "REVIEW", "APPROVED")
    validate_transition("script", "APPROVED", "DONE")
    validate_transition("script", "RUNNING", "FAILED")
    validate_transition("script", "FAILED", "RUNNING")
    validate_transition("script", "DONE", "RUNNING")  # explicit reopen
    validate_transition("script", "RUNNING", "RUNNING")  # heartbeat


def test_illegal_transitions_raise():
    with pytest.raises(IllegalTransitionError):
        validate_transition("script", "PENDING", "DONE")  # skip
    with pytest.raises(IllegalTransitionError):
        validate_transition("script", "PENDING", "APPROVED")
    with pytest.raises(IllegalTransitionError):
        validate_transition("script", "DONE", "APPROVED")  # terminal
    with pytest.raises(IllegalTransitionError):
        validate_transition("nope", "PENDING", "RUNNING")


def test_allowed_targets_is_deterministic():
    assert allowed_targets("PENDING") == ["RUNNING"]
    assert allowed_targets("PENDING") == allowed_targets("PENDING")


# -- persistence ------------------------------------------------------

def test_init_creates_all_pending_with_timestamps(tmp_path):
    doc = make_store(tmp_path).init("Unit Episode")
    assert doc["version"] == "1.0"
    assert doc["pipeline_type"] == "youtube-documentary"
    assert set(doc["stages"]) == set(EXPECTED_STAGES)
    for name, st in doc["stages"].items():
        assert st["state"] == "PENDING", name
        assert st["artifact_version"] == 0
        assert st["updated_at"]
    assert doc["created_at"] and doc["updated_at"]


def test_init_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    first = store.init("T")
    second = store.init("T")
    assert first == second


def test_transition_sets_timestamps(tmp_path):
    store = make_store(tmp_path)
    store.init("T")
    doc = store.transition("topic", "RUNNING")
    assert doc["stages"]["topic"]["state"] == "RUNNING"
    assert doc["stages"]["topic"]["started_at"]
    doc = store.transition("topic", "REVIEW")
    assert doc["stages"]["topic"]["reviewed_at"]
    doc = store.transition("topic", "APPROVED")
    assert doc["stages"]["topic"]["approved_at"]
    from tests.test_youtube_documentary_integration import BRIEF
    store.set_artifact("topic", BRIEF)
    doc = store.transition("topic", "DONE")
    assert doc["stages"]["topic"]["done_at"]


def test_failed_requires_reason_and_keeps_it(tmp_path):
    store = make_store(tmp_path)
    store.init("T")
    store.transition("research", "RUNNING")
    with pytest.raises(ValueError):
        store.transition("research", "FAILED")  # no reason
    doc = store.fail("research", "archive.org timeout")
    assert doc["stages"]["research"]["state"] == "FAILED"
    assert doc["stages"]["research"]["failure_reason"] == "archive.org timeout"
    # retry clears the reason
    doc = store.transition("research", "RUNNING")
    assert doc["stages"]["research"]["failure_reason"] is None


def test_set_artifact_versions_and_validates_known_schema(tmp_path):
    store = make_store(tmp_path)
    store.init("T")
    script = {
        "version": "1.0",
        "title": "T",
        "total_duration_seconds": 60,
        "sections": [{"id": "s1", "text": "hello", "start_seconds": 0, "end_seconds": 60}],
    }
    doc = store.set_artifact("script", script, provider="piper")
    assert doc["stages"]["script"]["artifact_version"] == 1
    assert doc["stages"]["script"]["provider"] == "piper"  # label only
    doc = store.set_artifact("script", script)
    assert doc["stages"]["script"]["artifact_version"] == 2


def test_set_artifact_rejects_invalid_known_schema(tmp_path):
    store = make_store(tmp_path)
    store.init("T")
    with pytest.raises(Exception):
        store.set_artifact("script", {"bogus": True})


def test_provider_agnostic_custom_payload(tmp_path):
    from tests.test_youtube_documentary_integration import EVIDENCE
    store = make_store(tmp_path)  # 'evidence' maps to evidence_bundle
    store.init("T")
    assert ARTIFACT_SCHEMA_MAP["evidence"] == "evidence_bundle"
    doc = store.set_artifact("evidence", EVIDENCE)
    assert doc["stages"]["evidence"]["artifact_version"] == 1
    with pytest.raises(Exception):
        store.set_artifact("evidence", {"bogus": True})


def test_history_is_append_only(tmp_path):
    store = make_store(tmp_path)
    store.init("T")
    store.transition("topic", "RUNNING")
    store.transition("topic", "REVIEW")
    hist = list((tmp_path / "ep-unit-001" / "history").glob("episode_*.json"))
    assert len(hist) >= 2  # one archive per mutation, never deleted
    # latest history entry parses as JSON (no destructive truncation)
    for h in hist:
        assert json.loads(h.read_text(encoding="utf-8"))["episode_id"] == "ep-unit-001"


def test_envelope_rejects_unknown_stage(tmp_path):
    store = make_store(tmp_path)
    doc = store.init("T")
    doc["stages"]["hacker"] = doc["stages"]["topic"]
    with pytest.raises(Exception):
        store.validate(doc)
