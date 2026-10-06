"""QA agent tests: verdict mapping, all six areas, adversarial fixtures."""

from __future__ import annotations

import hashlib
import math
import os
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from lib.producer.qa import QAAgent, probe_streams

try:
    from imageio_ffmpeg import get_ffmpeg_exe
except Exception:  # pragma: no cover - minimal envs skip video tests
    get_ffmpeg_exe = None  # type: ignore[assignment]


@pytest.fixture()
def ffmpeg_bin(tmp_path, monkeypatch):
    """Put a real ffmpeg on PATH (imageio static build)."""
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


def _sine_wav(path, seconds=2.0, freq=220.0, rate=24000, amplitude=0.4):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    frames = struct.pack(
        f"<{n}h",
        *[int(amplitude * 32767 * math.sin(2 * math.pi * freq * i / rate))
          for i in range(n)])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)


def _silence_wav(path, seconds=2.0, rate=24000):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _clip_mp4(path, seconds=4.0):
    """Real container: testsrc video + tone audio (not production footage,
    a probe target for technical checks)."""
    assert get_ffmpeg_exe is not None
    subprocess.run(
        [get_ffmpeg_exe(), "-hide_banner", "-y",
         "-f", "lavfi", "-i",
         f"testsrc=size=320x240:rate=10:duration={seconds}",
         "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}:sample_rate=24000",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "24000", "-ac", "1",
         str(path)], check=True, capture_output=True)


def _inputs(tmp_path, **over):
    _sine_wav(tmp_path / "s1.wav", seconds=2.0)
    _sine_wav(tmp_path / "s2.wav", seconds=2.0, freq=330.0)
    _sine_wav(tmp_path / "mix.wav", seconds=4.0, freq=330.0,
              amplitude=0.25)
    clip = tmp_path / "clip.mp4"
    _clip_mp4(clip)
    mix_sum = _sha(tmp_path / "mix.wav")
    clip_sum = _sha(clip)
    base = {
        "episode_id": "ep-qa-001",
        "video_path": str(clip),
        "script": {"sections": [
            {"id": "s1", "claim_ids": ["c1"],
             "start_seconds": 0.0, "end_seconds": 2.0},
            {"id": "s2", "claim_ids": ["c2"],
             "start_seconds": 2.0, "end_seconds": 4.0}]},
        "factcheck_report": {"package_hash": "sha256:" + "a" * 64,
                             "verdicts": [
            {"claim_id": "c1", "verdict": "verified",
             "blocks_approval": False},
            {"claim_id": "c2", "verdict": "verified",
             "blocks_approval": False}]},
        "storyboard": {"package_hash": "sha256:" + "a" * 64,
                       "requirements": [
                           {"id": "req-1"}, {"id": "req-2"}]},
        "asset_manifest": {"assets": [
            {"id": "clip-1", "license": "CC0",
             "rights_status": "verified_public_domain",
             "creator": "Wikimedia", "attribution": "Wikimedia Commons",
             "local_path": str(clip),
             "checksum": clip_sum}]},
        "narration_manifest": {"sections": [
            {"section_id": "s1", "asset_id": "narr_s1",
             "path": str(tmp_path / "s1.wav"), "duration_seconds": 2.0,
             "checksum": "sha256:" + "a" * 64, "provider": "kokoro"},
            {"section_id": "s2", "asset_id": "narr_s2",
             "path": str(tmp_path / "s2.wav"), "duration_seconds": 2.0,
             "checksum": "sha256:" + "b" * 64, "provider": "kokoro"}]},
        "edit_decisions": {
            "version": "1.0", "render_runtime": "ffmpeg",
            "cuts": [{"id": "cut-01", "source": str(tmp_path / "mix.wav"),
                      "in_seconds": 0.0, "out_seconds": 4.0}],
            "metadata": {"cuts_layout": [
                {"cut_id": "cut-01", "scene_id": "scene-01",
                 "requirement_id": "req-1", "asset_id": "clip-1",
                 "function": "establishing",
                 "start_seconds": 0.0, "end_seconds": 4.0},
                {"cut_id": "cut-02", "scene_id": "scene-02",
                 "requirement_id": "req-2", "asset_id": "clip-1",
                 "function": "payoff",
                 "start_seconds": 4.0, "end_seconds": 8.0}]}},
        "audio_mix": {"mix_path": str(tmp_path / "mix.wav")},
        "render_report": {"outputs": [
            {"path": str(clip), "format": "mp4",
             "resolution": "320x240", "duration_seconds": 4.0}]},
        "rights_mode": "strict",
    }
    base.update(over)
    return base


def _areas(report):
    areas = {}
    for raw in report.checks:
        areas.setdefault(raw["area"], []).append(raw["status"])
    return areas


# -- verdict mapping -------------------------------------------------------


def test_clean_inputs_pass_and_ready(tmp_path, ffmpeg_bin):
    report = QAAgent().run(_inputs(tmp_path))
    assert report.verdict == "PASS"
    assert report.readiness == "READY"
    assert report.checks_skipped == 0  # PASS needs zero skipped checks
    final = QAAgent().to_final_review(report)
    assert final["status"] == "pass"
    assert final["output_path"].endswith("clip.mp4")
    from schemas.artifacts import validate_artifact
    validate_artifact("final_review", final)


def test_unreadable_video_blocks(tmp_path):
    report = QAAgent().run(_inputs(tmp_path,
                                   video_path=str(tmp_path / "nope.mp4")))
    assert report.verdict == "FAIL"
    assert report.readiness == "BLOCKED"  # critical failure: BLOCKED


def test_silent_stem_blocks(tmp_path):
    _silence_wav(tmp_path / "s1.wav", seconds=2.0)
    report = QAAgent().run(_inputs(tmp_path))
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_missing_stem_file_blocks(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["narration_manifest"]["sections"][0]["path"] = str(
        tmp_path / "gone.wav")
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_blocking_claim_blocks(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["factcheck_report"]["verdicts"][1] = {
        "claim_id": "c2", "verdict": "contradicted",
        "blocks_approval": True}
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_unmapped_claim_blocks(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["script"]["sections"][0]["claim_ids"] = ["ghost"]
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_unknown_rights_fail_strict_mode(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["asset_manifest"]["assets"][0]["rights_status"] = "unknown"
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_unknown_rights_warn_permissive(tmp_path, ffmpeg_bin):
    inputs = _inputs(tmp_path, rights_mode="permissive")
    inputs["asset_manifest"]["assets"][0]["rights_status"] = "unknown"
    assert QAAgent().run(inputs).readiness == "READY"


def test_restricted_rights_always_fail(tmp_path):
    inputs = _inputs(tmp_path, rights_mode="permissive")
    inputs["asset_manifest"]["assets"][0]["rights_status"] = "restricted"
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_missing_attribution_fails(tmp_path):
    inputs = _inputs(tmp_path)
    asset = inputs["asset_manifest"]["assets"][0]
    asset["license"] = "CC-BY 4.0"
    asset["attribution"] = ""
    asset["creator"] = ""
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


# -- adversarial integrity ---------------------------------------------------


def test_fixture_media_rejected(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["asset_manifest"]["assets"][0]["local_path"] = (
        "tests/fixtures/footage_hub/clip.mp4")
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_synthetic_audio_provenance_rejected(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["narration_manifest"]["sections"][0]["provider"] = "sine"
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_broken_cut_reference_fails(tmp_path):
    inputs = _inputs(tmp_path)
    (inputs["edit_decisions"]["metadata"]["cuts_layout"][0]
     ["asset_id"]) = "ghost-clip"
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_missing_requirement_coverage_fails(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["storyboard"]["requirements"].append({"id": "req-99"})
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_stale_checksum_fails(tmp_path):
    inputs = _inputs(tmp_path)
    (inputs["asset_manifest"]["assets"][0]["checksum"]
     ) = "sha256:" + "0" * 64
    report = QAAgent().run(inputs)
    assert report.verdict == "FAIL" and report.readiness == "BLOCKED"


def test_warn_still_ready(tmp_path, ffmpeg_bin):
    # overused asset => continuity warn (non-blocking) => WARN/READY
    inputs = _inputs(tmp_path)
    layout = inputs["edit_decisions"]["metadata"]["cuts_layout"]
    layout.append(dict(layout[0], cut_id="cut-03", scene_id="scene-03",
                       start_seconds=8.0, end_seconds=12.0))
    inputs["edit_decisions"]["cuts"].append(
        {"id": "cut-03", "source": str(tmp_path / "mix.wav"),
         "in_seconds": 0.0, "out_seconds": 4.0})
    report = QAAgent().run(inputs)
    assert report.verdict == "WARN"
    assert report.readiness == "READY"  # non-critical: still READY


def test_probe_unreadable_without_prober(tmp_path):
    missing = tmp_path / "gone.mp4"
    assert probe_streams(missing)["readable"] is False
