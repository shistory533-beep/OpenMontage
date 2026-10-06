"""Preview production tests: subset timelines, captions, readiness."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from lib.producer.preview import (
    build_captions,
    build_preview_timeline,
    render_preview,
)


def _decisions():
    cuts = []
    cursor = 0.0
    for i in range(4):
        cuts.append({"id": f"cut-{i+1:02d}", "source": f"/v/c{i}.mp4",
                     "in_seconds": 0.0, "out_seconds": 5.0})
        cursor += 5.0
    return {"version": "1.0", "cuts": cuts,
            "render_runtime": "ffmpeg",
            "audio": {"narration": {"segments": []}},
            "metadata": {"cuts_layout": [
                {"cut_id": f"cut-{i+1:02d}",
                 "scene_id": f"scene-{i+1:02d}",
                 "requirement_id": f"req-{i+1}", "asset_id": f"c{i}",
                 "function": "context",
                 "start_seconds": i * 5.0, "end_seconds": (i + 1) * 5.0}
                for i in range(4)]},
            "shot_decisions": []}


def test_preview_selects_and_relays_gap_free():
    preview = build_preview_timeline(_decisions(), max_scenes=2)
    assert len(preview["cuts"]) == 2
    assert preview["metadata"]["preview"] is True
    assert preview["metadata"]["preview_scene_ids"] == [
        "scene-01", "scene-02"]
    # re-laid end-to-end (positions recomputed from spans)
    assert preview["metadata"]["cuts_layout"][1]["start_seconds"] == 5.0


def test_preview_scene_subset():
    preview = build_preview_timeline(
        _decisions(), scene_ids=["scene-02", "scene-04"])
    assert [c["id"] for c in preview["cuts"]] == ["cut-02", "cut-04"]


def test_preview_unknown_scene_fails():
    with pytest.raises(Exception):
        build_preview_timeline(_decisions(), scene_ids=["scene-99"])


def test_preview_max_seconds():
    preview = build_preview_timeline(_decisions(), max_seconds=12.0)
    assert len(preview["cuts"]) == 2  # 5+5 fits, third would exceed


def test_captions_srt_shape():
    srt = build_captions([{"asset_id": "n1", "start_seconds": 0.0,
                           "end_seconds": 2.5, "text": "The river."}])
    assert "00:00:00,000 --> 00:00:02,500" in srt
    assert "The river." in srt


def _sine_wav(path, seconds=2.0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * 24000)
    frames = struct.pack(
        f"<{n}h",
        *[int(0.4 * 32767 * math.sin(2 * math.pi * 220 * i / 24000))
          for i in range(n)])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(frames)


def test_render_preview_audio_ready(tmp_path):
    _sine_wav(tmp_path / "draft.wav")
    preview = build_preview_timeline(_decisions(), max_scenes=1)

    def renderer(timeline, out_path):
        assert len(timeline["cuts"]) == 1
        _sine_wav(out_path, seconds=2.0)
        return {"duration_seconds": 2.0, "resolution": "640x360"}

    report = render_preview(preview, renderer, tmp_path,
                            name="preview.wav")
    assert report["ready_for_review"] is True
    assert report["has_audio"] is True
    assert report["draft_timeline"] is True
    from schemas.artifacts import validate_artifact
    validate_artifact("preview_report", report)


def test_render_preview_missing_file_fails(tmp_path):
    preview = build_preview_timeline(_decisions(), max_scenes=1)

    def renderer(timeline, out_path):
        return {"duration_seconds": 2.0}

    with pytest.raises(Exception):
        render_preview(renderer and preview, renderer, tmp_path)
