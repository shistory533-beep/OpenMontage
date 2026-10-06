"""Visual scoring tests: decisions, determinism, penalties, no-bias."""

from __future__ import annotations

import pytest

from lib.editorial.visual_scoring import COMPONENT_WEIGHTS, VisualScorer


def _requirement(**over):
    req = {"id": "b1-vis",
           "narration_block_id": "b1",
           "subject": "canyon river aerial",
           "location": "Oregon",
           "period": "",
           "preferred_media_type": "video",
           "shot_function": "establishing",
           "minimum_duration_seconds": 4.0,
           "desired_duration_seconds": 8.0,
           "evidence_source_ids": ["https://example.com/river"],
           "positive_search_terms": ["canyon", "river", "aerial", "oregon"],
           "rights_requirement": "verified"}
    req.update(over)
    return req


def _good_asset(**over):
    asset = {"asset_id": "wikimedia_1", "provider": "wikimedia",
             "source_id": "1",
             "title": "Aerial view of canyon river in Oregon",
             "description": "Drone footage over the gorge",
             "source_url": "https://example.com/river",
             "download_url": "https://example.com/river.mp4",
             "kind": "video", "width": 1920, "height": 1080, "fps": 30.0,
             "duration": 10.0, "format": "mp4",
             "license": "CC0", "rights_status": "verified_public_domain",
             "extra": {"source_tags": "canyon river aerial oregon"}}
    asset.update(over)
    return asset


def test_weights_sum_to_one():
    assert abs(sum(COMPONENT_WEIGHTS.values()) - 1.0) < 1e-9


def test_good_footage_passes_with_reasons():
    out = VisualScorer().score_asset(_requirement(), _good_asset())
    assert out["decision"] == "pass"
    assert out["final_score"] >= 0.6
    assert set(out["components"]) >= set(COMPONENT_WEIGHTS)
    assert "semantic_relevance" in out["reason"]
    assert out["components"]["rights_confidence"] == 1.0


def test_bad_footage_is_wrong():
    asset = _good_asset(asset_id="x_9", provider="x",
                        title="City traffic at night",
                        description="Cars on a highway",
                        source_url="https://example.com/other",
                        extra={})
    out = VisualScorer().score_asset(_requirement(), asset)
    assert out["decision"] == "wrong"
    assert "no subject overlap" in out["reason"]


def test_rights_failure_drags_score():
    asset = _good_asset(rights_status="restricted",
                        license="All rights reserved")
    out = VisualScorer().score_asset(_requirement(), asset)
    assert out["components"]["rights_confidence"] == 0.0
    assert out["final_score"] < VisualScorer().score_asset(
        _requirement(), _good_asset())["final_score"]


def test_insufficient_duration_penalized():
    asset = _good_asset(duration=1.5)
    out = VisualScorer().score_asset(_requirement(), asset)
    assert out["components"]["duration_suitability"] == 0.2


def test_duplicate_footage_penalized():
    scorer = VisualScorer()
    clean = scorer.score_asset(_requirement(), _good_asset())
    ctx = {"episode_usage_counts": {"wikimedia_1": 2}}
    dup = scorer.score_asset(_requirement(), _good_asset(), ctx)
    assert dup["components"]["repetition_penalty"] == pytest.approx(-0.10)
    assert dup["final_score"] < clean["final_score"]
    assert "repetition_penalty" in dup["reason"]


def test_prior_episode_usage_penalized():
    ctx = {"global_usage_history": ["wikimedia_1"]}
    out = VisualScorer().score_asset(_requirement(), _good_asset(), ctx)
    assert out["components"]["prior_usage_penalty"] == pytest.approx(-0.15)


def test_ordering_stable_and_deterministic():
    scorer = VisualScorer()
    req = _requirement()
    assets = [_good_asset(asset_id=f"p_{i}", provider="pexels",
                          title=f"Canyon river clip {i}")
              for i in range(5)]
    once = scorer.score_requirement(req, assets)
    rev = scorer.score_requirement(req, list(reversed(assets)))
    assert [s["asset_id"] for s in once["scores"]] == \
        [s["asset_id"] for s in rev["scores"]]
    scores = [s["final_score"] for s in once["scores"]]
    assert scores == sorted(scores, reverse=True)


def test_no_provider_bias_by_default():
    scorer = VisualScorer()
    req = _requirement()
    a = _good_asset(asset_id="a_1", provider="alpha")
    b = _good_asset(asset_id="b_1", provider="beta")
    assert (scorer.score_asset(req, a)["final_score"]
            == scorer.score_asset(req, b)["final_score"])


def test_missing_when_no_candidates():
    out = VisualScorer().score_requirement(_requirement(), [])
    assert out["decision"] == "missing" and out["scores"] == []


def test_weak_middle_band():
    req = _requirement(positive_search_terms=["canyon", "river", "aerial",
                                              "oregon", "desert", "sunset",
                                              "rafting", "wildlife"],
                       location="Patagonia")
    out = VisualScorer().score_asset(req, _good_asset())
    assert out["decision"] == "weak"  # right subject, wrong place
    assert "location mismatch" in out["reason"]


def test_attach_scores_embeds_audit_trail():
    scorer = VisualScorer()
    board = {"requirements": [_requirement()]}
    scored = scorer.score_requirement(
        _requirement(), [_good_asset(), _good_asset(asset_id="z_2",
                                                    provider="nasa",
                                                    title="Highway")])
    enriched = scorer.attach_scores(board, [scored])
    req = enriched["requirements"][0]
    assert req["scoring"]["decision"] == "pass"
    assert len(req["scoring"]["scores"]) == 2
    assert enriched["scoring_summary"] == {"b1-vis": "pass"}
    from schemas.artifacts import validate_artifact
    validate_artifact("storyboard",
                      {"version": "1.0", "title": "t",
                       "requirements": [dict(req, id="b1-vis",
                                             narration_block_id="b1",
                                             visual_objective="o",
                                             subject="s",
                                             preferred_media_type="video",
                                             shot_function="establishing",
                                             minimum_duration_seconds=1.0,
                                             desired_duration_seconds=2.0,
                                             positive_search_terms=["canyon"],
                                             rights_requirement="verified",
                                             priority="normal",
                                             fallback_policy="widen_terms",
                                             availability="uncertain")],
                       "chapter_plan": [], "coverage": {}})
