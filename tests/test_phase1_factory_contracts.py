"""Phase 1 factory contracts: artifact registration, validation, durability.

Covers H1/H2/M1/L3/L4/L7 + M3/M4/L5-L6 mapping checks (offline, tmp dirs).
"""

from __future__ import annotations

import pytest

from lib.factory_stages import FACTORY_STAGES


def _manifest_produces() -> dict[str, list[str]]:
    from lib.pipeline_loader import load_pipeline
    manifest = load_pipeline("youtube-documentary")
    return {s["name"]: list(s.get("produces", [])) for s in manifest["stages"]}


def test_every_produced_artifact_has_registered_schema():
    from schemas.artifacts import ARTIFACT_NAMES, load_schema
    produces = _manifest_produces()
    assert len(produces) == 19
    missing = []
    for stage, names in produces.items():
        for name in names:
            if name not in ARTIFACT_NAMES:
                missing.append((stage, name))
            else:
                load_schema(name)  # file must exist + parse
    assert not missing, f"unregistered artifacts: {missing}"
    for name in ("narration_manifest", "footage_report", "audio_mix",
                 "analytics_report"):
        assert name in ARTIFACT_NAMES


def test_episode_schema_map_covers_all_stages():
    from lib.episode_store import ARTIFACT_SCHEMA_MAP
    gaps = [s for s in FACTORY_STAGES if s not in ARTIFACT_SCHEMA_MAP]
    assert not gaps, f"ARTIFACT_SCHEMA_MAP gaps: {gaps}"


def test_empty_artifact_never_done_and_stays_retryable(tmp_path):
    from lib.episode_store import EpisodeStore
    store = EpisodeStore("ep-empty-001", projects_dir=tmp_path)
    store.init("t")
    with pytest.raises(ValueError):
        store.set_artifact("narration", {})
    # store a valid artifact, then confirm invalid never overwrites it
    valid = {"version": "1.0", "tracks": 1, "sections": [{
        "section_id": "s1", "asset_id": "narr_s1",
        "duration_seconds": 10.0}]}
    store.set_artifact("narration", valid)
    before = store.load()["stages"]["narration"]
    with pytest.raises(ValueError):
        store.set_artifact("narration", {})
    after = store.load()["stages"]["narration"]
    assert after["artifact"] == before["artifact"]
    assert after["artifact_version"] == before["artifact_version"]
    # DONE on empty/invalid is blocked; FAILED -> RUNNING stays legal
    store.transition("narration", "RUNNING")
    store.fail("narration", "boom")
    assert store.status()["narration"] == "FAILED"
    store.transition("narration", "RUNNING")
    assert store.status()["narration"] == "RUNNING"


def test_done_blocked_on_invalid_artifact(tmp_path):
    from lib.episode_store import EpisodeStore
    store = EpisodeStore("ep-done-001", projects_dir=tmp_path)
    store.init("t")
    store.transition("research", "RUNNING")
    with pytest.raises(ValueError):
        store.transition("research", "DONE")


def test_producer_rejects_empty_artifact_and_resume_revalidates(tmp_path):
    from lib.producer.producer import ProducerAgent, ProducerHalted
    from tests.test_youtube_documentary_integration import (
        BRIEF, EVIDENCE, FACTCHECK, RESEARCH, SCRIPT, SCENES,
    )

    stage_inputs = {
        "research": RESEARCH, "evidence": EVIDENCE, "script": SCRIPT,
        "storyboard": SCENES, "fact_check": FACTCHECK,
    }

    def ok(payload):
        def run(ctx):
            return dict(payload)
        return run

    valid_narr = {"narration_manifest": {"version": "1.0", "tracks": 1,
        "sections": [{"section_id": "s1", "asset_id": "narr_s1",
                       "duration_seconds": 600.0}]}}
    handlers = {
        "topic": ok({"brief": BRIEF}),
        "fact_check": ok({"factcheck_report": FACTCHECK}),
        "narration": ok({"narration_manifest": {}}),  # empty: must fail
    }
    producer = ProducerAgent("ep-h2-001", projects_dir=tmp_path,
                             handlers=handlers, stage_inputs=stage_inputs,
                             stop_after="narration",
                             approvals={"topic": True, "script": True,
                                        "storyboard": True})
    with pytest.raises(ProducerHalted):
        producer.run()
    assert producer.store.status()["narration"] == "FAILED"

    # Invalid DONE artifacts do not survive resume: tamper then re-run.
    producer2 = ProducerAgent(
        "ep-h2-001", projects_dir=tmp_path, handlers={
            "topic": ok({"brief": BRIEF}),
            "fact_check": ok({"factcheck_report": FACTCHECK}),
            "narration": ok(valid_narr),
        },
        stage_inputs=stage_inputs, stop_after="narration",
        approvals={"topic": True, "script": True, "storyboard": True})
    doc = producer2.store.load()
    doc["stages"]["topic"]["artifact"] = {}
    doc["stages"]["topic"]["state"] = "DONE"
    producer2.store._write_validated(doc)
    report = producer2.run()
    assert "topic" in report["completed"]  # re-ran, not skipped


def test_attempt_counter_increments_and_persists(tmp_path):
    from lib.producer.producer import ProducerAgent
    from tests.test_youtube_documentary_integration import BRIEF

    def ok(payload):
        def run(ctx):
            seen.append(ctx.attempt)
            return dict(payload)
        return run

    seen: list[int] = []
    handlers = {"topic": ok({"brief": BRIEF})}
    producer = ProducerAgent("ep-l3-001", projects_dir=tmp_path,
                             handlers=handlers, approvals={"topic": True},
                             stop_after="topic")
    producer.run()
    assert seen == [1]
    # Second run of a fresh (non-DONE) stage increments; DONE skip does not.
    producer.store.transition("topic", "RUNNING")
    producer.run()
    assert seen == [1, 2]
    assert (tmp_path / "ep-l3-001" / "producer_attempts.json").exists()


def test_approvals_survive_restart(tmp_path):
    from lib.producer.producer import ProducerAgent
    from tests.test_youtube_documentary_integration import BRIEF

    def ok(payload):
        def run(ctx):
            return dict(payload)
        return run

    first = ProducerAgent("ep-m1-001", projects_dir=tmp_path,
                          handlers={"topic": ok({"brief": BRIEF})},
                          stop_after="topic")
    first.record_approval("topic", True)
    assert (tmp_path / "ep-m1-001" / "producer_approvals.json").exists()
    # "Restart": new instance over the same directory keeps the approval.
    second = ProducerAgent("ep-m1-001", projects_dir=tmp_path,
                           handlers={"topic": ok({"brief": BRIEF})},
                           stop_after="topic")
    assert second.approvals.get("topic") is True
    report = second.run()
    assert report["completed"] == ["topic"]
    assert second.store.status()["topic"] == "DONE"


def test_review_and_preview_validate_on_production_paths(tmp_path):
    from lib.producer import review as review_mod
    from schemas.artifacts import validate_artifact

    pkg = review_mod.assemble_review_package(
        episode_id="ep-l4-001", video_path="final.mp4",
        script={"version": "1.0"}, qa_report={"verdict": "PASS"})
    validate_artifact("review_package", pkg)
    with pytest.raises(Exception):
        review_mod.assemble_review_package(
            episode_id="ep-l4-001", video_path="",
            script={}, qa_report={})
    with pytest.raises(Exception):
        review_mod.record_decision(
            tmp_path, episode_id="ep-l4-001", decision="APPROVED",
            approver="", rationale="")
    ready = review_mod.mark_ready_for_review(tmp_path, "ep-l4-001")
    assert ready.decision == "READY_FOR_REVIEW"
    with pytest.raises(Exception):
        review_mod.assert_publish_allowed(tmp_path)
    review_mod.record_decision(
        tmp_path, episode_id="ep-l4-001", decision="APPROVED",
        approver="human", rationale="looks good")
    assert review_mod.assert_publish_allowed(tmp_path).decision == "APPROVED"


def test_preview_report_validates(tmp_path):
    import math
    import struct
    import wave
    from lib.producer.preview import render_preview

    def renderer(timeline, out_path):
        out_path = str(out_path).replace(".mp4", ".wav")
        from pathlib import Path as _Path
        out_path = _Path(out_path)
        n = 24000
        frames = struct.pack(
            f"<{n}h",
            *[int(0.4 * 32767 * math.sin(2 * math.pi * 220 * i / 24000))
              for i in range(n)])
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(frames)
        # render_preview checks workdir/renders/<name>; mirror the wav
        # next to the expected mp4 path is not needed — point the report
        # at the wav by rendering with name="preview.wav".
        return {"duration_seconds": 1.0, "resolution": "1920x1080"}

    report = render_preview({"cuts": [{"id": "c1"}]}, renderer, tmp_path,
                            name="preview.wav")
    assert report["draft_timeline"] is True


def test_documentary_loudness_profile():
    from lib.producer import audio_build, qa
    assert audio_build.DIALOGUE_TARGET_LUFS == -14.0
    assert qa.AUDIO_TARGET_LUFS == -14.0
    assert audio_build.TRUE_PEAK_CEILING_DBTP == -1.0
    assert qa.TRUE_PEAK_CEILING_DBTP == -1.0


def test_renderer_family_swap_refused_and_legacy_pipeline_intact():
    from lib.pipeline_loader import load_pipeline
    from lib.producer.runners import run_render
    from lib.producer.producer import StageContext, CriticalStageError

    legacy = load_pipeline("documentary-montage")
    assert [s["name"] for s in legacy["stages"]] == [
        "idea", "scene_plan", "assets", "edit", "compose"]
    factory = load_pipeline("youtube-documentary")
    editorial = next(s for s in factory["stages"] if s["name"] == "editorial")
    assert "documentary-montage" in str(editorial.get("review_focus", ""))

    ctx = StageContext(
        episode_id="ep-m4-001", stage="render",
        inputs={"edit_decisions": {
            "version": "1.0", "render_runtime": "remotion",
            "renderer_family": "documentary-montage", "cuts": []}},
        workdir="/tmp")
    with pytest.raises(CriticalStageError):
        run_render(ctx, {"renderer_family": "explainer-data"})
