"""Producer orchestrator tests: plan, run, resume, retry, gates, halt.

All offline: fake stage handlers stand in for services. Real-service
wiring is covered by test_producer_e2e.py.
"""

from __future__ import annotations

import json

import pytest

from lib.producer.contracts import PRODUCER_STAGES
from lib.producer.producer import (
    MissingStageInput,
    ProducerAgent,
    ProducerHalted,
)
from tests.test_youtube_documentary_integration import (
    BRIEF,
    EDIT,
    EVIDENCE,
    FACTCHECK,
    MANIFEST_ART,
    QA,
    REPORT,
    RESEARCH,
    SCENES,
    SCRIPT,
)

_VALID = {
    "topic": {"brief": BRIEF},
    "research": {"research_brief": RESEARCH},
    "evidence": {"evidence_bundle": EVIDENCE},
    "script": {"script": SCRIPT},
    "fact_check": {"factcheck_report": FACTCHECK},
    "storyboard": {"scene_plan": SCENES},
    "narration": {"narration_manifest": {"version": "1.0", "tracks": 1,
        "sections": [{"section_id": "s1", "asset_id": "narr_s1",
                       "duration_seconds": 600, "path": "narr_s1.wav",
                       "checksum": "sha256:" + "a" * 64,
                       "voice": "af_heart", "provider": "kokoro"}]}},
    "footage": {"asset_manifest": MANIFEST_ART},
    "footage_intelligence": {"footage_report": {"version": "1.0",
                                                 "verdicts": []}},
    "editorial": {"edit_decisions": EDIT},
    "timeline": {"edit_decisions": EDIT},
    "audio": {"audio_mix": {"version": "1.0", "mix_path": "mix.wav",
                             "duration_seconds": 600.0,
                             "loudness_db": -14.0,
                             "true_peak_dbtp": -1.5,
                             "loudness_measured": False}},
    "render": {"render_report": REPORT},
    "qa": {"final_review": QA},
    "packaging": {"package_bundle": {"version": "1.0",
        "titles": {"candidates": [
            {"title": f"Title {i}", "scores": {"clarity": 1.0},
             "final_score": 0.8, "misleading_risk": 0.0, "accepted": True}
            for i in range(5)]},
        "chosen_title": "Title 0", "description": "d",
        "chapters": [], "tags": {}, "subtitles": {},
        "thumbnail": {"focal_subject": "river", "composition": "center",
                      "text": "river", "contrast": "high",
                      "visual_concept": "establishing", "reason": "fits"}}},
    "thumbnail": {"thumbnail_set": {"concept": "c"}},
    "human_review": {"review_decision": {"decision": "APPROVED",
        "approver": "tester", "rationale": "ok",
        "timestamp": "2026-10-06T00:00:00+00:00",
        "episode_id": "ep-prod-001"}},
}


def _fake_handlers(payloads=None):
    payloads = payloads or _VALID

    def make(artifacts):
        def run(ctx):
            return dict(artifacts)
        return run
    return {stage: make(arts)
            for stage, arts in payloads.items()
            if stage in PRODUCER_STAGES}


def _manifest_names():
    from lib.pipeline_loader import get_stage_order, load_pipeline
    return get_stage_order(load_pipeline("youtube-documentary"))


def _producer(tmp_path, **kw):
    return ProducerAgent("ep-prod-001", projects_dir=tmp_path,
                         handlers=_fake_handlers(), **kw)


# -- scope -----------------------------------------------------------------


def test_producer_covers_manifest_up_to_human_review():
    assert list(PRODUCER_STAGES) == _manifest_names()[:-2]
    assert "publish" not in PRODUCER_STAGES
    assert "analytics" not in PRODUCER_STAGES


def test_dry_run_plans_without_writing(tmp_path):
    producer = _producer(tmp_path)
    plan = producer.plan()
    assert [p["stage"] for p in plan] == list(PRODUCER_STAGES)
    assert all(not p["will_skip"] for p in plan)
    assert not (tmp_path / "ep-prod-001").exists()


def test_start_stop_scoping(tmp_path):
    producer = _producer(tmp_path, start_from="script",
                         stop_after="storyboard")
    assert [p["stage"] for p in producer.plan()] == [
        "script", "fact_check", "storyboard"]


def test_unknown_scope_rejected(tmp_path):
    with pytest.raises(Exception):
        _producer(tmp_path, start_from="nope")


# -- run / resume / retry ----------------------------------------------------


def test_full_run_skips_nothing_when_fresh(tmp_path):
    approvals = {s: True for s in PRODUCER_STAGES}
    producer = _producer(tmp_path, approvals=approvals)
    report = producer.run()
    assert report["failed"] is None and report["awaiting_human"] is None
    assert report["completed"] == list(PRODUCER_STAGES)
    status = producer.store.status()
    assert all(status[s] == "DONE" for s in PRODUCER_STAGES)
    kinds = [e["kind"] for e in producer.events()]
    assert "run_started" in kinds and "run_finished" in kinds


def test_resume_skips_done_stages(tmp_path):
    approvals = {s: True for s in PRODUCER_STAGES}
    first = _producer(tmp_path, approvals=approvals,
                      stop_after="evidence")
    first.run()
    calls = []

    def counting(stage, artifacts):
        def run(ctx):
            calls.append(stage)
            return dict(artifacts)
        return run
    handlers = {stage: counting(stage, arts)
                for stage, arts in _VALID.items()}
    second = ProducerAgent("ep-prod-001", projects_dir=tmp_path,
                           handlers=handlers, approvals=approvals)
    report = second.run()
    assert "topic" not in calls and "research" not in calls
    assert "evidence" not in calls  # DONE is skipped, not re-run
    assert report["completed"] == list(PRODUCER_STAGES)


def test_retry_failed_stage(tmp_path):
    approvals = {s: True for s in PRODUCER_STAGES}
    attempts = {"n": 0}

    def flaky(ctx):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient boom")
        return {"research_brief": RESEARCH}

    producer = _producer(tmp_path, approvals=approvals,
                         stop_after="research")
    producer.handlers["research"] = flaky
    with pytest.raises(ProducerHalted):
        producer.run()
    assert producer.store.status()["research"] == "FAILED"
    report = producer.retry_failed()
    assert report["completed"] == ["topic", "research"]
    assert producer.store.status()["research"] == "DONE"
    kinds = [e["kind"] for e in producer.events()]
    assert "retry_started" in kinds and "stage_failed" in kinds


def test_critical_failure_halts_without_downstream(tmp_path):
    approvals = {s: True for s in PRODUCER_STAGES}
    ran = []

    def boom(ctx):
        ran.append(ctx.stage)
        raise RuntimeError("critical: fact source vanished")

    def record(ctx):
        ran.append(ctx.stage)
        return {"factcheck_report": FACTCHECK}

    producer = _producer(tmp_path, approvals=approvals,
                         stop_after="storyboard")
    producer.handlers["fact_check"] = boom
    producer.handlers["storyboard"] = record
    with pytest.raises(ProducerHalted) as exc:
        producer.run()
    assert "fact_check" in str(exc.value)
    assert "storyboard" not in ran  # never silently continued
    assert producer.store.status()["fact_check"] == "FAILED"
    reason = producer.store.load()["stages"]["fact_check"][
        "failure_reason"]
    assert "fact source vanished" in reason


def test_missing_stage_input_is_a_clean_failure(tmp_path):
    from lib.producer import runners

    def needy(ctx):
        raise MissingStageInput("no payload supplied")

    producer = _producer(tmp_path, approvals={"topic": True},
                         stop_after="topic")
    producer.handlers["topic"] = needy
    with pytest.raises(ProducerHalted):
        producer.run()
    assert producer.store.status()["topic"] == "FAILED"


# -- gates -------------------------------------------------------------------


def test_gated_stage_waits_for_human(tmp_path):
    producer = _producer(tmp_path, stop_after="topic")  # topic is gated
    report = producer.run()
    assert report["awaiting_human"] == "topic"
    assert report["completed"] == []
    assert producer.store.status()["topic"] == "REVIEW"
    # explicit approval unblocks the resume
    producer.record_approval("topic", True)
    report2 = producer.run()
    assert report2["completed"] == ["topic"]
    assert producer.store.status()["topic"] == "DONE"


def test_prerequisite_violation_fails_closed(tmp_path):
    # topic DONE but research skipped: evidence must not run.
    approvals = {s: True for s in PRODUCER_STAGES}
    producer = _producer(tmp_path, approvals=approvals,
                         start_from="evidence", stop_after="evidence")
    producer.store.init("t")
    producer.store.transition("topic", "RUNNING")
    producer.store.set_artifact("topic", BRIEF)
    producer.store.transition("topic", "APPROVED")
    producer.store.transition("topic", "DONE")
    with pytest.raises(ProducerHalted) as exc:
        producer.run()
    assert "prerequisites" in str(exc.value).lower()


def test_inspect_reports_status(tmp_path):
    producer = _producer(tmp_path, approvals={"topic": True},
                         stop_after="topic")
    producer.run()
    view = producer.inspect()
    assert view["episode_id"] == "ep-prod-001"
    assert view["stages"]["topic"]["state"] == "DONE"
    assert view["checkpoints"]["topic"]["status"] == "completed"
    assert view["next_stage"] is None  # scoped run finished its stages
    assert view["event_count"] > 0


def test_narration_transcript_built_from_tts_alignment(tmp_path):
    import json

    from lib.producer.producer import StageContext
    from lib.producer.runners import _narration_transcript_path

    ctx = StageContext(
        episode_id="ep-prod-001", stage="render",
        inputs={"narration_manifest": {"sections": [
            {"section_id": "s1", "duration_seconds": 2.0,
             "text": "Rivers carve canyons.",
             "alignment": [
                 {"text": "Rivers carve canyons.",
                  "start_seconds": 0.0, "end_seconds": 2.0}]},
        ]}},
        workdir=tmp_path / "ep-prod-001")
    path = _narration_transcript_path(ctx)
    assert path is not None and path.exists()
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["source"] == "tts_alignment"
    tokens = [w["word"] for w in doc["word_timestamps"]]
    assert tokens == ["Rivers", "carve", "canyons."]


def test_narration_transcript_absent_without_stems(tmp_path):
    from lib.producer.producer import StageContext
    from lib.producer.runners import _narration_transcript_path

    ctx = StageContext(
        episode_id="ep-prod-001", stage="render",
        inputs={"narration_manifest": {"sections": []}},
        workdir=tmp_path / "ep-prod-001")
    assert _narration_transcript_path(ctx) is None
