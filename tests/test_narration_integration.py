"""Narration integration: real narration must reach the final MP4.

Traces the production chain with the existing architecture (no new lanes):
  script sections (NarrationBlock)
    -> TTS Hub synthesize_cached (TTS, content-hash cached, verified audio)
    -> mapper.to_manifest_asset (AudioAsset: asset_manifest narration asset)
    -> mapper.section_timeline (AudioTimeline: edit segments + mixer tracks)
    -> AudioMixer.full_mix (AudioMaster: ducked + normalized mix)
    -> VideoCompose compose(audio_path=mix) (FFmpeg/render: AAC mux)
    -> final MP4

The offline layer (always runs, fake sine-wave provider = real audio)
fails if production narration ever becomes silence. The ffmpeg layer
(skipif, same convention as tests/tools/test_audio_mixer_*) proves the
mix and the muxed MP4 carry non-silent narration. Silence fixtures exist
only inline in tests; production code paths are scanned for silence
generation and must contain none.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from lib.tts_hub import mapper
from lib.tts_hub.audio import assert_not_silence, probe_wav
from lib.tts_hub.cache import synthesize_cached
from lib.tts_hub.contracts import SpeechResult, TTSStatus

SECTIONS = [
    {"id": "s1", "text": "The river carved this canyon over six million years."},
    {"id": "s2", "text": "Every layer of rock is a page in deep time."},
    {"id": "s3", "text": "And the water is still writing."},
]

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg required")


def _sine_wav(path, seconds=1.0, freq=220.0, rate=24000, amplitude=0.4):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    frames = struct.pack(f"<{n}h",
                         *[int(amplitude * 32767 * math.sin(2 * math.pi * freq * i / rate))
                           for i in range(n)])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(frames)


class _FakeProvider:
    name = "fake-sine"
    model = "sine-24000-mono"
    sample_rate = 24000
    channels = 1

    def is_available(self): return True

    def voices(self): return [{"id": "sine", "language": "en"}]

    def synthesize(self, text, voice, out_path, language="en", **options):
        import hashlib

        if not text.strip():
            from lib.tts_hub.interface import EmptyTextError
            raise EmptyTextError("empty")
        # Section-length audio: duration scales with text (like real TTS).
        _sine_wav(out_path, seconds=max(1.0, len(text) / 40.0))
        info = assert_not_silence(out_path)
        with open(out_path, "rb") as f:
            checksum = "sha256:" + hashlib.sha256(f.read()).hexdigest()
        return SpeechResult(provider="fake-sine", model=self.model,
                            voice=voice, language=language, input_text=text,
                            output_audio_path=str(out_path),
                            sample_rate=24000, channels=1,
                            duration=info["duration"], alignment=[],
                            generation_metadata={}, checksum=checksum,
                            status=TTSStatus.DONE)


def _narrate(tmp_path) -> list[tuple[SpeechResult, str]]:
    """Script sections -> verified TTS Hub results (production call path)."""
    prov = _FakeProvider()
    out = []
    for i, sec in enumerate(SECTIONS):
        res = synthesize_cached(prov, sec["text"], "sine",
                                str(tmp_path / "narr" / f"{sec['id']}.wav"),
                                cache_dir=tmp_path / "tts_cache")
        assert res.status in ("done", "cached")
        assert res.duration > 0 and res.checksum.startswith("sha256:")
        out.append((res, sec["id"]))
    return out


# -- offline: narration assets + timeline carry real (non-silent) audio -------

def test_narration_assets_carry_verified_audio(tmp_path):
    narrated = _narrate(tmp_path)
    assets = [mapper.to_manifest_asset(res, f"narr_{sid}", "scene_1", sid)
              for res, sid in narrated]
    assert len(assets) == len(SECTIONS)
    for asset in assets:
        assert asset["type"] == "narration"
        assert asset["duration_seconds"] > 0
        assert asset["provider"] == "fake-sine"
        info = assert_not_silence(asset["path"])  # REGRESSION: fails on silence
        assert abs(info["duration"] - asset["duration_seconds"]) < 0.05


def test_audio_timeline_segments_cover_narration_in_order(tmp_path):
    narrated = _narrate(tmp_path)
    cursor, placed = 0.0, []
    for res, sid in narrated:
        placed.append((res, f"narr_{sid}", cursor))
        cursor += res.duration
    segments, tracks = mapper.section_timeline(placed)
    assert len(segments) == len(tracks) == len(SECTIONS)
    for seg, track, (res, _sid) in zip(segments, tracks, narrated):
        assert track["role"] == "speech"
        assert Path(track["path"]).is_file()
        # Every mixer track is independently verified non-silent: if the
        # hub ever emits silence, this fails instead of shipping it.
        info = assert_not_silence(track["path"])
        assert info["duration"] > 0
        assert seg["end_seconds"] - seg["start_seconds"] > 0
    total = segments[-1]["end_seconds"] - segments[0]["start_seconds"]
    assert abs(total - sum(r.duration for r, _ in narrated)) < 0.01


def test_no_silence_fallback_in_production_narration_paths():
    """Forbid hidden synthetic narration fallbacks at the source level.

    anullsrc/aevalsrc are legitimate ONLY for container padding of
    audio-less clips (video_stitch, video_compose mux prep) — they must
    never appear in any TTS/narration production path.
    """
    repo = Path(__file__).resolve().parent.parent
    narration_files = list((repo / "lib" / "tts_hub").glob("*.py")) + [
        repo / "tools" / "audio" / "tts_hub.py",
        repo / "tools" / "audio" / "tts_selector.py",
        repo / "tools" / "audio" / "audio_mixer.py",
    ]
    offenders = [str(p) for p in narration_files if p.is_file()
                 and any(tok in p.read_text(encoding="utf-8")
                         for tok in ("anullsrc", "aevalsrc",
                                     "sine=frequency", "flite", "espeak"))]
    assert offenders == [], f"synthetic narration fallback found: {offenders}"
    from tools.audio.tts_hub import TTSHub
    assert TTSHub.supports.get("silence_fallback") is False


# -- ffmpeg layer: mix + mux -----------------------------------------------------

def _mix_tracks(tmp_path, placed) -> str:
    from tools.audio.audio_mixer import AudioMixer

    tracks = [{"path": res.output_audio_path, "role": "speech",
               "start_seconds": start} for res, _, start in placed]
    out = tmp_path / "mix" / "master.wav"
    result = AudioMixer().execute({"operation": "full_mix", "tracks": tracks,
                                   "normalize": False,
                                   "output_path": str(out)})
    assert result.success, result.error
    return str(out)


@needs_ffmpeg
def test_full_mix_carries_narration_not_silence(tmp_path):
    narrated = _narrate(tmp_path)
    cursor, placed = 0.0, []
    for res, sid in narrated:
        placed.append((res, f"narr_{sid}", cursor))
        cursor += res.duration
    master = _mix_tracks(tmp_path, placed)
    info = assert_not_silence(master)  # REGRESSION: silent master fails here
    expected = sum(r.duration for r, _ in narrated)
    assert abs(info["duration"] - expected) < 0.5
    assert int(info["sample_rate"]) > 0 and int(info["channels"]) >= 1


@needs_ffmpeg
def test_final_mp4_contains_real_narration(tmp_path):
    """End-to-end: narration -> mix -> muxed MP4, verified independently."""
    from tools.video.video_compose import VideoCompose

    narrated = _narrate(tmp_path)
    cursor, placed = 0.0, []
    for res, sid in narrated:
        placed.append((res, f"narr_{sid}", cursor))
        cursor += res.duration
    total = sum(r.duration for r, _ in narrated)
    master = _mix_tracks(tmp_path, placed)

    # Silent source clip (brauchbarer Stand-in: no audio stream of its own).
    clip = tmp_path / "clip.mp4"
    subprocess.run([FFMPEG, "-y", "-f", "lavfi",
                    "-i", f"testsrc=size=640x360:rate=30:duration={total:.2f}",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264",
                    str(clip)], check=True, capture_output=True)
    edit = {"version": "1.0", "render_runtime": "ffmpeg",
            "cuts": [{"id": "c1", "source": str(clip),
                      "in_seconds": 0, "out_seconds": total}]}
    final = tmp_path / "final.mp4"
    result = VideoCompose().execute({"operation": "compose",
                                     "edit_decisions": edit,
                                     "audio_path": master,
                                     "output_path": str(final),
                                     "preset": "ultrafast"})
    assert result.success, result.error
    assert result.data["has_mixed_audio"] is True
    assert final.is_file()

    # Independent verification (ffmpeg -i stderr = ffprobe equivalent).
    probe = subprocess.run([FFMPEG, "-hide_banner", "-i", str(final)],
                           capture_output=True, text=True)
    stderr = probe.stderr
    assert "Audio:" in stderr, f"no audio stream in final MP4:\n{stderr}"
    assert "Video:" in stderr
    # Extract the muxed audio and prove it is the narration, not silence.
    extracted = tmp_path / "extracted.wav"
    subprocess.run([FFMPEG, "-y", "-i", str(final), "-vn",
                    "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1",
                    str(extracted)], check=True, capture_output=True)
    info = assert_not_silence(extracted)
    assert info["duration"] > total * 0.9  # narration spans the timeline
