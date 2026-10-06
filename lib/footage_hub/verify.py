"""Downloaded-media verification for FootageHub (stdlib + ffprobe/ffmpeg).

Strategy chain (best available wins, always honest about what ran):
  1. ffprobe, when on PATH — full validation: container decodes, streams
     present, width/height/duration/fps measured.
  2. ffmpeg -i stderr parse, when ffmpeg (but no ffprobe) is on PATH —
     stream presence + duration from the demuxer.
  3. stdlib magic sniffing — container recognition + structural checks
     (PNG IHDR, JPEG SOI/EOI, GIF header/trailer, WebP RIFF, MP4 ftyp,
     WebM/Matroska EBML, AVI RIFF). Catches truncation/corruption that
     breaks the container structure. Unknown bytes are NEVER declared
     corrupt (unrecognized != broken); they return verified=False with a
     reason so the manifest row records what was (not) checked.

Proven-corrupt media raises MediaCorruptError (fail closed, retry is
pointless). Anything else returns a report dict with verified True/False
and the measured fields when known. No network, no third-party packages.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any


class MediaCorruptError(ValueError):
    """Downloaded bytes positively fail media validation. Do not retry."""


class MediaProbeError(ValueError):
    """The prober itself failed (missing binary, unparseable output)."""


def orientation_of(width: int, height: int) -> str:
    """landscape | portrait | square | unknown (zero dimension)."""
    try:
        w, h = int(width or 0), int(height or 0)
    except (TypeError, ValueError):
        return "unknown"
    if w <= 0 or h <= 0:
        return "unknown"
    if w == h:
        return "square"
    return "landscape" if w > h else "portrait"


# -- stdlib sniffers --------------------------------------------------------

def _sniff_png(head: bytes, tail: bytes, size: int) -> dict[str, Any] | None:
    if head[:8] != b"\x89PNG\r\n\x1a\n" or len(head) < 33:
        return None
    (length,) = struct.unpack(">I", head[8:12])
    if head[12:16] != b"IHDR" or length != 13:
        raise MediaCorruptError("PNG: bad IHDR chunk")
    w, h = struct.unpack(">II", head[16:24])
    if w == 0 or h == 0 or w > 30000 or h > 30000:
        raise MediaCorruptError(f"PNG: implausible dimensions {w}x{h}")
    if tail[-8:-4] != b"IEND":
        # Truncation positive: structurally incomplete PNG.
        raise MediaCorruptError("PNG: missing IEND trailer (truncated?)")
    return {"container": "png", "width": w, "height": h}


def _sniff_jpeg(head: bytes, tail: bytes, size: int) -> dict[str, Any] | None:
    if head[:2] != b"\xff\xd8":
        return None
    if size < 4:
        raise MediaCorruptError("JPEG: truncated (file < 4 bytes)")
    if tail[-2:] != b"\xff\xd9":
        raise MediaCorruptError("JPEG: missing EOI marker (truncated?)")
    return {"container": "jpeg"}


def _sniff_gif(head: bytes, tail: bytes, size: int) -> dict[str, Any] | None:
    if head[:6] not in (b"GIF87a", b"GIF89a") or len(head) < 13:
        return None
    w, h = struct.unpack("<HH", head[6:10])
    if w == 0 or h == 0:
        raise MediaCorruptError("GIF: zero dimensions")
    if tail[-1:] != b"\x3b":
        raise MediaCorruptError("GIF: missing trailer (truncated?)")
    return {"container": "gif", "width": w, "height": h}


def _sniff_webp(head: bytes, tail: bytes, size: int) -> dict[str, Any] | None:
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WEBP":
        return None
    (riff_size,) = struct.unpack("<I", head[4:8])
    if size < riff_size + 8:
        raise MediaCorruptError("WEBP: RIFF size exceeds file (truncated?)")
    return {"container": "webp"}


def _sniff_mp4(head: bytes, tail: bytes, size: int) -> dict[str, Any] | None:
    if len(head) < 12 or head[4:8] != b"ftyp":
        return None
    if size < 32:
        raise MediaCorruptError("MP4: ftyp present but file < 32 bytes")
    return {"container": "mp4"}


def _sniff_webm(head: bytes, tail: bytes, size: int) -> dict[str, Any] | None:
    if head[:4] != b"\x1a\x45\xdf\xa3":
        return None
    if size < 32:
        raise MediaCorruptError("WebM: EBML header present but file < 32 bytes")
    return {"container": "webm"}


def _sniff_avi(head: bytes, tail: bytes, size: int) -> dict[str, Any] | None:
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"AVI ":
        return None
    return {"container": "avi"}


_SNIFFERS = (_sniff_png, _sniff_jpeg, _sniff_gif, _sniff_webp,
             _sniff_mp4, _sniff_webm, _sniff_avi)


def sniff_container(path: str | Path) -> dict[str, Any]:
    """Stdlib structural check. Returns report; raises MediaCorruptError
    only on positively-broken structure. Unknown bytes => verified False."""
    p = Path(path)
    size = p.stat().st_size
    with open(p, "rb") as f:
        head = f.read(1 << 20)
        f.seek(max(0, size - 256))
        tail = f.read()
    for sniffer in _SNIFFERS:
        hit = sniffer(head, tail, size)
        if hit is not None:
            report = {"verified": True, "method": "magic-sniff", **hit}
            return report
    return {"verified": False, "method": "magic-sniff",
            "reason": "unrecognized container (not proof of corruption)"}


# -- ffprobe / ffmpeg -------------------------------------------------------

def _ffprobe(path: str) -> dict[str, Any]:
    exe = shutil.which("ffprobe")
    if exe is None:
        raise MediaProbeError("ffprobe not on PATH")
    proc = subprocess.run(
        [exe, "-v", "error", "-show_entries",
         "stream=codec_type,width,height,avg_frame_rate,sample_rate,channels"
         ":format=duration,size",
         "-of", "json", path],
        capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise MediaCorruptError(
            f"ffprobe rejected file: {(proc.stderr or '').strip()[-300:]}")
    import json

    try:
        doc = json.loads(proc.stdout or "{}")
    except ValueError as exc:
        raise MediaProbeError(f"ffprobe output unparseable: {exc}") from exc
    streams = doc.get("streams") or []
    if not streams:
        raise MediaCorruptError("ffprobe: no streams decoded")
    report: dict[str, Any] = {"verified": True, "method": "ffprobe",
                              "streams": [s.get("codec_type") for s in streams]}
    for s in streams:
        if s.get("codec_type") == "video":
            report["width"] = int(s.get("width") or 0)
            report["height"] = int(s.get("height") or 0)
            num, _, den = (s.get("avg_frame_rate") or "0/1").partition("/")
            try:
                report["fps"] = float(num) / float(den or 1)
            except (ValueError, ZeroDivisionError):
                report["fps"] = 0.0
        if s.get("codec_type") == "audio":
            report["sample_rate"] = int(s.get("sample_rate") or 0)
            report["channels"] = int(s.get("channels") or 0)
    try:
        report["duration"] = float((doc.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        report["duration"] = 0.0
    return report


def _ffmpeg_parse(path: str) -> dict[str, Any]:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise MediaProbeError("ffmpeg not on PATH")
    proc = subprocess.run([exe, "-hide_banner", "-i", path],
                          capture_output=True, text=True, timeout=60)
    err = proc.stderr or ""
    if "Invalid data found" in err or "moov atom not found" in err:
        raise MediaCorruptError(
            f"ffmpeg demuxer rejected file: {err.strip()[-300:]}")
    report: dict[str, Any] = {"verified": False, "method": "ffmpeg-parse"}
    if "Duration:" in err:
        try:
            dur = err.split("Duration:")[1].split(",")[0].strip()
            h, m, s = dur.split(":")
            report["duration"] = int(h) * 3600 + int(m) * 60 + float(s)
        except (ValueError, IndexError):
            pass
    streams = []
    for line in err.splitlines():
        line = line.strip()
        if line.startswith("Stream ") and ("Video:" in line or "Audio:" in line):
            streams.append("video" if "Video:" in line else "audio")
    if streams:
        report["streams"] = streams
        report["verified"] = True  # demuxer decoded stream tables
    else:
        report["reason"] = "no streams parsed"
    return report


def probe_file(path: str | Path, kind: str = "video") -> dict[str, Any]:
    """Best-available verification. Never returns corrupt-by-default.

    Raises MediaCorruptError only on positive proof of breakage; otherwise
    returns a report with verified True/False + measured fields when known.
    kind is advisory (selects which fields callers should expect).
    """
    _ = kind  # reserved for kind-specific expectations (future)
    target = str(path)
    try:
        return _ffprobe(target)
    except MediaProbeError:
        pass
    try:
        parsed = _ffmpeg_parse(target)
        if parsed.get("verified"):
            return parsed
    except MediaProbeError:
        pass
    # Fall back to stdlib structure checks (always available).
    return sniff_container(target)
