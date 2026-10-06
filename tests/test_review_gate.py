"""Human review gate tests: explicit append-only approval, publish lock."""

from __future__ import annotations

import json

import pytest

from lib.producer.review import (
    assemble_review_package,
    assert_publish_allowed,
    latest_decision,
    mark_ready_for_review,
    read_decisions,
    record_decision,
)


def _package(tmp_path, **over):
    pkg = {"version": "1.0", "episode_id": "ep-rev-001",
           "video_path": str(tmp_path / "final.mp4"),
           "script": {"sections": [{"id": "s1"}]},
           "qa_report": {"verdict": "PASS", "readiness": "READY"}}
    pkg.update(over)
    return pkg


def test_ready_for_review_package_complete(tmp_path):
    pkg = assemble_review_package(
        episode_id="ep-rev-001",
        video_path=str(tmp_path / "final.mp4"),
        script={"sections": [{"id": "s1"}]},
        storyboard={"requirements": []},
        picks=[{"asset_id": "clip-1"}],
        qa_report={"verdict": "PASS"},
        rights_summary={"mode": "strict"},
        narration_status={"section_count": 1},
        titles=[{"title": "Rivers"}],
        thumbnail={"concept": "canyon"},
        description="A film about rivers.",
        chapters=[{"chapter_id": "ch1", "start": "0:00"}],
        subtitles_path=str(tmp_path / "subs.srt"))
    assert pkg["status"] == "READY_FOR_REVIEW"
    for key in ("script", "storyboard", "selected_footage", "qa_report",
                "rights_summary", "narration_status", "title_candidates",
                "thumbnail", "description", "chapters", "subtitles_path"):
        assert key in pkg, key
    from schemas.artifacts import validate_artifact
    validate_artifact("review_package", pkg)


def test_incomplete_package_refused(tmp_path):
    with pytest.raises(Exception):
        assemble_review_package(episode_id="ep-rev-001", video_path="",
                                script={}, qa_report={})


def test_approval_requires_identity_and_rationale(tmp_path):
    mark_ready_for_review(tmp_path, "ep-rev-001")
    with pytest.raises(Exception):
        record_decision(tmp_path, episode_id="ep-rev-001",
                        decision="APPROVED", approver="",
                        rationale="looks good")
    with pytest.raises(Exception):
        record_decision(tmp_path, episode_id="ep-rev-001",
                        decision="APPROVED", approver="ada",
                        rationale="")
    entry = record_decision(tmp_path, episode_id="ep-rev-001",
                            decision="APPROVED", approver="ada",
                            rationale="QA passed, footage licensed.")
    assert entry.timestamp and entry.decision == "APPROVED"
    from schemas.artifacts import validate_artifact
    validate_artifact("review_decision", entry.to_dict())


def test_approval_before_review_refused(tmp_path):
    with pytest.raises(Exception) as exc:
        record_decision(tmp_path, episode_id="ep-rev-001",
                        decision="APPROVED", approver="ada",
                        rationale="skipping ahead")
    assert "READY_FOR_REVIEW" in str(exc.value)


def test_decisions_append_only(tmp_path):
    mark_ready_for_review(tmp_path, "ep-rev-001")
    record_decision(tmp_path, episode_id="ep-rev-001",
                    decision="CHANGES_REQUESTED", approver="ada",
                    rationale="tighten the opening")
    record_decision(tmp_path, episode_id="ep-rev-001",
                    decision="APPROVED", approver="ada",
                    rationale="opening fixed")
    decisions = read_decisions(tmp_path)
    assert [d.decision for d in decisions] == [
        "READY_FOR_REVIEW", "CHANGES_REQUESTED", "APPROVED"]
    assert latest_decision(tmp_path).decision == "APPROVED"


def test_rejection_recorded_with_reasons(tmp_path):
    mark_ready_for_review(tmp_path, "ep-rev-001")
    entry = record_decision(tmp_path, episode_id="ep-rev-001",
                            decision="REJECTED", approver="ada",
                            rationale="wrong river entirely")
    assert entry.decision == "REJECTED"
    with pytest.raises(Exception):
        assert_publish_allowed(tmp_path)


def test_publish_impossible_without_approval(tmp_path):
    with pytest.raises(Exception):
        assert_publish_allowed(tmp_path)
    mark_ready_for_review(tmp_path, "ep-rev-001")
    with pytest.raises(Exception):
        assert_publish_allowed(tmp_path)
    record_decision(tmp_path, episode_id="ep-rev-001",
                    decision="APPROVED", approver="ada",
                    rationale="good to go")
    allowed = assert_publish_allowed(tmp_path)
    assert allowed.decision == "APPROVED"


def test_unknown_decision_rejected(tmp_path):
    with pytest.raises(Exception):
        record_decision(tmp_path, episode_id="ep-rev-001",
                        decision="MAYBE", approver="ada",
                        rationale="unsure")
