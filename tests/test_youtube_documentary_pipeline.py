"""Unit tests: youtube-documentary manifest + pipeline guard (offline)."""
from __future__ import annotations

import pytest

from lib.pipeline_guard import (
    PrerequisiteError,
    PublishBlockedError,
    assert_stage_ready,
    next_pending,
    predecessors,
    stage_names,
    validate_sequence,
)
from lib.pipeline_loader import get_stage_order, load_pipeline

EXPECTED_ORDER = ["topic", "research", "evidence", "script", "fact_check",
                  "storyboard", "narration", "footage",
                  "footage_intelligence", "editorial", "timeline", "audio",
                  "render", "qa", "packaging", "thumbnail", "human_review",
                  "publish", "analytics"]


def manifest():
    return load_pipeline("youtube-documentary")


def cp(status="completed", approved=True, artifacts=None):
    return {"status": status, "human_approved": approved,
            "artifacts": artifacts or {}}


# -- manifest shape --------------------------------------------------------

def test_manifest_loads_and_is_schema_valid():
    m = manifest()
    assert m["name"] == "youtube-documentary"
    assert m["category"] == "documentary"


def test_stage_order_is_deterministic_and_exact():
    m = manifest()
    assert get_stage_order(m) == EXPECTED_ORDER
    assert stage_names(m) == EXPECTED_ORDER


def test_binding_gates():
    m = manifest()
    gates = {s["name"]: bool(s.get("human_approval_default", False))
             for s in m["stages"]}
    for stage in ("topic", "script", "storyboard", "footage",
                  "human_review", "publish"):
        assert gates[stage] is True, stage
    for stage in ("research", "fact_check", "editorial", "render", "qa"):
        assert gates[stage] is False, stage


def test_no_generative_video_tools_in_footage_stage():
    m = manifest()
    footage = next(s for s in m["stages"] if s["name"] == "footage")
    tools = set(footage.get("tools_available", []))
    assert tools <= {"footage_hub", "direct_clip_search", "corpus_builder",
                     "clip_search"}


# -- guard: readiness -------------------------------------------------------

def full_chain(extra=None):
    cps = {
        "topic": cp(artifacts={"brief": {}}),
        "research": cp(artifacts={"research_brief": {}}),
        "evidence": cp(artifacts={"evidence_bundle": {}}, approved=False),
        "script": cp(artifacts={"script": {}}),
        "fact_check": cp(artifacts={"factcheck_report": {}}, approved=False),
        "storyboard": cp(artifacts={"scene_plan": {}}),
        "narration": cp(artifacts={"narration_manifest": {}}, approved=False),
        "footage": cp(artifacts={"asset_manifest": {}}),
        "footage_intelligence": cp(artifacts={"footage_report": {}},
                                   approved=False),
        "editorial": cp(artifacts={"edit_decisions": {}}),
        "timeline": cp(artifacts={"edit_decisions": {}}),
        "audio": cp(artifacts={"audio_mix": {}}, approved=False),
        "render": cp(artifacts={"render_report": {}}, approved=False),
        "qa": cp(artifacts={"final_review": {}}, approved=False),
        "packaging": cp(artifacts={"package_bundle": {}}, approved=False),
        "thumbnail": cp(artifacts={"thumbnail_set": {}}, approved=False),
        "human_review": cp(artifacts={"review_decision": {}}),
    }
    if extra:
        cps.update(extra)
    return cps


def test_valid_pipeline_all_stages_ready_in_sequence():
    m = manifest()
    cps = dict(full_chain())
    cps["publish"] = cp(artifacts={"publish_log": {}})
    validate_sequence(m, EXPECTED_ORDER)  # canonical order is legal
    for stage in EXPECTED_ORDER[1:]:
        prior = {k: v for k, v in cps.items()
                 if EXPECTED_ORDER.index(k) < EXPECTED_ORDER.index(stage)}
        assert_stage_ready(m, stage, prior)


def test_missing_prerequisite_fails_closed():
    m = manifest()
    with pytest.raises(PrerequisiteError):
        assert_stage_ready(m, "script", {})  # research never completed
    cps = {"topic": cp(artifacts={"brief": {}})}
    with pytest.raises(PrerequisiteError):
        assert_stage_ready(m, "storyboard", cps)  # script + factcheck absent


def test_missing_artifact_fails_closed():
    m = manifest()
    cps = {"topic": cp(artifacts={"brief": {}}),
           "research": cp(artifacts={})}  # completed but empty: brief chain ok,
    # script needs research_brief artifact specifically
    with pytest.raises(PrerequisiteError) as e:
        assert_stage_ready(m, "script", cps)
    assert "research_brief" in str(e.value)


def test_unapproved_gate_blocks_successor():
    m = manifest()
    cps = {"topic": cp(artifacts={"brief": {}}, approved=False)}
    with pytest.raises(PrerequisiteError) as e:
        assert_stage_ready(m, "research", cps)
    assert "approval" in str(e.value)


def test_invalid_stage_order_rejected():
    m = manifest()
    with pytest.raises(PrerequisiteError):
        validate_sequence(m, ["research", "topic"])
    with pytest.raises(PrerequisiteError):
        validate_sequence(m, ["topic", "render"])
    with pytest.raises(PrerequisiteError):
        validate_sequence(m, ["topic", "nope"])


def test_predecessors_helper():
    m = manifest()
    assert predecessors(m, "topic") == []
    assert predecessors(m, "evidence") == ["topic", "research"]
    assert predecessors(m, "publish") == [s for s in EXPECTED_ORDER
                                          if s not in ("publish", "analytics")]
    assert predecessors(m, "analytics") == EXPECTED_ORDER[:-1]
    with pytest.raises(PrerequisiteError):
        predecessors(m, "producer")  # explicitly out of scope


def test_publish_blocked_before_human_approval():
    m = manifest()
    cps = {k: v for k, v in full_chain().items() if k != "human_review"}
    with pytest.raises(PublishBlockedError):
        assert_stage_ready(m, "publish", cps)  # human_review not run yet
    cps["human_review"] = cp(artifacts={"review_decision": {}}, approved=False)
    with pytest.raises(PublishBlockedError):
        assert_stage_ready(m, "publish", cps)  # completed but not approved
    cps["human_review"] = cp(artifacts={"review_decision": {}})
    assert_stage_ready(m, "publish", cps)  # APPROVED -> allowed


def test_next_pending_resume_pointer():
    m = manifest()
    assert next_pending(m, {}) == "topic"
    cps = {"topic": cp(artifacts={"brief": {}}),
           "research": cp(artifacts={"research_brief": {}})}
    assert next_pending(m, cps) == "evidence"
    assert next_pending(m, full_chain()) == "publish"
