"""Editorial smoke test: research -> script -> factcheck -> storyboard.

Runs the full editorial intelligence chain on realistic fixture data
(Crooked River canyon documentary), including visual scoring of a
mixed candidate set, and validates every emitted artifact against its
registered JSON schema. Fully offline and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

from lib.editorial.contracts import (
    Claim,
    Fact,
    NarrationBlock,
    OpenQuestion,
    SourceRecord,
)
from lib.editorial.factcheck import FactCheckAgent
from lib.editorial.research import ResearchAgent
from lib.editorial.script_agent import ScriptAgent
from lib.editorial.storyboard import StoryboardAgent
from lib.editorial.visual_scoring import VisualScorer
from schemas.artifacts import validate_artifact

FIX = Path(__file__).parent / "fixtures" / "editorial"


def _load(name: str):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def test_editorial_chain_smoke(tmp_path):
    # -- research ------------------------------------------------------
    research = ResearchAgent(
        "Crooked River canyon", audience="general", language="en",
        target_duration_seconds=40.0, channel_niche="earth science",
        cache_dir=tmp_path / "source_cache")
    report = research.ingest_sources(
        [SourceRecord(**s) for s in _load("sources")])
    assert not report["duplicates"]
    research.add_facts([Fact(**f) for f in _load("facts")])
    research.add_claims([Claim(**c) for c in _load("claims")])
    research.add_open_questions([OpenQuestion(
        id="q1", question="What widened the upper canyon?",
        why_matters="mechanism beat", related_fact_ids=["f5"])])
    package = research.build_package()
    assert package.contradictions == []  # fixture set is consistent
    validate_artifact("evidence_bundle", package.to_dict())

    # resume mid-run from saved state without losing anything
    state_path = research.save_state(tmp_path / "research_state.json")
    resumed = ResearchAgent.resume(state_path)
    assert (resumed.build_package().package_hash
            == package.package_hash)

    # -- script ----------------------------------------------------------
    scripts = ScriptAgent(package, target_duration_seconds=40.0)
    blocks = [NarrationBlock(**b) for b in _load("blocks")]
    script = scripts.build_script("Crooked River", blocks)
    assert script.unsupported_claim_ids == []
    script_artifact = scripts.script_json(script)
    validate_artifact("script", script_artifact)
    readable = scripts.readable_script(script)
    assert "Crooked River" in readable and "[PAYOFF]" in readable
    mapping = scripts.claim_mapping_json(script)
    assert mapping["claim_mapping"]["b1"] == ["c1"]

    # -- fact check --------------------------------------------------------
    factcheck = FactCheckAgent().check(script.blocks, package)
    assert factcheck.passed is True, factcheck.blocking_claim_ids
    assert factcheck.package_hash == package.package_hash
    validate_artifact("factcheck_report", factcheck.to_dict())

    # -- storyboard ----------------------------------------------------------
    boards = StoryboardAgent()
    board = boards.build("Crooked River board", script.blocks, factcheck)
    assert board["coverage"]["covers_narration"] is True
    validate_artifact("storyboard", board)
    plan = boards.to_scene_plan(board)
    validate_artifact("scene_plan", plan)

    # -- visual scoring -------------------------------------------------------
    scorer = VisualScorer()
    good = {"asset_id": "wikimedia_canyon", "provider": "wikimedia",
            "source_id": "7", "title": "Crooked River carving the gorge",
            "description": "Aerial view below the rim, river keeps carving",
            "source_url": "https://example.com/river",
            "download_url": "https://example.com/river.mp4",
            "kind": "video", "width": 1920, "height": 1080,
            "duration": 12.0, "format": "mp4",
            "license": "CC0", "rights_status": "verified_public_domain",
            "extra": {"source_tags": "canyon river aerial gorge"}}
    bad = dict(good, asset_id="pexels_city", provider="pexels",
               title="City traffic at night",
               description="Highway cars",
               source_url="https://example.com/city",
               extra={})
    req = board["requirements"][0]
    scoreboard = scorer.score_requirement(req, [bad, good])
    assert scoreboard["scores"][0]["asset_id"] == "wikimedia_canyon"
    assert scoreboard["scores"][0]["decision"] == "pass"
    assert scoreboard["decision"] == "pass"
    enriched = scorer.attach_scores(board, [scoreboard])
    assert (enriched["requirements"][0]["scoring"]["scores"][0]
            ["components"]["rights_confidence"] == 1.0)
    validate_artifact("storyboard", enriched)  # scored board still valid
