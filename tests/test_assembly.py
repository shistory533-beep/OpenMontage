"""Editorial assembly tests: moments, Timeline IR, surgical revision."""

from __future__ import annotations

import pytest

from lib.producer.assembly import (
    AssemblyGapError,
    assemble_timeline,
    input_hash,
    replace_scene,
    retime_timeline,
    revise_scene,
    select_moments,
)
from lib.producer.contracts import FootageMoment


def _reqs():
    return [
        {"id": "req-1", "narration_block_id": "s1",
         "shot_function": "establishing",
         "desired_duration_seconds": 6.0,
         "positive_search_terms": ["river", "canyon"]},
        {"id": "req-2", "narration_block_id": "s2",
         "shot_function": "evidence",
         "desired_duration_seconds": 4.0,
         "positive_search_terms": ["rock", "strata"]},
        {"id": "req-3", "narration_block_id": "s3",
         "shot_function": "payoff",
         "desired_duration_seconds": 5.0,
         "positive_search_terms": ["sunset", "water"]},
    ]


def _asset(aid, duration=10.0, provider="wikimedia"):
    return {"asset_id": aid, "provider": provider,
            "local_path": f"/vault/{aid}.mp4",
            "source_url": f"https://example.com/{aid}",
            "license": "CC0", "rights_status": "verified_public_domain",
            "checksum": "sha256:" + "a" * 64, "duration": duration}


def _picks(scores=(0.9, 0.8, 0.75)):
    return [{"requirement_id": f"req-{i+1}", "asset_id": f"clip-{i+1}",
             "final_score": s, "decision": "pass",
             "reason": "test pick", "asset": _asset(f"clip-{i+1}")}
            for i, s in enumerate(scores)]


def _segments():
    return [{"asset_id": "narr_s1", "start_seconds": 0.0,
             "end_seconds": 5.0},
            {"asset_id": "narr_s2", "start_seconds": 5.0,
             "end_seconds": 8.0},
            {"asset_id": "narr_s3", "start_seconds": 8.0,
             "end_seconds": 12.0}]


def test_select_moments_records_provenance_and_repetition():
    moments = select_moments(
        _reqs(), _picks(),
        {f"clip-{i+1}": _asset(f"clip-{i+1}") for i in range(3)})
    assert len(moments) == 3
    first = moments[0].to_dict()
    for field in FootageMoment.required_fields():
        assert field in first, field
    assert first["requirement_id"] == "req-1"
    assert first["asset_id"] == "clip-1"
    assert first["provenance"]["license"] == "CC0"
    assert first["repetition_count"] == 0
    assert (first["out_seconds"] - first["in_seconds"]) == 6.0


def test_gap_raises_without_filler():
    picks = _picks()[:2]  # req-3 uncovered
    with pytest.raises(AssemblyGapError) as exc:
        select_moments(_reqs(), picks,
                       {f"clip-{i+1}": _asset(f"clip-{i+1}")
                        for i in range(2)})
    assert "req-3" in str(exc.value)


def test_wrong_scored_pick_is_unusable():
    picks = _picks()
    picks[0]["decision"] = "wrong"
    with pytest.raises(AssemblyGapError):
        select_moments(_reqs(), picks,
                       {f"clip-{i+1}": _asset(f"clip-{i+1}")
                        for i in range(3)})


def _layout_of(timeline):
    return timeline["metadata"]["cuts_layout"]


def test_assemble_timeline_is_schema_valid_ir():
    from schemas.artifacts import validate_artifact
    timeline = assemble_timeline(_reqs(), _picks(), _segments())
    validate_artifact("edit_decisions", timeline)
    assert len(timeline["cuts"]) == 3
    assert timeline["render_runtime"] == "remotion"
    assert timeline["metadata"]["assembly_input_hash"].startswith("sha256:")
    layout = _layout_of(timeline)
    assert layout[0]["start_seconds"] == 0.0
    assert (layout[-1]["end_seconds"]
            == layout[0]["end_seconds"] + 4.0 + 5.0)
    assert (timeline["audio"]["narration"]["segments"]
            == _segments())


def test_deterministic_replay():
    first = assemble_timeline(_reqs(), _picks(), _segments())
    second = assemble_timeline(_reqs(), _picks(), _segments())
    assert first == second
    assert (input_hash(_reqs(), _picks(), _segments())
            == first["metadata"]["assembly_input_hash"])


def test_replace_scene_leaves_others_untouched():
    timeline = assemble_timeline(_reqs(), _picks(), _segments())
    before_cuts = {c["id"]: dict(c) for c in timeline["cuts"]}
    before_layout = {e["scene_id"]: dict(e)
                     for e in _layout_of(timeline)}
    new_moment = FootageMoment(
        requirement_id="req-2", asset_id="clip-9",
        asset_provider="wikimedia", asset_path="/vault/clip-9.mp4",
        in_seconds=1.0, out_seconds=5.0, function="evidence",
        score=0.88, decision="pass",
        provenance={"provider": "wikimedia"}, repetition_count=0)
    revised = replace_scene(timeline, "req-2", new_moment,
                            rationale="sharper strata detail")
    assert len(revised["cuts"]) == 3
    changed = next(c for c in revised["cuts"] if c["id"] == "cut-02")
    assert changed["source"] == "/vault/clip-9.mp4"
    assert (changed["in_seconds"], changed["out_seconds"]) == (1.0, 5.0)
    for cut in revised["cuts"]:
        if cut["id"] == "cut-02":
            continue
        # unrelated scenes: identical source spans, untouched decisions
        assert cut == before_cuts[cut["id"]]
    layout = {e["scene_id"]: e for e in _layout_of(revised)}
    assert layout["scene-01"] == before_layout["scene-01"]
    assert layout["scene-03"]["asset_id"] == "clip-3"
    assert revised["metadata"]["timeline_revision"] == 2
    assert any("scene-02" in entry
               for entry in revised["metadata"]["revision_log"])


def test_revise_scene_trims_in_place():
    timeline = assemble_timeline(_reqs(), _picks(), _segments())
    revised = revise_scene(timeline, "scene-01", out_seconds=4.0,
                           rationale="tighter opening")
    layout = {e["scene_id"]: e for e in _layout_of(revised)}
    first = layout["scene-01"]
    assert (first["end_seconds"] - first["start_seconds"]) == 4.0
    # downstream re-laid gap-free from the new boundary
    assert layout["scene-02"]["start_seconds"] == first["end_seconds"]
    # untouched scene keeps its source span + asset
    third_cut = next(c for c in revised["cuts"] if c["id"] == "cut-03")
    assert third_cut["source"] == "/vault/clip-3.mp4"
    assert (third_cut["in_seconds"],
            third_cut["out_seconds"]) == (0.0, 5.0)


def test_revise_unknown_scene_fails():
    timeline = assemble_timeline(_reqs(), _picks(), _segments())
    with pytest.raises(Exception):
        revise_scene(timeline, "scene-99", out_seconds=2.0)


def test_retime_bumps_revision_without_replacement():
    timeline = assemble_timeline(_reqs(), _picks(), _segments())
    retimed = retime_timeline(timeline)
    assert retimed["metadata"]["timeline_revision"] == 2
    assert retimed["cuts"] == timeline["cuts"]
    assert (retimed["metadata"]["cuts_layout"]
            == timeline["metadata"]["cuts_layout"])
