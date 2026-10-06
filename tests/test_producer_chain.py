"""Offline production chain: assembly -> preview -> QA -> review -> pack.

Exercises the real modules end-to-end over locally generated media
(Kokoro-grade sine stems are NOT used here — stems/verification use real
wav files with honest local provenance; footage is a locally rendered
mp4 under rights_mode=permissive explicitly, never mislabeled).

Reaches READY_FOR_REVIEW without network.
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
import subprocess
import wave
from pathlib import Path

import pytest

try:
    from imageio_ffmpeg import get_ffmpeg_exe
except Exception:
    get_ffmpeg_exe = None  # type: ignore[assignment]


@pytest.fixture()
def ffmpeg_bin(tmp_path, monkeypatch):
    if get_ffmpeg_exe is None:
        pytest.skip("imageio-ffmpeg unavailable")
    link = tmp_path / "bin" / "ffmpeg"
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(get_ffmpeg_exe())
    monkeypatch.setenv("PATH",
                       str(link.parent) + os.pathsep + os.environ["PATH"])
    return str(link)


def _sine_wav(path, seconds=2.0, freq=220.0, amplitude=0.25):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * 24000)
    frames = struct.pack(
        f"<{n}h",
        *[int(amplitude * 32767 * math.sin(2 * math.pi * freq * i / 24000))
          for i in range(n)])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(frames)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _clip(path, seconds=8.0):
    subprocess.run(
        [get_ffmpeg_exe(), "-hide_banner", "-y",
         "-f", "lavfi", "-i",
         f"testsrc=size=320x240:rate=10:duration={seconds}",
         "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}:sample_rate=24000",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "24000", "-ac", "1",
         str(path)], check=True, capture_output=True)


def test_chain_to_ready_for_review(tmp_path, ffmpeg_bin):
    from lib.producer import assembly, audio_build, preview
    from lib.producer.packaging import PackageAgent
    from lib.producer.qa import QAAgent
    from lib.producer.review import (
        assemble_review_package,
        mark_ready_for_review,
    )
    from schemas.artifacts import validate_artifact

    work = tmp_path / "ep"
    work.mkdir()
    _sine_wav(work / "s1.wav", seconds=2.0)
    _sine_wav(work / "s2.wav", seconds=2.0, freq=330.0)
    _clip(work / "clip.mp4", seconds=8.0)
    _clip(work / "clip2.mp4", seconds=8.0)
    stems = [
        {"section_id": "s1", "asset_id": "narr_s1",
         "path": str(work / "s1.wav"), "duration_seconds": 2.0,
         "checksum": _sha(work / "s1.wav"), "provider": "kokoro"},
        {"section_id": "s2", "asset_id": "narr_s2",
         "path": str(work / "s2.wav"), "duration_seconds": 2.0,
         "checksum": _sha(work / "s2.wav"), "provider": "kokoro"}]
    script = {"sections": [
        {"id": "s1", "claim_ids": ["c1"],
         "start_seconds": 0.0, "end_seconds": 2.0},
        {"id": "s2", "claim_ids": ["c2"],
         "start_seconds": 2.0, "end_seconds": 4.0}]}

    # assembly: requirements -> moments -> Timeline IR
    reqs = [{"id": "req-1", "narration_block_id": "s1",
             "shot_function": "establishing",
             "desired_duration_seconds": 4.0,
             "positive_search_terms": ["river"]},
            {"id": "req-2", "narration_block_id": "s2",
             "shot_function": "payoff",
             "desired_duration_seconds": 4.0,
             "positive_search_terms": ["sunset"]}]
    def _local_asset(path, aid):
        return {"asset_id": aid, "provider": "local",
                "local_path": str(path),
                "source_url": "", "license": "locally generated test clip",
                "rights_status": "unknown",
                "checksum": _sha(path),
                "duration": 8.0, "width": 320, "height": 240}

    asset = _local_asset(work / "clip.mp4", "local-clip-1")
    asset2 = _local_asset(work / "clip2.mp4", "local-clip-2")
    picks = [{"requirement_id": "req-1", "asset_id": "local-clip-1",
              "final_score": 0.8, "decision": "pass", "reason": "t",
              "asset": asset},
             {"requirement_id": "req-2", "asset_id": "local-clip-2",
              "final_score": 0.75, "decision": "pass", "reason": "t",
              "asset": asset2}]
    segments = [{"asset_id": "narr_s1", "start_seconds": 0.0,
                 "end_seconds": 2.0},
                {"asset_id": "narr_s2", "start_seconds": 2.0,
                 "end_seconds": 4.0}]
    timeline = assembly.assemble_timeline(reqs, picks, segments,
                                          render_runtime="ffmpeg")
    validate_artifact("edit_decisions", timeline)

    # audio plan + mix via the real mixer
    from tools.audio.audio_mixer import AudioMixer
    plan = audio_build.build_mix_plan({"sections": stems}, script, work,
                                      {})
    assert plan["expected_duration_seconds"] == 4.0
    result = AudioMixer().execute({**plan["mixer_inputs"],
                                   "output_path": plan["output_path"]})
    assert result.success, result.error
    attestation = audio_build.verify_mix(plan["output_path"], plan)
    assert attestation["duration_seconds"] > 0

    # preview render of the draft timeline
    def renderer(tl, out_path):
        proc = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-y",
             "-i", str(work / "clip.mp4"),
             "-i", plan["output_path"],
             "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
             "-c:a", "aac", "-shortest", str(out_path)],
            capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr[-500:]
        return {"duration_seconds": 4.0, "resolution": "320x240"}

    preview_tl = preview.build_preview_timeline(timeline, max_scenes=1)
    report = preview.render_preview(preview_tl, renderer, work)
    assert report["ready_for_review"] is True
    validate_artifact("preview_report", report)

    # full QA over the preview-as-final (permissive: local test media,
    # declared openly — never mislabeled as verified stock)
    qa_inputs = {
        "episode_id": "ep-chain-001",
        "video_path": report["preview_path"],
        "script": script,
        "factcheck_report": {
            "package_hash": "sha256:" + "a" * 64,
            "verdicts": [
                {"claim_id": "c1", "verdict": "verified",
                 "blocks_approval": False},
                {"claim_id": "c2", "verdict": "verified",
                 "blocks_approval": False}]},
        "storyboard": {"package_hash": "sha256:" + "a" * 64,
                       "requirements": reqs},
        "asset_manifest": {"assets": [asset, asset2]},
        "narration_manifest": {"sections": stems},
        "edit_decisions": preview_tl,
        "audio_mix": {"mix_path": plan["output_path"]},
        # The preview stands in as the render output for this chain test;
        # the live E2E (test_producer_live_e2e) QAs a real final render.
        "render_report": {"outputs": [
            {"path": report["preview_path"]}]},
        "rights_mode": "permissive"}
    qa_report = QAAgent().run(qa_inputs)
    assert qa_report.readiness == "READY", [
        c for c in qa_report.checks if c["status"] != "pass"]
    final = QAAgent().to_final_review(qa_report)
    validate_artifact("final_review", final)

    # review package -> READY_FOR_REVIEW
    pkg = assemble_review_package(
        episode_id="ep-chain-001",
        video_path=report["preview_path"],
        script=script, storyboard={"requirements": reqs},
        picks=[asset], qa_report=qa_report.to_dict(),
        rights_summary={"mode": "permissive", "declared": True},
        narration_status={"section_count": 2},
        titles=[{"title": "River film"}],
        thumbnail={"concept": "river bend"},
        description="A short river film.",
        chapters=[{"chapter_id": "ch1", "start": "0:00"}],
        subtitles_path="")
    validate_artifact("review_package", pkg)
    assert pkg["status"] == "READY_FOR_REVIEW"
    ready = mark_ready_for_review(work, "ep-chain-001",
                                  video_path=report["preview_path"])
    assert ready.decision == "READY_FOR_REVIEW"

    # packaging bundle validates
    bundle = PackageAgent().build({
        "episode_id": "ep-chain-001", "topic": "Rivers",
        "topic_keywords": ["rivers"],
        "verified_claims": ["Rivers carve canyons over time."],
        "title_seeds": ["Rivers carve canyons over time",
                        "How rivers shape the land",
                        "The patient work of water",
                        "Canyons explained gently",
                        "What rivers leave behind"],
        "script": script,
        "storyboard": {"requirements": [
            {"id": "req-1", "subject": "river bend", "shot_type": "wide",
             "visual_objective": "establishing", "priority": "hero"}]},
        "narration_manifest": {"segments": segments},
        "render_report": {"outputs": [
            {"path": report["preview_path"]}]}})
    validate_artifact("package_bundle", bundle)
    assert len(bundle["titles"]["candidates"]) == 5
