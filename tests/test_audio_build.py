"""Audio production tests: narration verify, mix plan, mix verify."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from lib.producer.audio_build import (
    build_mix_plan,
    measure_loudness,
    verify_mix,
    verify_narration,
)


def _sine_wav(path, seconds=1.0, freq=220.0, rate=24000, amplitude=0.4):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    frames = struct.pack(
        f"<{n}h",
        *[int(amplitude * 32767
              * math.sin(2 * math.pi * freq * i / rate))
          for i in range(n)])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)


def _silence_wav(path, seconds=1.0, rate=24000):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)


def _script():
    return {"sections": [
        {"id": "s1", "text": "The river carved the canyon.",
         "start_seconds": 0.0, "end_seconds": 2.0},
        {"id": "s2", "text": "Deep time, written in stone.",
         "start_seconds": 2.0, "end_seconds": 4.0}]}


def _manifest(tmp_path, silence_s2=False):
    _sine_wav(tmp_path / "s1.wav", seconds=2.0)
    if silence_s2:
        _silence_wav(tmp_path / "s2.wav", seconds=2.0)
    else:
        _sine_wav(tmp_path / "s2.wav", seconds=2.0, freq=330.0)
    return {"tracks": 2,
            "sections": [
                {"section_id": "s1", "asset_id": "narr_s1",
                 "path": str(tmp_path / "s1.wav"),
                 "duration_seconds": 2.0,
                 "checksum": "sha256:" + "a" * 64,
                 "provider": "kokoro"},
                {"section_id": "s2", "asset_id": "narr_s2",
                 "path": str(tmp_path / "s2.wav"),
                 "duration_seconds": 2.0,
                 "checksum": "sha256:" + "b" * 64,
                 "provider": "kokoro"}]}


def test_verify_narration_timing_and_coverage(tmp_path):
    att = verify_narration(_script()["sections"],
                           _manifest(tmp_path))
    assert att["section_count"] == 2
    assert att["total_seconds"] == 4.0
    assert all(s["file_present"] for s in att["stems"])


def test_missing_section_fails_no_silence_pad(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["sections"] = manifest["sections"][:1]
    with pytest.raises(Exception) as exc:
        verify_narration(_script()["sections"], manifest)
    assert "s2" in str(exc.value)


def test_silent_stem_fails(tmp_path):
    with pytest.raises(Exception) as exc:
        verify_narration(_script()["sections"],
                         _manifest(tmp_path, silence_s2=True))
    assert "s2" in str(exc.value)


def test_fixture_provenance_rejected(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["sections"][0]["path"] = (
        "tests/fixtures/some/stem.wav")
    manifest["sections"][0]["provider"] = "test"
    with pytest.raises(Exception) as exc:
        verify_narration(_script()["sections"], manifest)
    assert "fixture" in str(exc.value).lower()


def test_missing_checksum_rejected(tmp_path):
    manifest = _manifest(tmp_path)
    del manifest["sections"][0]["checksum"]
    with pytest.raises(Exception):
        verify_narration(_script()["sections"], manifest)


def test_build_mix_plan_lays_stems_end_to_end(tmp_path):
    plan = build_mix_plan(_manifest(tmp_path), _script(), tmp_path, {})
    tracks = plan["mixer_inputs"]["tracks"]
    assert tracks[0]["start_seconds"] == 0.0
    assert tracks[1]["start_seconds"] == 2.0
    assert plan["mixer_inputs"]["operation"] == "full_mix"
    assert plan["expected_duration_seconds"] == 4.0


def test_verify_mix_rejects_silence(tmp_path):
    _silence_wav(tmp_path / "mix.wav", seconds=4.0)
    plan = {"expected_duration_seconds": 4.0, "mixer_inputs": {},
            "narration": {}}
    with pytest.raises(Exception):
        verify_mix(tmp_path / "mix.wav", plan)


def test_verify_mix_rejects_missing_file(tmp_path):
    with pytest.raises(Exception):
        verify_mix(tmp_path / "nope.wav", {})


def test_measure_loudness_labels_estimates(tmp_path):
    _sine_wav(tmp_path / "tone.wav", seconds=2.0)
    loud = measure_loudness(tmp_path / "tone.wav")
    assert "integrated_lufs" in loud and "true_peak_dbtp" in loud
    assert "measured" in loud  # True (ffmpeg) or labeled estimate
