"""Integration: youtube-documentary checkpoints on disk (offline, tmp dir).

Proves, against the real checkpoint writer/reader (not mocks):
  - ordered run topic -> human_review, resume via get_next_stage,
  - failure halts at the failed stage and retry continues,
  - guard blocks publish until human_review APPROVED, then allows it.
"""
from __future__ import annotations

from pathlib import Path

from lib.checkpoint import get_next_stage, init_project, write_checkpoint
from lib.pipeline_guard import (
    PublishBlockedError,
    assert_stage_ready,
    read_checkpoints,
)
from lib.pipeline_loader import load_pipeline

PIPE = "youtube-documentary"
BRIEF = {"version": "1.0", "title": "T", "hook": "h",
         "key_points": ["a"], "tone": "calm", "style": "doc",
         "target_platform": "youtube", "target_duration_seconds": 600}
RESEARCH = {"version": "1.0", "topic": "rivers", "research_date": "2026-10-05",
            "landscape": {"existing_content": [
                {"title": f"t{i}", "source": "youtube", "angle": "a",
                 "what_it_covers": "c"} for i in range(3)],
                "saturated_angles": ["s"], "underserved_gaps": ["g"]},
            "data_points": [{"claim": f"c{i}",
                             "source_url": "https://example.com/x",
                             "credibility": "secondary_source"} for i in range(3)],
            "audience_insights": {"common_questions": ["q1", "q2", "q3"],
                                  "misconceptions": [], "knowledge_level": "k"},
            "angles_discovered": [{"name": f"a{i}", "hook": "h",
                                   "type": "evergreen", "why_now": "w"}
                                  for i in range(3)],
            "sources": [{"url": "https://example.com/x", "title": f"s{i}",
                         "used_for": "u"} for i in range(5)]}
SCRIPT = {"version": "1.0", "title": "T", "total_duration_seconds": 600,
          "sections": [{"id": "s1", "text": "hi", "start_seconds": 0,
                        "end_seconds": 600}]}
SCENES = {"version": "1.0", "scenes": [
    {"id": "sl1", "type": "broll", "description": "river",
     "start_seconds": 0, "end_seconds": 600}]}
MANIFEST_ART = {"version": "1.0", "assets": []}
EDIT = {"version": "1.0", "render_runtime": "remotion", "cuts": [
    {"id": "c1", "source": "a.mp4", "in_seconds": 0, "out_seconds": 600}]}
REPORT = {"version": "1.0", "outputs": [
    {"path": "r.mp4", "format": "mp4", "resolution": "1920x1080",
     "duration_seconds": 600}]}
QA = {"version": "1.0", "output_path": "r.mp4", "status": "pass", "checks": {
    "technical_probe": {}, "visual_spotcheck": {}, "audio_spotcheck": {},
    "promise_preservation": {}, "subtitle_check": {}}}
PUBLISH = {"version": "1.0", "entries": []}
EVIDENCE = {"version": "1.0", "topic": "rivers",
            "sources": [{"title": "USGS river data",
                         "url": "https://www.usgs.gov/river-data",
                         "publisher": "USGS", "date": "2024-05-01",
                         "source_type": "government",
                         "retrieved_at": "2026-10-05T00:00:00+00:00"}],
            "facts": [], "claims": [],
            "evidence_graph": {"nodes": {}, "edges": []},
            "contradictions": [], "open_questions": [],
            "package_hash": "sha256:" + "a" * 64}
FACTCHECK = {"version": "1.0", "package_hash": "sha256:" + "a" * 64,
             "verdicts": [{"claim_id": "c1", "statement": "rivers flow",
                           "verdict": "verified",
                           "source_ids": ["https://www.usgs.gov/river-data"],
                           "evidence_summary": "USGS gauge record",
                           "confidence": 0.9, "problem": "",
                           "recommendation": "none",
                           "blocks_approval": False}],
             "blocking_claim_ids": [], "passed": True}

CHAIN = [("topic", {"brief": BRIEF}, True),
         ("research", {"research_brief": RESEARCH}, False),
         ("evidence", {"evidence_bundle": EVIDENCE}, False),
         ("script", {"script": SCRIPT}, True),
         ("fact_check", {"factcheck_report": FACTCHECK}, False),
         ("storyboard", {"scene_plan": SCENES}, True),
         ("narration", {"narration_manifest": {"tracks": 6}}, False),
         ("footage", {"asset_manifest": MANIFEST_ART}, True),
         ("footage_intelligence", {"footage_report": {"verdicts": []}},
          False),
         ("editorial", {"edit_decisions": EDIT}, False),
         ("timeline", {"edit_decisions": EDIT}, False),
         ("audio", {"audio_mix": {"loudness_db": -16}}, False),
         ("render", {"render_report": REPORT}, False),
         ("qa", {"final_review": QA}, False),
         ("packaging", {"package_bundle": {"path": "exports/x"}}, False),
         ("thumbnail", {"thumbnail_set": {"concept": "river at dawn"}},
          False),
         ("human_review", {"review_decision": {"verdict": "APPROVED"}},
          True)]


def _write_chain(pdir: Path, pid: str, upto: str | None = None,
                 approve_hr: bool = True):
    for stage, arts, gated in CHAIN:
        write_checkpoint(pdir, pid, stage, "completed", arts,
                         pipeline_type=PIPE,
                         human_approved=(approve_hr if stage == "human_review"
                                         else True) if gated else False)
        if upto == stage:
            break


def test_ordered_run_and_resume(tmp_path):
    pid = "ydoc-int-001"
    init_project(pid, title="T", pipeline_type=PIPE, pipeline_dir=tmp_path)
    assert get_next_stage(tmp_path, pid, PIPE) == "topic"
    _write_chain(tmp_path, pid, upto="script")
    assert get_next_stage(tmp_path, pid, PIPE) == "fact_check"
    _write_chain(tmp_path, pid)  # complete the rest
    assert get_next_stage(tmp_path, pid, PIPE) == "publish"


def test_resume_after_failure(tmp_path):
    pid = "ydoc-int-002"
    init_project(pid, title="T", pipeline_type=PIPE, pipeline_dir=tmp_path)
    _write_chain(tmp_path, pid, upto="audio")
    write_checkpoint(tmp_path, pid, "render", "failed",
                     {"render_report": REPORT}, pipeline_type=PIPE,
                     error="ffmpeg OOM on 4k upscale")
    assert get_next_stage(tmp_path, pid, PIPE) == "render"  # halted here
    m = load_pipeline(PIPE)
    cps = read_checkpoints(tmp_path, pid, m)
    assert_stage_ready(m, "render", cps)  # retry is legal: prereqs intact
    write_checkpoint(tmp_path, pid, "render", "completed",
                     {"render_report": REPORT}, pipeline_type=PIPE)
    assert get_next_stage(tmp_path, pid, PIPE) == "qa"


def test_publish_blocked_then_allowed(tmp_path):
    import pytest

    pid = "ydoc-int-003"
    init_project(pid, title="T", pipeline_type=PIPE, pipeline_dir=tmp_path)
    _write_chain(tmp_path, pid, upto="thumbnail")
    m = load_pipeline(PIPE)
    with pytest.raises(PublishBlockedError):
        assert_stage_ready(m, "publish", read_checkpoints(tmp_path, pid, m))
    write_checkpoint(tmp_path, pid, "human_review", "completed",
                     {"review_decision": {"verdict": "APPROVED"}},
                     pipeline_type=PIPE, human_approved=True)
    assert_stage_ready(m, "publish", read_checkpoints(tmp_path, pid, m))
    write_checkpoint(tmp_path, pid, "publish", "completed",
                     {"publish_log": PUBLISH}, pipeline_type=PIPE,
                     human_approved=True)
    assert get_next_stage(tmp_path, pid, PIPE) == "analytics"  # terminal stage
    write_checkpoint(tmp_path, pid, "analytics",
                     "completed", {"analytics_report": {"metrics": {}}},
                     pipeline_type=PIPE)
    assert get_next_stage(tmp_path, pid, PIPE) is None  # run complete
