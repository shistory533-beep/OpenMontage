"""Research Agent tests: success, failure, dedupe, contradictions, resume."""

from __future__ import annotations

import pytest

from lib.editorial.contracts import (
    Claim,
    Fact,
    OpenQuestion,
    SourceRecord,
)
from lib.editorial.research import (
    ResearchAgent,
    ResearchError,
    SourceCache,
    normalize_url,
    quality_weight,
)

S1 = "https://www.usgs.gov/river-data/crooked"
S2 = "https://doi.org/10.1234/basalt-incision"
S3 = "https://example-news.com/canyon-story"


def _sources():
    return [
        SourceRecord(title="Crooked River discharge data",
                     url=S1, publisher="USGS",
                     date="2024-05-01", source_type="government",
                     retrieved_at="2026-01-01T00:00:00+00:00"),
        SourceRecord(title="Basalt canyon incision rates",
                     url=S2, publisher="Journal of Geology",
                     date="2021-03-15", source_type="academic",
                     retrieved_at="2026-01-01T00:00:00+00:00"),
        SourceRecord(title="Canyon story", url=S3,
                     publisher="Example News", date="",
                     source_type="news",
                     retrieved_at="2026-01-01T00:00:00+00:00"),
    ]


def _agent():
    agent = ResearchAgent("Crooked River canyon", audience="general",
                          target_duration_seconds=600.0,
                          channel_niche="earth science")
    agent.ingest_sources(_sources())
    return agent


def _facts():
    return [
        Fact(id="f1", statement="The canyon is 500 feet deep.",
             statement_type="fact", source_ids=[S1, S2],
             subject_key="canyon depth", numeric_value=500.0,
             numeric_unit="feet"),
        Fact(id="f2", statement="The basalt is 5.3 million years old.",
             statement_type="fact", source_ids=[S1],
             subject_key="basalt age", numeric_value=5.3,
             numeric_unit="million years"),
        Fact(id="f3", statement="Incision accelerated after the Pleistocene.",
             statement_type="inference", source_ids=[S2],
             subject_key="incision timing"),
        Fact(id="f4", statement="It is the most beautiful gorge in Oregon.",
             statement_type="opinion", source_ids=[S3],
             subject_key="beauty"),
        Fact(id="f5", statement="Groundwater sapping role remains debated.",
             statement_type="unresolved", source_ids=[S2],
             subject_key="widening"),
    ]


def _claims():
    return [
        Claim(id="c1", statement="The canyon reaches 500 feet deep.",
              claim_type="factual", fact_ids=["f1"], source_ids=[S1, S2],
              critical=True),
        Claim(id="c2", statement="The basalt is 5.3 million years old.",
              claim_type="factual", fact_ids=["f2"], source_ids=[S1]),
        Claim(id="c3", statement="It is the most beautiful gorge in Oregon.",
              claim_type="opinion", fact_ids=["f4"], source_ids=[S3]),
        Claim(id="c4", statement="Widening may involve groundwater sapping.",
              claim_type="factual", fact_ids=["f5"], source_ids=[S2]),
    ]


# -- success ---------------------------------------------------------------


def test_research_success_builds_hashed_package():
    agent = _agent()
    agent.add_facts(_facts())
    agent.add_claims(_claims())
    agent.add_open_questions([OpenQuestion(
        id="q1", question="What widened the upper canyon?",
        why_matters="mechanism beat depends on it",
        related_fact_ids=["f5"])])
    pkg = agent.build_package()
    assert pkg.topic == "Crooked River canyon"
    assert len(pkg.sources) == 3 and len(pkg.facts) == 5
    assert len(pkg.claims) == 4 and len(pkg.open_questions) == 1
    assert pkg.package_hash.startswith("sha256:")
    assert len(pkg.package_hash) == 71
    assert pkg.evidence_graph["nodes"] and pkg.evidence_graph["edges"]
    # determinism: rebuild from same material -> identical hash
    agent2 = _agent()
    agent2.add_facts(_facts())
    agent2.add_claims(_claims())
    agent2.add_open_questions([OpenQuestion(
        id="q1", question="What widened the upper canyon?",
        why_matters="mechanism beat depends on it",
        related_fact_ids=["f5"])])
    assert agent2.build_package().package_hash == pkg.package_hash


def test_primary_sources_outrank_secondary():
    gov = SourceRecord(title="t", url="https://a.gov/x", publisher="USGS",
                       source_type="government", retrieved_at="2026-01-01T00:00:00+00:00")
    news = SourceRecord(title="t", url="https://news.example/x",
                        publisher="News", source_type="news",
                        retrieved_at="2026-01-01T00:00:00+00:00")
    assert quality_weight(gov) >= quality_weight(news)
    dated = SourceRecord(title="t", url="https://news.example/y",
                         publisher="News", date="2024-01-01",
                         source_type="news",
                         retrieved_at="2026-01-01T00:00:00+00:00")
    assert quality_weight(dated) > quality_weight(news)


def test_single_source_confidence_capped():
    agent = _agent()
    agent.add_facts(_facts())
    conf_multi = agent.fact_confidence(agent._facts["f1"])
    conf_single = agent.fact_confidence(agent._facts["f2"])
    assert conf_multi > conf_single
    assert conf_single <= 0.7


# -- failure modes -----------------------------------------------------------


def test_source_missing_fields_rejected():
    agent = ResearchAgent("t")
    with pytest.raises(ResearchError):
        agent.ingest_sources([SourceRecord(title="", url="https://x.example/a",
                                           publisher="P", source_type="news",
                                           retrieved_at="2026-01-01T00:00:00+00:00")])


def test_unknown_source_type_rejected():
    agent = ResearchAgent("t")
    with pytest.raises(ResearchError):
        agent.ingest_sources([SourceRecord(title="t", url="https://x.example/a",
                                           publisher="P", source_type="blog",
                                           retrieved_at="2026-01-01T00:00:00+00:00")])


def test_fact_without_sources_rejected():
    agent = _agent()
    with pytest.raises(ResearchError):
        agent.add_facts([Fact(id="fx", statement="Something happened.",
                              statement_type="fact", source_ids=[])])


def test_fact_citing_unknown_source_rejected():
    agent = _agent()
    with pytest.raises(ResearchError):
        agent.add_facts([Fact(id="fx", statement="Something happened.",
                              statement_type="fact",
                              source_ids=["https://nope.example/"]) ])


def test_factual_claim_without_facts_rejected():
    agent = _agent()
    agent.add_facts(_facts())
    with pytest.raises(ResearchError):
        agent.add_claims([Claim(id="cx", statement="Big claim.",
                                claim_type="factual", fact_ids=[])])


def test_quote_without_attribution_rejected():
    agent = _agent()
    agent.add_facts(_facts())
    with pytest.raises(ResearchError):
        agent.add_claims([Claim(id="cx", statement='"We measured it."',
                                claim_type="factual", fact_ids=["f1"],
                                source_ids=[S1], is_direct_quote=True,
                                attribution="")])


def test_empty_package_rejected():
    with pytest.raises(ResearchError):
        ResearchAgent("t").build_package()


# -- dedupe ------------------------------------------------------------------


def test_duplicate_sources_deduplicated():
    agent = ResearchAgent("t")
    recs = _sources()
    report = agent.ingest_sources(recs)
    assert len(report["added"]) == 3 and not report["duplicates"]
    variants = [
        SourceRecord(title="Crooked River discharge data",
                     url="https://www.usgs.gov/river-data/crooked/"
                         "?utm_source=x&utm_medium=y",
                     publisher="USGS", date="2024-05-01",
                     source_type="government",
                     retrieved_at="2026-01-01T00:00:00+00:00"),
        SourceRecord(title="Crooked River discharge data",
                     url="https://other.example/different",
                     publisher="USGS", date="2024-05-01",
                     source_type="government",
                     retrieved_at="2026-01-01T00:00:00+00:00"),
    ]
    report2 = agent.ingest_sources(variants)
    assert not report2["added"] and len(report2["duplicates"]) == 2


def test_normalize_url_drops_tracking():
    assert (normalize_url("https://WWW.USGS.GOV/a/?b=2&utm_source=x&a=1")
            == normalize_url("http://usgs.gov/a?a=1&b=2")
            .replace("http://", "https://"))


# -- contradictions ------------------------------------------------------------


def test_numeric_contradiction_detected():
    agent = _agent()
    agent.add_facts(_facts() + [
        Fact(id="f6", statement="A survey reports the canyon is 620 feet deep.",
             statement_type="fact", source_ids=[S3],
             subject_key="canyon depth", numeric_value=620.0,
             numeric_unit="feet"),
    ])
    contradictions = agent.detect_contradictions()
    assert len(contradictions) == 1
    assert set(contradictions[0].fact_ids) == {"f1", "f6"}
    pkg = agent.build_package()
    flagged = {f["id"] for f in pkg.facts if f.get("contradicted")}
    assert flagged == {"f1", "f6"}


def test_close_values_are_not_contradictions():
    agent = _agent()
    agent.add_facts(_facts() + [
        Fact(id="f6", statement="Another survey says 505 feet.",
             statement_type="fact", source_ids=[S3],
             subject_key="canyon depth", numeric_value=505.0,
             numeric_unit="feet"),
    ])
    assert agent.detect_contradictions() == []


def test_date_conflict_detected():
    agent = _agent()
    agent.add_facts(_facts() + [
        Fact(id="f7", statement="The dam was completed in 1958.",
             statement_type="fact", source_ids=[S1],
             subject_key="dam completion", date_value="1958-01-01"),
        Fact(id="f8", statement="Records show the dam finished in 1961.",
             statement_type="fact", source_ids=[S2],
             subject_key="dam completion", date_value="1961-06-01"),
    ])
    contradictions = agent.detect_contradictions()
    assert any(c.subject_key == "dam completion" for c in contradictions)


# -- cache + resume --------------------------------------------------------------


def test_source_cache_resume(tmp_path):
    cache = SourceCache(tmp_path / "cache")
    rec = _sources()[0]
    is_new, _ = cache.add(rec)
    assert is_new is True
    is_new2, _ = cache.add(rec)
    assert is_new2 is False
    assert cache.get(rec.url).title == rec.title
    cache2 = SourceCache(tmp_path / "cache")
    assert len(cache2.all_records()) == 1  # state reloaded from disk


def test_agent_state_resume(tmp_path):
    agent = _agent()
    agent.add_facts(_facts())
    state_path = tmp_path / "research_state.json"
    agent.save_state(state_path)
    resumed = ResearchAgent.resume(state_path)
    resumed.add_claims(_claims())
    pkg = resumed.build_package()
    assert len(pkg.sources) == 3 and len(pkg.facts) == 5
