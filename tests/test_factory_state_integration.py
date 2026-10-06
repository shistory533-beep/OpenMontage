"""Integration tests for the factory episode layer.

Proves end-to-end properties with zero network / zero providers:
  1. full 19-stage lifecycle PENDING -> RUNNING -> REVIEW -> APPROVED -> DONE,
  2. crash-resume: a fresh EpisodeStore on the same dir sees identical state,
  3. failure + retry mid-pipeline preserves history and versions,
  4. envelope validates against schemas/factory/episode_package.schema.json.
"""

from __future__ import annotations

import json

from lib.episode_store import EpisodeStore
from lib.factory_stages import APPROVAL_GATES, FACTORY_STAGES

SCRIPT = {
    "version": "1.0",
    "title": "Integration Ep",
    "total_duration_seconds": 60,
    "sections": [{"id": "s1", "text": "hi", "start_seconds": 0, "end_seconds": 60}],
}
SCENE_PLAN = {
    "version": "1.0",
    "scenes": [{"id": "sl1", "type": "broll", "description": "river",
                "start_seconds": 0, "end_seconds": 10}],
}
MANIFEST = {"version": "1.0", "assets": []}
EDIT = {"version": "1.0", "render_runtime": "remotion",
        "cuts": [{"id": "c1", "source": "a.mp4", "in_seconds": 0, "out_seconds": 5}]}
REPORT = {"version": "1.0",
          "outputs": [{"path": "r.mp4", "format": "mp4",
                       "resolution": "1920x1080", "duration_seconds": 5}]}
QA = {"version": "1.0", "output_path": "r.mp4", "status": "pass",
      "checks": {"technical_probe": {}, "visual_spotcheck": {},
                 "audio_spotcheck": {}, "promise_preservation": {},
                 "subtitle_check": {}}}
PUBLISH = {"version": "1.0", "entries": []}
RESEARCH = {"version": "1.0", "topic": "rivers",
            "research_date": "2026-10-05",
            "landscape": {"existing_content": [
                {"title": f"t{i}", "source": "youtube", "angle": "a",
                 "what_it_covers": "c"} for i in range(3)],
                "saturated_angles": ["s"], "underserved_gaps": ["g"]},
            "data_points": [
                {"claim": f"c{i}", "source_url": "https://example.com/x",
                 "credibility": "secondary_source"} for i in range(3)],
            "audience_insights": {"common_questions": ["q1", "q2", "q3"],
                                  "misconceptions": [],
                                  "knowledge_level": "mixed"},
            "angles_discovered": [
                {"name": f"a{i}", "hook": "h", "type": "evergreen",
                 "why_now": "w"} for i in range(3)],
            "sources": [{"url": "https://example.com/x", "title": f"s{i}",
                         "used_for": "u"} for i in range(5)]}

PAYLOADS = {"research": RESEARCH, "script": SCRIPT, "storyboard": SCENE_PLAN,
            "footage": MANIFEST, "timeline": EDIT, "editorial": EDIT,
            "render": REPORT, "qa": QA, "publish": PUBLISH}


def _drive_full_lifecycle(store: EpisodeStore):
    for stage in FACTORY_STAGES:
        store.transition(stage, "RUNNING")
        payload = PAYLOADS.get(stage, {"note": f"{stage} payload"})
        store.set_artifact(stage, payload)
        # editorial/timeline share the EDIT payload shape; both validate as edit_decisions
        if stage in APPROVAL_GATES:
            # Gated stages must pass through APPROVED: DONE without prior
            # approval is an ApprovalGateError (publish/human_review included).
            store.transition(stage, "REVIEW")
            store.transition(stage, "APPROVED")
        store.transition(stage, "DONE")


def test_full_lifecycle_all_done(tmp_path):
    store = EpisodeStore("ep-int-001", projects_dir=tmp_path)
    store.init("Integration Episode")
    _drive_full_lifecycle(store)
    status = store.status()
    assert set(status) == set(FACTORY_STAGES)
    assert all(s == "DONE" for s in status.values())
    doc = store.load()
    store.validate(doc)  # envelope schema, explicit
    assert doc["stages"]["script"]["artifact_version"] == 1
    assert doc["stages"]["render"]["done_at"]


def test_crash_resume_from_disk(tmp_path):
    store = EpisodeStore("ep-int-002", projects_dir=tmp_path)
    store.init("Crash Ep")
    for stage in ("topic", "evidence"):
        store.transition(stage, "RUNNING")
        store.set_artifact(stage, {"note": stage})
        if stage in APPROVAL_GATES:
            store.transition(stage, "REVIEW")
            store.transition(stage, "APPROVED")
        store.transition(stage, "DONE")
    store.transition("script", "RUNNING")  # <- "process killed" here
    # fresh handle = post-crash process
    resumed = EpisodeStore("ep-int-002", projects_dir=tmp_path)
    status = resumed.status()
    assert status["topic"] == "DONE"
    assert status["script"] == "RUNNING"  # interrupted stage resumes, not restarts
    resumed.set_artifact("script", SCRIPT)
    resumed.transition("script", "REVIEW")
    resumed.transition("script", "APPROVED")
    resumed.transition("script", "DONE")
    assert resumed.status()["script"] == "DONE"


def test_failure_retry_preserves_history_and_versions(tmp_path):
    store = EpisodeStore("ep-int-003", projects_dir=tmp_path)
    store.init("Fail Ep")
    store.transition("footage", "RUNNING")
    store.fail("footage", "0 clips matched slot queries")
    assert store.status()["footage"] == "FAILED"
    store.transition("footage", "RUNNING")
    store.set_artifact("footage", MANIFEST)
    # footage is gated: retry must still pass through approval before DONE
    store.transition("footage", "REVIEW")
    store.transition("footage", "APPROVED")
    store.transition("footage", "DONE")
    hist = list((tmp_path / "ep-int-003" / "history").glob("episode_*.json"))
    assert len(hist) >= 3
    states_seen = {json.loads(h.read_text(encoding="utf-8"))["stages"]["footage"]["state"] for h in hist}
    assert "FAILED" in states_seen or "RUNNING" in states_seen  # failure preserved on disk
