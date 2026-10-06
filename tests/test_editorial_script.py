"""Script Agent tests: structure, duration, grounding, language, uncertainty."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.editorial.contracts import (
    Claim,
    Fact,
    NarrationBlock,
    ResearchPackage,
    SourceRecord,
)
from lib.editorial.research import ResearchAgent
from lib.editorial.script_agent import (
    ScriptAgent,
    ScriptError,
    estimate_duration_seconds,
)

FIX = Path(__file__).parent / "fixtures" / "editorial"


def _load(name: str):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


S1 = "https://www.usgs.gov/river-data/crooked"
S2 = "https://doi.org/10.1234/basalt-incision"
S3 = "https://example-news.com/canyon-story"


def _agent() -> ResearchAgent:
    agent = ResearchAgent("Crooked River canyon", audience="general",
                          target_duration_seconds=600.0,
                          channel_niche="earth science")
    agent.ingest_sources([SourceRecord(**s) for s in _load("sources")])
    return agent


def _facts():
    return [Fact(**f) for f in _load("facts")]


def _claims():
    return [Claim(**c) for c in _load("claims")]


def _package() -> ResearchPackage:
    agent = _agent()
    agent.add_facts(_facts())
    agent.add_claims(_claims())
    return agent.build_package()


def _blocks() -> list[NarrationBlock]:
    return [NarrationBlock(**b) for b in _load("blocks")]


def _agent_for(target: float = 40.0) -> ScriptAgent:
    return ScriptAgent(_package(), target_duration_seconds=target)


# -- happy path --------------------------------------------------------------


def test_valid_script_builds_all_outputs():
    agent = _agent_for()
    script = agent.build_script("Crooked River", _blocks())
    assert script.total_duration_seconds > 0
    assert len(script.blocks) == 9
    assert script.unsupported_claim_ids == []
    assert set(script.claim_mapping) == {f"b{i}" for i in range(1, 10)}
    assert script.pacing_report["block_count"] == 9
    assert set(script.pacing_report["beats"]) == {
        "hook", "question", "setup", "discovery", "escalation",
        "mechanism", "consequence", "transformation", "payoff"}
    # script.json validates against the canonical script schema
    from schemas.artifacts import validate_artifact
    js = agent.script_json(script)
    validate_artifact("script", js)
    assert js["sections"][0]["start_seconds"] == 0.0
    assert js["sections"][-1]["end_seconds"] == script.total_duration_seconds
    doc = js["metadata"]["documentary"]
    assert doc["claim_mapping"]["b1"] == ["c1"]
    assert doc["unsupported_claim_ids"] == []
    mapping = agent.claim_mapping_json(script)
    assert mapping["claim_mapping"]["b4"] == ["c1"]
    # readable script + pacing report exist and are coherent
    text = agent.readable_script(script)
    assert "# Crooked River" in text and "## Chapter: ch2" in text
    assert "[HOOK] b1" in text


def test_duration_estimate_sane():
    assert estimate_duration_seconds(" ".join(["word"] * 150)) == 60.0
    assert estimate_duration_seconds("", "en") == 0.0


# -- duration enforcement -------------------------------------------------------


def test_duration_miss_raises():
    agent = _agent_for(target=10.0)  # ~60s of narration vs 10s target
    with pytest.raises(ScriptError):
        agent.build_script("Crooked River", _blocks())


def test_duration_boundary_ok():
    probe = _agent_for(target=0.0)
    total = sum(b.estimated_duration_seconds
                for b in probe.time_blocks(_blocks()))
    agent = _agent_for(target=round(total * 1.05, 2))  # +5%: inside ±10%
    script = agent.build_script("Crooked River", _blocks())
    assert script.pacing_report["total_seconds"] == total


# -- structural failures ----------------------------------------------------------


def test_beat_order_enforced():
    agent = _agent_for()
    blocks = _blocks()
    blocks[0], blocks[-1] = blocks[-1], blocks[0]
    with pytest.raises(ScriptError):
        agent.build_script("Crooked River", blocks)


def test_missing_beat_field_rejected():
    agent = _agent_for()
    blocks = _blocks()
    blocks[3] = NarrationBlock(**{**blocks[3].to_dict(), "beat": "climax"})
    with pytest.raises(ScriptError):
        agent.build_script("Crooked River", blocks)


def test_unknown_claim_link_rejected():
    agent = _agent_for()
    blocks = _blocks()
    blocks[0] = NarrationBlock(**{**blocks[0].to_dict(),
                                  "claim_ids": ["nope"]})
    with pytest.raises(ScriptError):
        agent.build_script("Crooked River", blocks)


def test_missing_evidence_flagged_not_silent():
    agent = _agent_for()
    blocks = _blocks()
    blocks[1] = NarrationBlock(**{**blocks[1].to_dict(),
                                  "text": "The river is 900 feet deep here.",
                                  "claim_ids": []})
    script = agent.build_script("Crooked River", blocks)
    assert "b2" in script.unsupported_claim_ids


# -- grounding adversarials --------------------------------------------------------


def test_fabricated_statistic_caught():
    agent = _agent_for()
    blocks = _blocks()
    blocks[3] = NarrationBlock(**{**blocks[3].to_dict(),
                                  "text": "The gorge reaches 900 feet, "
                                          "twice the old record."})
    script = agent.build_script("Crooked River", blocks)
    assert "b4" in script.unsupported_claim_ids


def test_fake_quote_caught():
    agent = _agent_for()
    blocks = _blocks()
    blocks[2] = NarrationBlock(**{**blocks[2].to_dict(),
                                  "text": 'A ranger once said "the river '
                                          'sings at dawn every day."'})
    script = agent.build_script("Crooked River", blocks)
    assert "b3" in script.unsupported_claim_ids


def test_causal_overclaim_needs_two_sources():
    agent = _agent_for()
    agent_single = ScriptAgent(_package(), target_duration_seconds=60.0)
    blocks = _blocks()
    blocks[5] = NarrationBlock(**{**blocks[5].to_dict(),
                                  "text": "This flood proves that dams "
                                          "caused the widening.",
                                  "claim_ids": ["c2"]})
    findings = agent_single.validate_blocks(blocks)["findings"]
    assert any(f["code"] == "unsupported_causal_or_superlative"
               for f in findings if f["block_id"] == "b6")


def test_weasel_attribution_flagged():
    agent = _agent_for()
    blocks = _blocks()
    blocks[6] = NarrationBlock(**{**blocks[6].to_dict(),
                                  "text": "Scientists say the walls keep "
                                          "growing taller each year."})
    findings = agent.validate_blocks(blocks)["findings"]
    assert any(f["code"] == "weasel_attribution"
               for f in findings if f["block_id"] == "b7")


def test_repetitive_filler_flagged():
    agent = _agent_for()
    blocks = _blocks()
    filler = "the patient river carves the ancient stone slowly"
    blocks[0] = NarrationBlock(**{**blocks[0].to_dict(),
                                  "text": f"Look down as {filler}."})
    blocks[8] = NarrationBlock(**{**blocks[8].to_dict(),
                                  "text": f"Remember how {filler}."})
    findings = agent.validate_blocks(blocks)["findings"]
    assert any(f["code"] == "repetitive_filler" for f in findings)


def test_uncertainty_dropped_flagged():
    agent = _agent_for()
    blocks = _blocks()
    # c4 rests on unresolved f5; strip every hedge word out of b5
    blocks[4] = NarrationBlock(**{**blocks[4].to_dict(),
                                  "text": "Floods widened the upper canyon "
                                          "in a single season."})
    findings = agent.validate_blocks(blocks)["findings"]
    assert any(f["code"] == "uncertainty_dropped"
               for f in findings if f["block_id"] == "b5")
