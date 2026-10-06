"""WAV validation + silence rejection (stdlib only, no ffmpeg needed).

The hub writes 16-bit PCM WAV; `wave` parses it exactly. Duration is
measured from frame counts — never predicted from text length. Silence
detection uses peak + mean-absolute energy thresholds calibrated against
real Kokoro output (peak ~0.4, mean_abs ~0.03 for speech): anything three
orders of magnitude below speech energy is rejected. Production code may
only call assert_not_silence to REJECT; test-only silence fixtures are
constructed inline in tests, never emitted by the hub.
"""
from __future__ import annotations

import wave
from pathlib import Path

PEAK_FLOOR = 0.01       # int16-normalized peak below this => silence
MEAN_ABS_FLOOR = 0.0005  # mean absolute amplitude below this => silence


def probe_wav(path: str | Path) -> dict[str, float]:
    """Return measured sample_rate, channels, duration, peak, mean_abs."""
    import struct

    with wave.open(str(path), "rb") as w:
        n_channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        sample_rate = w.getframerate()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)
    if sampwidth != 2:
        raise ValueError(f"expected 16-bit PCM, got {sampwidth * 8}-bit")
    count = n_frames * n_channels
    samples = struct.unpack(f"<{count}h", raw) if count else ()
    peak = max((abs(s) for s in samples), default=0) / 32768.0
    mean_abs = (sum(abs(s) for s in samples) / count / 32768.0) if count else 0.0
    return {"sample_rate": float(sample_rate), "channels": float(n_channels),
            "duration": (n_frames / sample_rate) if sample_rate else 0.0,
            "peak": peak, "mean_abs": mean_abs}


def assert_not_silence(path: str | Path) -> dict[str, float]:
    """Raise SilenceRejectedError when measured audio is silence."""
    from lib.tts_hub.interface import SilenceRejectedError

    info = probe_wav(path)
    if info["duration"] <= 0:
        raise SilenceRejectedError(f"{path}: zero-duration audio rejected")
    if info["peak"] < PEAK_FLOOR or info["mean_abs"] < MEAN_ABS_FLOOR:
        raise SilenceRejectedError(
            f"{path}: silence rejected (peak={info['peak']:.5f}, "
            f"mean_abs={info['mean_abs']:.6f}) — missing narration stays "
            f"missing; it is never filled with silence")
    return info
