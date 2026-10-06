"""Storyboard Agent tests: gating, coverage, availability, scene_plan."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.editorial.contracts import FactCheckReport
from lib.editorial.research import ResearchAgent
from lib.editorial.contracts import Claim, Fact, SourceRecord
from lib.editorial.script_agent import ScriptAgent
from lib.editorial.factcheck import FactCheckAgent
from lib.editorial.storyboard import StoryboardAgent, StoryboardError

FIX = Path(__file__).parent / "fixtures" / "editorial"


def _load(name: str):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _chain():
    from lib.editorial.contracts import NarrationBlock
    agent = ResearchAgent("Crooked River canyon")
    agent.ingest_sources([SourceRecord(**s) for s in _load("sources")])
    agent.add_facts([Fact(**f) for f in _load("facts")])
    agent.add_claims([Claim(**c) for c in _load("claims")])
    pkg = agent.build_package()
    scripts = ScriptAgent(pkg, target_duration_seconds=40.0)
    blocks = [NarrationBlock(**b) for b in _load("blocks")]
    script = scripts.build_script("Crooked River", blocks)
    report = FactCheckAgent().check(script.blocks, pkg)
    return pkg, script, report


def test_storyboard_covers_every_block():
    pkg, script, report = _chain()
    assert report.passed
    board = StoryboardAgent().build("Crooked River board",
                                    script.blocks, report)
    assert len(board["requirements"]) >= len(script.blocks)
    covered = {r["narration_block_id"] for r in board["requirements"]}
    assert covered == {b["id"] for b in script.blocks}
    assert board["coverage"]["covers_narration"] is True
    assert board["coverage"]["missing_requirement_ids"] == []
    assert len(board["chapter_plan"]) == 3
    from schemas.artifacts import validate_artifact
    validate_artifact("storyboard", board)


def test_storyboard_never_assumes_footage_exists():
    _, script, report = _chain()
    board = StoryboardAgent().build("b", script.blocks, report)
    states = {r["availability"] for r in board["requirements"]}
    assert "available" not in states
    assert states <= {"uncertain", "missing"}


def test_blocked_report_blocks_storyboard():
    _, script, _ = _chain()
    bad = FactCheckReport(package_hash="sha256:" + "1" * 64,
                          verdicts=[], blocking_claim_ids=["c1"],
                          passed=False)
    with pytest.raises(StoryboardError):
        StoryboardAgent().build("b", script.blocks, bad)


def test_long_blocks_get_multiple_requirements():
    _, script, report = _chain()
    blocks = [dict(b, estimated_duration_seconds=25.0)
              for b in script.blocks[:1]]
    board = StoryboardAgent().build("b", blocks, report)
    assert len(board["requirements"]) > 1
    assert all(r["desired_duration_seconds"] > 0
               for r in board["requirements"])


def test_requirements_have_search_and_rights_contract():
    _, script, report = _chain()
    board = StoryboardAgent().build("b", script.blocks, report)
    for req in board["requirements"]:
        assert req["positive_search_terms"], req["id"]
        assert req["rights_requirement"] == "verified"
        assert req["fallback_policy"] in (
            "widen_terms", "adjacent_slot", "flag_missing")
        assert req["minimum_duration_seconds"] <= \
            req["desired_duration_seconds"]


def test_chart_map_detection():
    _, script, report = _chain()
    blocks = [dict(b, text="The chart shows growth of 5.3 million years of data.",
                   estimated_duration_seconds=4.0)
              for b in script.blocks[:1]]
    board = StoryboardAgent().build("b", blocks, report)
    assert board["requirements"][0]["shot_function"] == "chart"
    assert board["requirements"][0]["preferred_media_type"] == "image"


def test_to_scene_plan_shape():
    _, script, report = _chain()
    agent = StoryboardAgent()
    board = agent.build("b", script.blocks, report)
    plan = agent.to_scene_plan(board)
    from schemas.artifacts import validate_artifact
    validate_artifact("scene_plan", plan)
    assert len(plan["scenes"]) == len(board["requirements"])
    assert plan["scenes"][0]["start_seconds"] == 0.0
    for scene, req in zip(plan["scenes"], board["requirements"]):
        assert scene["script_section_id"] == req["narration_block_id"]
