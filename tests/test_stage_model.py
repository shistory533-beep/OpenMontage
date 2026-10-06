"""Canonical stage-model tests: one source of truth for factory stage IDs.

Covers the Part 2 unification contract:
  - stage consistency (Episode Store == envelope schema == manifest),
  - manifest gates == canonical APPROVAL_GATES,
  - invalid stage / prerequisite / transition rejected (fail closed),
  - resume across all 19 stages,
  - approval gates (publish blocked before human approval, analytics
    blocked before publish/export),
  - legacy migration (sources/facts/claims -> evidence, metadata ->
    packaging) with artifact preservation.
All offline (tmp_path projects dir, no network/providers).
"""

from __future__ import annotations

import pytest

from lib.episode_store import (
    ARTIFACT_SCHEMA_MAP,
    EpisodeStore,
    migrate_legacy_doc,
)
from lib.factory_stages import (
    APPROVAL_GATES,
    FACTORY_STAGES,
    ApprovalGateError,
    IllegalTransitionError,
    ManifestStageError,
    PrerequisiteViolationError,
    StageModelError,
    all_prerequisites,
    assert_prerequisites_met,
    prerequisites,
    requires_approval,
    validate_manifest_against_canonical,
    validate_transition,
)
from lib.pipeline_guard import (
    PrerequisiteError,
    PublishBlockedError,
    assert_stage_ready,
    next_pending,
)
from lib.pipeline_loader import get_stage_order, load_pipeline

CANONICAL = [
    "topic", "research", "evidence", "script", "fact_check",
    "storyboard", "narration", "footage", "footage_intelligence",
    "editorial", "timeline", "audio", "render", "qa",
    "packaging", "thumbnail", "human_review", "publish", "analytics",
]


def manifest():
    return load_pipeline("youtube-documentary")


def cp(status="completed", approved=True, artifacts=None):
    return {"status": status, "human_approved": approved,
            "artifacts": artifacts or {}}


# -- consistency: one source of truth -----------------------------------

def test_factory_stages_are_canonical_19():
    assert list(FACTORY_STAGES) == CANONICAL


def test_manifest_matches_canonical_exactly():
    m = manifest()
    validate_manifest_against_canonical(m)  # must not raise
    assert get_stage_order(m) == CANONICAL


def test_episode_store_covers_canonical_stages(tmp_path):
    doc = EpisodeStore("ep-sm-001", projects_dir=tmp_path).init("T")
    assert sorted(doc["stages"]) == sorted(CANONICAL)


def test_manifest_gates_match_canonical_approval_gates():
    m = manifest()
    manifest_gates = {s["name"] for s in m["stages"]
                      if s.get("human_approval_default", False)}
    assert manifest_gates == set(APPROVAL_GATES)


def test_artifact_schema_map_keys_are_canonical():
    assert set(ARTIFACT_SCHEMA_MAP) <= set(FACTORY_STAGES)


def test_manifest_validator_rejects_divergence():
    with pytest.raises(ManifestStageError):
        validate_manifest_against_canonical(
            {"name": "x", "stages": [{"name": "topic"}, {"name": "nope"}]})
    with pytest.raises(ManifestStageError):
        validate_manifest_against_canonical(
            {"name": "x", "stages": [{"name": "script"}, {"name": "topic"}]})
    with pytest.raises(ManifestStageError):
        validate_manifest_against_canonical(
            {"name": "x", "stages": [{"name": "topic"}, {"name": "topic"}]})


# -- invalid stage / prerequisite / transition ---------------------------

def test_invalid_stage_rejected_everywhere(tmp_path):
    with pytest.raises(IllegalTransitionError):
        validate_transition("metadata", "PENDING", "RUNNING")  # legacy ID
    with pytest.raises(IllegalTransitionError):
        validate_transition("sources", "PENDING", "RUNNING")  # legacy ID
    with pytest.raises(PrerequisiteViolationError):
        prerequisites("claims")
    with pytest.raises(PrerequisiteViolationError):
        assert_prerequisites_met({}, "producer")
    store = EpisodeStore("ep-sm-002", projects_dir=tmp_path)
    store.init("T")
    with pytest.raises(IllegalTransitionError):
        store.transition("metadata", "RUNNING")
    with pytest.raises(IllegalTransitionError):
        store.set_artifact("facts", {"items": []})


def test_invalid_prerequisite_blocks_start():
    # analytics requires the whole chain incl. publish DONE
    with pytest.raises(PrerequisiteViolationError):
        assert_prerequisites_met({}, "analytics")
    almost = {s: "DONE" for s in CANONICAL if s != "publish"}
    with pytest.raises(PrerequisiteViolationError) as e:
        assert_prerequisites_met(almost, "analytics")
    assert "publish" in str(e.value)
    # publish requires human_review DONE (approval handled separately)
    with pytest.raises(PrerequisiteViolationError):
        assert_prerequisites_met(
            {s: "DONE" for s in CANONICAL[:16]}, "publish")
    full = {s: "DONE" for s in CANONICAL}
    assert_prerequisites_met(full, "analytics")  # complete chain passes
    assert_prerequisites_met({}, "topic")  # entry stage: no prerequisites
    assert all_prerequisites("topic") == ()
    assert all_prerequisites("analytics") == tuple(CANONICAL[:-1])


def test_invalid_transition_rejected(tmp_path):
    with pytest.raises(IllegalTransitionError):
        validate_transition("publish", "PENDING", "DONE")  # skip
    with pytest.raises(IllegalTransitionError):
        validate_transition("publish", "DONE", "APPROVED")  # terminal
    with pytest.raises(IllegalTransitionError):
        validate_transition("analytics", "PENDING", "APPROVED")
    store = EpisodeStore("ep-sm-003", projects_dir=tmp_path)
    store.init("T")
    store.transition("research", "RUNNING")
    # research is ungated: RUNNING -> DONE directly is legal...
    doc = store.transition("research", "DONE")
    assert doc["stages"]["research"]["state"] == "DONE"
    # ...but DONE is terminal: DONE -> APPROVED is rejected.
    with pytest.raises(IllegalTransitionError):
        store.transition("research", "APPROVED")


def test_ungated_running_to_done_is_legal_but_gated_is_not(tmp_path):
    store = EpisodeStore("ep-sm-004", projects_dir=tmp_path)
    store.init("T")
    # research is ungated: RUNNING -> DONE directly is legal
    store.transition("research", "RUNNING")
    doc = store.transition("research", "DONE")
    assert doc["stages"]["research"]["state"] == "DONE"
    # script is gated: RUNNING -> DONE without APPROVED is blocked
    store.transition("script", "RUNNING")
    with pytest.raises(ApprovalGateError):
        store.transition("script", "DONE")


# -- approval gates -------------------------------------------------------

def test_approval_gate_on_every_gated_stage(tmp_path):
    for stage in sorted(APPROVAL_GATES):
        store = EpisodeStore(f"ep-gate-{stage}", projects_dir=tmp_path)
        store.init("T")
        assert requires_approval(stage) is True
        store.transition(stage, "RUNNING")
        with pytest.raises(ApprovalGateError):
            store.transition(stage, "DONE")
        store.transition(stage, "REVIEW")
        store.transition(stage, "APPROVED")
        doc = store.transition(stage, "DONE")
        assert doc["stages"][stage]["state"] == "DONE"


def test_rework_clears_approval(tmp_path):
    store = EpisodeStore("ep-sm-005", projects_dir=tmp_path)
    store.init("T")
    store.transition("script", "RUNNING")
    store.transition("script", "APPROVED")
    store.transition("script", "RUNNING")  # reopen for rework
    with pytest.raises(ApprovalGateError):
        store.transition("script", "DONE")  # stale approval must not carry
    store.transition("script", "APPROVED")
    store.transition("script", "DONE")  # fresh approval works


def test_publish_blocked_before_human_approval_store_level(tmp_path):
    store = EpisodeStore("ep-sm-006", projects_dir=tmp_path)
    store.init("T")
    store.transition("publish", "RUNNING")
    with pytest.raises(ApprovalGateError):
        store.transition("publish", "DONE")


def test_publish_and_analytics_gates_guard_level():
    m = manifest()
    arts = {
        "topic": cp(artifacts={"brief": {}}),
        "research": cp(artifacts={"research_brief": {}}),
        "evidence": cp(artifacts={"evidence_bundle": {}}),
        "script": cp(artifacts={"script": {}}),
        "fact_check": cp(artifacts={"factcheck_report": {}}),
        "storyboard": cp(artifacts={"scene_plan": {}}),
        "narration": cp(artifacts={"narration_manifest": {}}),
        "footage": cp(artifacts={"asset_manifest": {}}),
        "footage_intelligence": cp(artifacts={"footage_report": {}}),
        "editorial": cp(artifacts={"edit_decisions": {}}),
        "timeline": cp(artifacts={"edit_decisions": {}}),
        "audio": cp(artifacts={"audio_mix": {}}),
        "render": cp(artifacts={"render_report": {}}),
        "qa": cp(artifacts={"final_review": {}}),
        "packaging": cp(artifacts={"package_bundle": {}}),
        "thumbnail": cp(artifacts={"thumbnail_set": {}}),
        "human_review": cp(artifacts={"review_decision": {}}),
        "publish": cp(artifacts={"publish_log": {}}),
    }
    # publish blocked while human_review is missing/unapproved
    with pytest.raises(PublishBlockedError):
        assert_stage_ready(m, "publish",
                            {k: v for k, v in arts.items()
                             if k != "human_review"})
    # analytics blocked before publish/export
    with pytest.raises(PrerequisiteError):
        assert_stage_ready(m, "analytics",
                            {k: v for k, v in arts.items()
                             if k != "publish"})
    # full chain incl. approved human_review + publish -> analytics ready
    assert_stage_ready(m, "analytics", arts)


# -- resume -----------------------------------------------------------------

def test_resume_pointer_walks_all_19_stages():
    m = manifest()
    cps: dict = {}
    assert next_pending(m, cps) == "topic"
    order = get_stage_order(m)
    assert len(order) == 19
    for i, stage in enumerate(order):
        cps[stage] = cp()
        expected = order[i + 1] if i + 1 < len(order) else None
        assert next_pending(m, cps) == expected, stage


def test_store_resume_after_crash_mid_chain(tmp_path):
    store = EpisodeStore("ep-sm-007", projects_dir=tmp_path)
    store.init("T")
    for stage in CANONICAL[:CANONICAL.index("footage")]:
        store.transition(stage, "RUNNING")
        # Transitions never require artifacts; only write payloads where no
        # canonical schema applies (schema stages stay payload-free here).
        if stage not in ARTIFACT_SCHEMA_MAP:
            store.set_artifact(stage, {"note": stage})
        if stage in APPROVAL_GATES:
            store.transition(stage, "REVIEW")
            store.transition(stage, "APPROVED")
        store.transition(stage, "DONE")
    store.transition("footage", "RUNNING")  # crash here
    resumed = EpisodeStore("ep-sm-007", projects_dir=tmp_path)
    status = resumed.status()
    assert status["footage"] == "RUNNING"
    assert status["evidence"] == "DONE"
    assert status["analytics"] == "PENDING"


# -- migration ----------------------------------------------------------------

def _legacy_stage(state="DONE", version=1, artifact=None):
    return {"state": state, "artifact_version": version,
            "artifact": artifact or {}, "failure_reason": None,
            "provider": None, "started_at": "2026-10-05T00:00:00+00:00",
            "updated_at": "2026-10-05T00:00:00+00:00",
            "reviewed_at": None, "approved_at": None, "done_at": None}


def _legacy_doc():
    stages = {}
    for name in ("topic", "research", "sources", "facts", "claims", "script",
                 "fact_check", "storyboard", "narration", "footage",
                 "editorial", "timeline", "audio", "render", "qa",
                 "thumbnail", "metadata", "publish", "analytics"):
        stages[name] = _legacy_stage()
    return {"version": "1.0", "episode_id": "ep-legacy", "title": "L",
            "pipeline_type": "youtube-documentary",
            "created_at": "2026-10-05T00:00:00+00:00",
            "updated_at": "2026-10-05T00:00:00+00:00",
            "stages": stages}


def test_migration_maps_legacy_ids_and_validates():
    doc = _legacy_doc()
    doc["stages"]["sources"]["artifact"] = {"items": ["s1"]}
    doc["stages"]["facts"]["artifact"] = {"items": ["f1"]}
    doc["stages"]["claims"]["artifact"] = {"items": ["c1"]}
    doc["stages"]["metadata"]["artifact"] = {"title": "yt title"}
    out = migrate_legacy_doc(doc)
    assert sorted(out["stages"]) == sorted(CANONICAL)
    ev = out["stages"]["evidence"]
    assert ev["state"] == "DONE"
    assert ev["artifact"] == {"sources": {"items": ["s1"]},
                              "facts": {"items": ["f1"]},
                              "claims": {"items": ["c1"]}}
    assert ev["artifact_version"] == 1
    assert out["stages"]["packaging"]["artifact"] == {"title": "yt title"}
    # gated DONE stages get an approval backfill (pre-gate docs lack stamps)
    assert out["stages"]["publish"]["approved_at"]
    # stages with no legacy equivalent start blank
    assert out["stages"]["footage_intelligence"]["state"] == "PENDING"
    assert out["stages"]["human_review"]["state"] == "PENDING"
    # result validates against the canonical envelope
    store_check = EpisodeStore("ep-legacy", projects_dir=None)
    store_check.validate(out)


def test_migration_is_conservative_on_partial_evidence():
    doc = _legacy_doc()
    doc["stages"]["sources"]["state"] = "DONE"
    doc["stages"]["facts"]["state"] = "RUNNING"
    doc["stages"]["claims"]["state"] = "PENDING"
    out = migrate_legacy_doc(doc)
    assert out["stages"]["evidence"]["state"] == "PENDING"  # never over-claim
    assert out["stages"]["evidence"]["done_at"] is None


def test_migration_preserves_failure():
    doc = _legacy_doc()
    doc["stages"]["facts"]["state"] = "FAILED"
    doc["stages"]["facts"]["failure_reason"] = "archive timeout"
    out = migrate_legacy_doc(doc)
    ev = out["stages"]["evidence"]
    assert ev["state"] == "FAILED"
    assert "archive timeout" in (ev["failure_reason"] or "")


def test_migration_rejects_unknown_stages():
    doc = _legacy_doc()
    doc["stages"]["hacker"] = _legacy_stage()
    with pytest.raises(StageModelError):
        migrate_legacy_doc(doc)


def test_migration_idempotent_on_canonical(tmp_path):
    store = EpisodeStore("ep-sm-008", projects_dir=tmp_path)
    canonical = store.init("T")
    out = migrate_legacy_doc(canonical)
    assert sorted(out["stages"]) == sorted(CANONICAL)
    store.validate(out)
