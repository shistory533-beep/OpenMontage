"""Preview production: a reviewable draft before the final render.

A preview is a shortened render (selected scenes), a draft timeline, the
current audio, and captions. It exists so a human can judge pacing and
coverage cheaply. A preview is NEVER labeled production-ready: only a
passing QA verdict on the final render earns that word
(see lib.producer.qa).

READY_FOR_REVIEW is set on the preview report when the preview file
exists, is technically sound (probe passes), and carries non-silent
audio. Full QA still gates packaging.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from lib.tts_hub.audio import assert_not_silence, probe_wav

Renderer = Callable[[dict[str, Any], Path], dict[str, Any]]
# (preview_timeline, output_path) -> {"duration_seconds","resolution",...}


class PreviewError(ValueError):
    """Base class: preview refused (fail closed)."""


def build_preview_timeline(edit_decisions: dict[str, Any], *,
                           scene_ids: list[str] | None = None,
                           max_scenes: int | None = None,
                           max_seconds: float | None = None
                           ) -> dict[str, Any]:
    """Subset cuts preserving order; re-laid end-to-end (gap-free draft)."""
    cuts = list(edit_decisions.get("cuts") or [])
    if not cuts:
        raise PreviewError("Preview needs edit_decisions with cuts.")
    layout = {(e.get("cut_id")): e for e in
              ((edit_decisions.get("metadata") or {}).get("cuts_layout")
               or [])}

    def _scene_of(cut: dict[str, Any]) -> str:
        if cut.get("scene_id"):
            return str(cut["scene_id"])
        entry = layout.get(cut.get("id", ""), {})
        return str(entry.get("scene_id", ""))

    if scene_ids is not None:
        wanted = set(scene_ids)
        picked = [c for c in cuts if _scene_of(c) in wanted]
        missing = wanted - {_scene_of(c) for c in picked}
        if missing:
            raise PreviewError(f"Preview scene ids not found: {missing}")
        cuts = picked
    if max_scenes is not None:
        cuts = cuts[:max_scenes]
    def _span_of(cut: dict[str, Any]) -> float:
        start, end = cut.get("start_seconds"), cut.get("end_seconds")
        if start is None or end is None:
            return round(cut["out_seconds"] - cut["in_seconds"], 3)
        return round(end - start, 3)

    if max_seconds is not None:
        kept: list[dict[str, Any]] = []
        total = 0.0
        for cut in cuts:
            span = _span_of(cut)
            if kept and total + span > max_seconds:
                break
            kept.append(cut)
            total += span
        cuts = kept
    if not cuts:
        raise PreviewError("Preview selection is empty.")
    relaid, cursor = [], 0.0
    for cut in cuts:
        span = _span_of(cut)
        entry = dict(cut)
        entry["start_seconds"] = round(cursor, 3)
        entry["end_seconds"] = round(cursor + span, 3)
        relaid.append(entry)
        cursor += span
    preview = dict(edit_decisions)
    preview["cuts"] = relaid
    metadata = dict(edit_decisions.get("metadata") or {})
    metadata["preview"] = True
    metadata["preview_scene_ids"] = [_scene_of(c) for c in cuts]
    preview["metadata"] = metadata
    return preview


def build_captions(narration_segments: list[dict[str, Any]]) -> str:
    """Draft SRT captions from narration segment timings."""
    lines = []
    for i, seg in enumerate(narration_segments, 1):
        lines.append(str(i))
        lines.append(f"{_srt_ts(seg.get('start_seconds', 0))} --> "
                     f"{_srt_ts(seg.get('end_seconds', 0))}")
        lines.append(str(seg.get("text", seg.get("asset_id", ""))))
        lines.append("")
    return "\n".join(lines)


def _srt_ts(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds or 0) * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def render_preview(preview_timeline: dict[str, Any],
                   renderer: Renderer,
                   workdir: Path,
                   *,
                   name: str = "preview.mp4") -> dict[str, Any]:
    """Render the draft via the injected renderer; verify the file."""
    out_path = workdir / "renders" / name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        info = renderer(preview_timeline, out_path) or {}
    except Exception as exc:
        raise PreviewError(f"Preview render failed: {exc}") from exc
    if not out_path.exists():
        raise PreviewError(
            f"Preview renderer reported success but {out_path} is missing.")
    if out_path.suffix.lower() == ".wav":
        probe = probe_wav(out_path)
        duration = float(info.get("duration_seconds")
                         or probe["duration"])
        try:
            assert_not_silence(out_path)
            narration_ok: bool | None = True
        except Exception:
            narration_ok = False
        has_audio = True
    else:
        from lib.producer.qa import probe_streams
        streams = probe_streams(out_path, prober=None)
        if not streams.get("readable"):
            raise PreviewError(
                f"Preview file failed probe: {out_path}")
        duration = float(info.get("duration_seconds")
                         or streams.get("duration_seconds", 0.0) or 0.0)
        has_audio = "audio" in (streams.get("streams") or [])
        narration_ok = _preview_audio_ok(out_path) if has_audio else False
    ready = bool(duration > 0 and has_audio and narration_ok)
    report = {"version": "1.0",
              "preview_path": str(out_path),
              "duration_seconds": round(duration, 3),
              "resolution": info.get("resolution", ""),
              "draft_timeline": True,
              "has_audio": has_audio,
              "narration_audio_verified": narration_ok,
              "ready_for_review": ready,
              "captions_path": ""}
    return report


def _preview_audio_ok(path: Path) -> bool | None:
    """True = extracted track non-silent; None = unverifiable here."""
    import shutil
    import subprocess
    import tempfile

    exe = shutil.which("ffmpeg")
    if exe is None:
        return None  # no extractor: cannot verify, must not claim pass
    with tempfile.TemporaryDirectory() as tmp:
        wav = str(Path(tmp) / "preview_audio.wav")
        proc = subprocess.run(
            [exe, "-hide_banner", "-y", "-i", str(path), "-vn",
             "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1", wav],
            capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return False
        try:
            assert_not_silence(wav)
            return True
        except Exception:
            return False
