"""Audio production: verification + mix planning over the existing pipeline.

Uses audio_mixer (full_mix) and TTS Hub provenance — nothing is
reimplemented. Verification is pure-Python where possible (wav decode,
silence rejection) with ffmpeg-backed loudness/true-peak measurement
when a binary is available; estimates are always labeled as estimates
and never presented as measurements.

Hard rules:
- every script section has exactly one verified narration stem;
- missing stems fail (never padded with silence, silently or otherwise);
- narration assets must carry TTS Hub provenance; synthetic/test audio
  (fixture paths, synthetic markers, silence) is rejected, not mixed.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any

from lib.tts_hub.audio import assert_not_silence, probe_wav

DIALOGUE_TARGET_LUFS = -16.0
LOUDNESS_TOLERANCE_LUFS = 3.0
TRUE_PEAK_CEILING_DBTP = -1.0
COVERAGE_TOLERANCE_SECONDS = 1.0

# Provenance markers that prove a stem is NOT production narration.
# NOTE: deliberately no bare "test" substring — pytest tmp dirs contain
# "test_..." and must not false-positive. Fixture media is caught by the
# explicit fixtures/synthetic/mock markers plus provenance + silence.
_SYNTHETIC_SOURCE_TOOLS = {"test", "synthetic", "sine", "fixture", "mock",
                           "stub", "placeholder"}
_SYNTHETIC_PATH_HINTS = ("tests/fixtures", "test_fixtures", "/fixtures/",
                         "fixture_media", "synthetic", "mock_")


class AudioBuildError(ValueError):
    """Base class: audio stage refused (fail closed)."""


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def verify_narration(script_sections: list[dict[str, Any]],
                     narration_manifest: dict[str, Any]) -> dict[str, Any]:
    """Check timing, coverage, and provenance of narration stems.

    Returns an attestation fragment {section_count, total_seconds,
    coverage_seconds, stems:[...]}. Raises AudioBuildError on any gap.
    """
    stems = narration_manifest.get("sections") or []
    if not script_sections:
        raise AudioBuildError("Narration needs script.sections.")
    if not stems:
        raise AudioBuildError(
            "Narration manifest has no sections: missing stems fail "
            "the stage (never padded with silence).")
    by_section: dict[str, list[dict[str, Any]]] = {}
    for stem in stems:
        by_section.setdefault(str(stem.get("section_id", "")), []).append(
            stem)
    checked = []
    problems = []
    for section in script_sections:
        sid = str(section.get("id", ""))
        matches = by_section.get(sid, [])
        if len(matches) != 1:
            problems.append(
                f"section {sid!r}: expected exactly 1 narration asset, "
                f"found {len(matches)}")
            continue
        stem = matches[0]
        duration = float(stem.get("duration_seconds", 0) or 0)
        if duration <= 0:
            problems.append(f"section {sid!r}: zero-duration stem")
            continue
        _check_provenance(stem, problems)
        path = stem.get("path", "")
        if path and Path(path).exists():
            try:
                assert_not_silence(path)
            except Exception as exc:
                problems.append(
                    f"section {sid!r}: stem failed audio check: {exc}")
        checked.append({"section_id": sid,
                        "asset_id": stem.get("asset_id", ""),
                        "duration_seconds": duration,
                        "path": path,
                        "file_present": bool(path)
                        and Path(path).exists()})
    extra = [s for sid, group in by_section.items() for s in group
             if sid not in {str(x.get("id", "")) for x in script_sections}]
    if extra:
        problems.append(
            f"{len(extra)} narration asset(s) reference unknown sections.")
    if problems:
        raise AudioBuildError("Narration verification failed: "
                              + "; ".join(problems))
    total = round(sum(s["duration_seconds"] for s in checked), 3)
    return {"section_count": len(checked), "total_seconds": total,
            "coverage_seconds": total, "stems": checked}


def _check_provenance(stem: dict[str, Any], problems: list[str]) -> None:
    """Reject synthetic/test audio masquerading as narration."""
    tool = str(stem.get("source_tool", "") or stem.get("provider", ""))
    path = str(stem.get("path", ""))
    if tool.split(":")[0].lower() in _SYNTHETIC_SOURCE_TOOLS:
        problems.append(
            f"section {stem.get('section_id')!r}: synthetic source_tool "
            f"{tool!r} rejected (no synthetic test audio in production)")
    lowered = path.lower()
    if any(hint in lowered for hint in _SYNTHETIC_PATH_HINTS):
        problems.append(
            f"section {stem.get('section_id')!r}: fixture path {path!r} "
            f"rejected (no fixture media in production)")
    if not stem.get("checksum"):
        problems.append(
            f"section {stem.get('section_id')!r}: stem carries no checksum "
            f"(provenance required)")


def build_mix_plan(narration_manifest: dict[str, Any],
                   script: dict[str, Any],
                   workdir: Path,
                   cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Produce audio_mixer full_mix inputs + expected verification values."""
    cfg = cfg or {}
    attestation = verify_narration(script.get("sections") or [],
                                   narration_manifest)
    tracks = [{"path": s["path"], "role": "speech",
               "start_seconds": 0.0} for s in attestation["stems"]]
    # Lay stems end-to-end in script order.
    cursor = 0.0
    for track, stem in zip(tracks, attestation["stems"]):
        track["start_seconds"] = round(cursor, 3)
        cursor += stem["duration_seconds"]
    music_path = cfg.get("music_path")
    if music_path:
        tracks.append({"path": music_path, "role": "music", "volume": 0.2,
                       "start_seconds": 0.0})
    out_path = workdir / "assets" / "audio" / "final_mix.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mixer_inputs: dict[str, Any] = {
        "operation": "full_mix", "tracks": tracks,
        "ducking": {"enabled": bool(music_path),
                    "music_volume_during_speech": 0.15,
                    "attack_ms": 200, "release_ms": 500},
        "normalize": True,
        "loudnorm_target": float(cfg.get("loudness_target",
                                         DIALOGUE_TARGET_LUFS)),
    }
    return {"mixer_inputs": mixer_inputs,
            "output_path": str(out_path),
            "expected_duration_seconds": round(cursor, 3),
            "narration": attestation}


def verify_mix(mix_path: str | Path,
               plan: dict[str, Any]) -> dict[str, Any]:
    """Verify the rendered mix. Returns the audio_mix attestation."""
    mix_path = Path(mix_path)
    if not mix_path.exists():
        raise AudioBuildError(f"Mix not found: {mix_path}")
    info = assert_not_silence(mix_path)  # never ship a silent master
    expected = float(plan.get("expected_duration_seconds", 0) or 0)
    if expected and abs(info["duration"] - expected) > (
            COVERAGE_TOLERANCE_SECONDS + 0.5):
        raise AudioBuildError(
            f"Mix duration {info['duration']:.2f}s diverges from planned "
            f"{expected:.2f}s.")
    loudness = measure_loudness(mix_path)
    target = float((plan.get("mixer_inputs") or {}).get(
        "loudnorm_target", DIALOGUE_TARGET_LUFS))
    integrated = loudness.get("integrated_lufs")
    if integrated is not None and abs(integrated - target) > (
            LOUDNESS_TOLERANCE_LUFS):
        raise AudioBuildError(
            f"Mix loudness {integrated:.1f} LUFS misses target {target} "
            f"(tolerance ±{LOUDNESS_TOLERANCE_LUFS}).")
    peak = loudness.get("true_peak_dbtp")
    if peak is not None and peak > TRUE_PEAK_CEILING_DBTP:
        raise AudioBuildError(
            f"Mix true peak {peak:.1f} dBTP exceeds ceiling "
            f"{TRUE_PEAK_CEILING_DBTP} dBTP.")
    return {"version": "1.0",
            "mix_path": str(mix_path),
            "duration_seconds": round(info["duration"], 3),
            "sample_rate": int(info["sample_rate"]),
            "channels": int(info["channels"]),
            "loudness_db": integrated,
            "true_peak_dbtp": peak,
            "loudness_measured": loudness.get("measured", False),
            "narration": plan.get("narration", {}),
            "expected_duration_seconds": expected}


def measure_loudness(mix_path: str | Path) -> dict[str, Any]:
    """Integrated LUFS + true peak. ffmpeg-measured when available.

    Without ffmpeg, falls back to a pure-Python RMS estimate clearly
    labeled measured=False (planning-grade only, never a pass claim).
    """
    exe = _ffmpeg()
    if exe is not None:
        try:
            return _loudness_ffmpeg(exe, mix_path)
        except Exception:
            pass  # fall through to the labeled estimate
    return _loudness_estimate(mix_path)


def _loudness_ffmpeg(exe: str, mix_path: str | Path) -> dict[str, Any]:
    proc = subprocess.run(
        [exe, "-hide_banner", "-i", str(mix_path), "-map", "0:a",
         "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120)
    text = proc.stderr or ""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise AudioBuildError("ffmpeg loudnorm produced no JSON.")
    data = json.loads(text[start:end + 1])
    return {"integrated_lufs": float(data["input_i"]),
            "true_peak_dbtp": float(data["input_tp"]),
            "lra": float(data.get("input_lra", 0.0)),
            "measured": True}


def _loudness_estimate(mix_path: str | Path) -> dict[str, Any]:
    """RMS-based LUFS approximation. measured=False: never a pass claim."""
    with wave.open(str(mix_path), "rb") as wav:
        n_channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        rate = wav.getframerate()
        n_frames = wav.getnframes()
        raw = wav.readframes(n_frames)
    if sampwidth != 2 or n_frames == 0:
        return {"integrated_lufs": None, "true_peak_dbtp": None,
                "measured": False, "reason": "unsupported estimate input"}
    samples = struct.unpack(f"<{n_frames * n_channels}h", raw)
    peak = max(abs(s) for s in samples) / 32768.0
    mean_sq = sum((s / 32768.0) ** 2 for s in samples) / len(samples)
    import math
    rms = math.sqrt(mean_sq)
    approx_lufs = 20 * math.log10(rms) - 0.691 if rms > 0 else None
    approx_peak = 20 * math.log10(peak) if peak > 0 else None
    return {"integrated_lufs": (round(approx_lufs, 1)
                                if approx_lufs is not None else None),
            "true_peak_dbtp": (round(approx_peak, 1)
                               if approx_peak is not None else None),
            "measured": False,
            "reason": "ffmpeg unavailable: RMS estimate, planning-grade"}
