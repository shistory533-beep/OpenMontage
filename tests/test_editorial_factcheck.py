"""Fact Check Agent tests: classification, blocking, adversarials."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.editorial.contracts import (
    Claim,
    Fact,
    ResearchPackage,
    SourceRecord,
)
from lib.editorial.factcheck import FactCheckAgent
from lib.editorial.research import ResearchAgent

FIX = Path(__file__).parent / "fixtures" / "editorial"


def _load(name: str):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _package(extra_facts=(), extra_claims=()) -> ResearchPackage:
    agent = ResearchAgent("Crooked River canyon")
    agent.ingest_sources([SourceRecord(**s) for s in _load("sources")])
    agent.add_facts([Fact(**f) for f in _load("facts")] + list(extra_facts))
    agent.add_claims([Claim(**c) for c in _load("claims")] + list(extra_claims))
    return agent.build_package()


def _blocks():
    from lib.editorial.contracts import NarrationBlock
    return [NarrationBlock(**b) for b in _load("blocks")]


def _timed_dicts():
    from lib.editorial.script_agent import ScriptAgent
    pkg = _package()
    agent = ScriptAgent(pkg, target_duration_seconds=40.0)
    script = agent.build_script("Crooked River", _blocks())
    return script.blocks


def _verdicts(report):
    return {v["claim_id"]: v for v in report.verdicts}


# -- classification ----------------------------------------------------------


def test_clean_package_verifies():
    report = FactCheckAgent().check(_timed_dicts(), _package())
    v = _verdicts(report)
    assert v["c1"]["verdict"] == "verified"
    assert v["c2"]["verdict"] == "verified"
    assert v["c3"]["verdict"] == "opinion"
    assert v["c4"]["verdict"] == "requires_research"
    assert v["c4"]["blocks_approval"] is False  # non-critical: flagged only
    assert report.passed is True
    assert report.blocking_claim_ids == []
    assert report.package_hash == _package().package_hash
    from schemas.artifacts import validate_artifact
    validate_artifact("factcheck_report", report.to_dict())


def _package_with_raw_claims(raw_claims) -> ResearchPackage:
    """Append claims that bypass research-time validation (fact-check adversarial input)."""
    from lib.editorial.hashing import package_hash
    pkg = _package()
    d = pkg.to_dict()
    d["claims"].extend(raw_claims)
    payload = {k: v for k, v in d.items()
               if k not in ("package_hash", "created_at")}
    d["package_hash"] = package_hash(payload)
    return ResearchPackage.from_dict(d)


def test_critical_unsupported_blocks():
    pkg = _package_with_raw_claims([{
        "id": "cx", "statement": "The canyon is 900 feet deep.",
        "claim_type": "factual", "fact_ids": [], "source_ids": [],
        "critical": True}])
    blocks = _timed_dicts() + [{"id": "bx", "claim_ids": ["cx"]}]
    report = FactCheckAgent().check(blocks, pkg)
    v = _verdicts(report)
    assert v["cx"]["verdict"] == "unsupported"
    assert v["cx"]["blocks_approval"] is True
    assert report.passed is False
    assert report.blocking_claim_ids == ["cx"]


def test_contradicted_claim_blocks_even_when_not_critical():
    pkg = _package(
        extra_facts=[Fact(
            id="f6", statement="A survey reports 620 feet.",
            statement_type="fact",
            source_ids=["https://example-news.com/canyon-story"],
            subject_key="canyon depth", numeric_value=620.0,
            numeric_unit="feet")],
        extra_claims=[Claim(
            id="cx", statement="Surveys report the canyon is 620 feet deep.",
            claim_type="factual", fact_ids=["f6"],
            source_ids=["https://example-news.com/canyon-story"],
            critical=False)])
    assert any(c["subject_key"] == "canyon depth"
               for c in pkg.contradictions)
    blocks = _timed_dicts() + [{"id": "bx", "claim_ids": ["cx"]}]
    report = FactCheckAgent().check(blocks, pkg)
    assert _verdicts(report)["cx"]["verdict"] == "contradicted"
    assert report.passed is False


def test_unknown_claim_id_is_structural_block():
    report = FactCheckAgent().check([{"id": "bx", "claim_ids": ["ghost"]}],
                                    _package())
    v = _verdicts(report)["ghost"]
    assert v["verdict"] == "unsupported" and v["problem"] == "source_mismatch"
    assert report.passed is False


# -- adversarials ---------------------------------------------------------------


def test_sneaky_number_mismatch_caught():
    pkg = _package(extra_claims=[Claim(
        id="cx", statement="The canyon reaches 500 feet deep and spans "
                           "12 miles of rim trail.",
        claim_type="factual", fact_ids=["f1"],
        source_ids=["https://www.usgs.gov/river-data/crooked"],
        critical=True)])
    report = FactCheckAgent().check([{"id": "bx", "claim_ids": ["cx"]}], pkg)
    v = _verdicts(report)["cx"]
    assert v["verdict"] == "unsupported"
    assert v["problem"] == "numeric_discrepancy"
    assert "12" in v["evidence_summary"]


def test_date_discrepancy_caught():
    pkg = _package(extra_claims=[Claim(
        id="cx", statement="The gauging station opened in 1998.",
        claim_type="factual", fact_ids=["f1"],
        source_ids=["https://www.usgs.gov/river-data/crooked"],
        critical=True)])
    report = FactCheckAgent().check([{"id": "bx", "claim_ids": ["cx"]}], pkg)
    v = _verdicts(report)["cx"]
    assert v["problem"] == "date_discrepancy"
    assert v["blocks_approval"] is True


def test_attribution_to_non_source_caught():
    pkg = _package(extra_claims=[Claim(
        id="cx", statement="According to NASA, the canyon is 500 feet deep.",
        claim_type="factual", fact_ids=["f1"],
        source_ids=["https://www.usgs.gov/river-data/crooked"],
        critical=True)])
    report = FactCheckAgent().check([{"id": "bx", "claim_ids": ["cx"]}], pkg)
    v = _verdicts(report)["cx"]
    assert v["problem"] == "attribution_error"
    assert v["blocks_approval"] is True


def test_fake_quote_caught():
    pkg = _package(
        extra_facts=[Fact(
            id="f9", statement="The ranger described the sunrise.",
            statement_type="fact",
            source_ids=["https://example-news.com/canyon-story"])],
        extra_claims=[Claim(
            id="cx", statement="The ranger said \"the river sings at dawn.\"",
            claim_type="factual", fact_ids=["f9"],
            source_ids=["https://example-news.com/canyon-story"],
            critical=True, is_direct_quote=True,
            attribution="unnamed ranger")])
    report = FactCheckAgent().check([{"id": "bx", "claim_ids": ["cx"]}], pkg)
    v = _verdicts(report)["cx"]
    assert v["problem"] == "fake_quote_risk"
    assert report.passed is False


def test_unattributed_quote_caught():
    pkg = _package(extra_claims=[Claim(
        id="cx", statement="The canyon is \"a wound of astonishing beauty.\"",
        claim_type="factual", fact_ids=["f1"],
        source_ids=["https://www.usgs.gov/river-data/crooked"],
        critical=False)])
    report = FactCheckAgent().check([{"id": "bx", "claim_ids": ["cx"]}], pkg)
    assert _verdicts(report)["cx"]["problem"] == "fake_quote_risk"


def test_single_source_causal_claim_hedged_not_passed():
    pkg = _package(extra_claims=[Claim(
        id="cx", statement="The flood proves that snowmelt caused the widening.",
        claim_type="factual", fact_ids=["f2"],
        source_ids=["https://www.usgs.gov/river-data/crooked"])])
    report = FactCheckAgent().check([{"id": "bx", "claim_ids": ["cx"]}], pkg)
    v = _verdicts(report)["cx"]
    assert v["verdict"] == "partially_verified"
    assert v["problem"] == "causal_overclaim"
    assert v["recommendation"] == "hedge"
    assert v["blocks_approval"] is False


def test_single_source_superlative_hedged():
    pkg = _package(extra_claims=[Claim(
        id="cx", statement="It is the largest gorge in the state.",
        claim_type="factual", fact_ids=["f2"],
        source_ids=["https://www.usgs.gov/river-data/crooked"])])
    report = FactCheckAgent().check([{"id": "bx", "claim_ids": ["cx"]}], pkg)
    v = _verdicts(report)["cx"]
    assert v["verdict"] == "partially_verified"
    assert v["problem"] == "unsupported_superlative"


def test_multi_sourced_superlative_passes():
    pkg = _package(extra_claims=[Claim(
        id="cx", statement="It is the largest gorge in the state.",
        claim_type="factual", fact_ids=["f1"],
        source_ids=["https://www.usgs.gov/river-data/crooked",
                    "https://doi.org/10.1234/basalt-incision"])])
    report = FactCheckAgent().check([{"id": "bx", "claim_ids": ["cx"]}], pkg)
    assert _verdicts(report)["cx"]["verdict"] == "verified"


# -- independence guarantees ------------------------------------------------------


def test_verdicts_never_rewrite_claims():
    report = FactCheckAgent().check(_timed_dicts(), _package())
    for v in report.verdicts:
        assert v["recommendation"] in (
            "cut", "re-source", "hedge", "research", "none")
        assert "corrected" not in v["evidence_summary"].lower()
        assert "should say" not in v["evidence_summary"].lower()


def test_report_pins_package_hash():
    pkg = _package()
    report = FactCheckAgent().check(_timed_dicts(), pkg)
    assert report.package_hash == pkg.package_hash
    other = _package()
    other.package_hash = "sha256:" + "0" * 64
    report2 = FactCheckAgent().check(_timed_dicts(), other)
    assert report2.package_hash != pkg.package_hash
