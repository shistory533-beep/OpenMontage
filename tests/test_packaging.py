"""Packaging tests: titles, description, chapters, tags, thumbnail."""

from __future__ import annotations

import pytest

from lib.producer.packaging import PackageAgent, PackagingError, score_title


def _verified():
    return ["The canyon reaches 500 feet deep.",
            "The basalt is 5.3 million years old."]


def test_five_scored_titles_no_clickbait():
    agent = PackageAgent()
    out = agent.generate_titles(
        "Crooked River canyon",
        ["crooked", "river", "canyon", "basalt"],
        _verified(),
        seeds=["Crooked River canyon: what the evidence shows",
               "How water cut a 500-foot canyon",
               "The river that carved stone",
               "SHOCKING canyon secrets EXPOSED",
               "Basalt, water, and deep time"])
    assert len(out["candidates"]) == 5
    assert all(c["accepted"] for c in out["candidates"])
    assert any("SHOCKING" in r for r in out["rejected"])
    assert all(c["misleading_risk"] < 0.5 for c in out["candidates"])
    for axis in ("clarity", "curiosity", "specificity", "relevance",
                 "originality"):
        assert axis in out["candidates"][0]["scores"]
    from schemas.artifacts import validate_artifact
    bundle = agent.build({
        "episode_id": "ep-pkg-001", "topic": "Crooked River canyon",
        "topic_keywords": ["crooked", "river", "canyon"],
        "verified_claims": _verified(),
        "title_seeds": ["Crooked River canyon: what the evidence shows",
                        "How water cut a 500-foot canyon",
                        "The river that carved stone",
                        "Basalt, water, and deep time",
                        "A canyon in five hundred feet"],
        "script": {"sections": [
            {"id": "s1", "chapter_id": "hook", "start_seconds": 0.0},
            {"id": "s2", "chapter_id": "story", "start_seconds": 12.5}]},
        "storyboard": {"requirements": [
            {"id": "req-1", "subject": "aerial canyon",
             "shot_type": "wide", "visual_objective": "establishing",
             "priority": "hero"}]},
        "narration_manifest": {"segments": [
            {"asset_id": "n1", "start_seconds": 0.0, "end_seconds": 5.0,
             "text": "The river."}]},
        "research_package": {"sources": [
            {"url": "https://www.usgs.gov/river-data"}]},
        "render_report": {"outputs": [{"path": "final.mp4"}]}})
    validate_artifact("package_bundle", bundle)
    assert bundle["chosen_title"] == bundle["titles"]["candidates"][0][
        "title"]


def test_unverifiable_superlative_rejected():
    candidate = score_title("The largest canyon on Earth, proven at last",
                            ["canyon"], _verified())
    assert candidate.accepted is False
    assert candidate.misleading_risk >= 0.5


def test_grounded_superlative_accepted():
    candidate = score_title(
        "The 500-foot canyon the river carved",
        ["canyon", "river"], _verified())
    assert candidate.accepted is True


def test_all_clickbait_seeds_fail_closed():
    agent = PackageAgent()
    with pytest.raises(PackagingError):
        agent.generate_titles("Rivers", ["rivers"], ["Rivers flow."],
                              seeds=["SHOCKING river EXPOSED"])


def test_description_chapters_tags():
    agent = PackageAgent()
    chapters = agent.build_chapters([
        {"chapter_id": "hook", "start_seconds": 0.0},
        {"chapter_id": "story", "start_seconds": 75.0}])
    assert chapters[0] == {"chapter_id": "hook", "title": "Hook",
                           "start": "0:00"}
    assert chapters[1]["start"] == "1:15"
    desc = agent.build_description("Rivers carve canyons.", chapters,
                                   ["https://www.usgs.gov/x"])
    assert "0:00 Hook" in desc and "Sources:" in desc
    tags = agent.build_tags(["Crooked River", "canyon"])
    assert "crooked river" in tags["tags"]
    assert tags["hashtags"][0].startswith("#")


def test_thumbnail_spec_grounded():
    agent = PackageAgent()
    spec = agent.thumbnail_spec(
        {"id": "req-1", "subject": "aerial canyon",
         "shot_type": "wide", "visual_objective": "establishing river"},
        "Crooked River canyon", _verified())
    for key in ("focal_subject", "composition", "text", "contrast",
                "visual_concept", "reason"):
        assert spec[key], key
    assert spec["text_word_count"] <= 4
    assert "Crooked River" in spec["reason"] or "canyon" in spec["reason"]


def test_thumbnail_text_falls_back_to_subject():
    agent = PackageAgent()
    spec = agent.thumbnail_spec(
        {"id": "req-1", "subject": "aerial canyon",
         "shot_type": "close_up", "visual_objective": "detail"},
        "Totally unrelated jazz hands", _verified())
    assert "jazz" not in spec["text"].lower()
