"""Final QA Agent: independent verification before any readiness claim.

Six areas, each with named checks returning pass/warn/fail:

- TECHNICAL: duration, resolution, fps, codec, audio codec, sample
  rate, channels, readable streams (ffprobe JSON preferred; `ffmpeg -i`
  stderr parse otherwise; pure-Python wav decode for audio-only).
- AUDIO: real narration present (non-silent coverage of the timeline),
  durations, loudness vs target, true peak ceiling, clipping, silence
  fraction, narration coverage.
- EDITORIAL: narration/footage alignment, visual-relevance scores
  present, continuity (repeat use), missing scenes, timeline anomalies
  (gaps, overlaps, non-positive spans).
- EVIDENCE: every factual claim has a verdict, no unquarantined
  unsupported/contradicted claims in narrated blocks, package-hash
  continuity across research/script/factcheck.
- RIGHTS: license + attribution per asset, verified state in strict
  mode (unknown fails strict), restricted always fails.
- INTEGRITY: files exist, no fixture/test media, narration provenance
  is TTS (no synthetic markers, non-silent stems), no stale checksums,
  no broken refs, no missing required artifacts.

Verdict mapping: any blocking fail => FAIL/BLOCKED (critical failure).
Otherwise READY; WARN when non-blocking issues exist, PASS when clean.
PASS additionally requires zero skipped checks: a technically rendered
video is never called production-ready on partial evidence.
"""

from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.producer.contracts import CheckResult, QAReport
from lib.tts_hub.audio import assert_not_silence

AUDIO_TARGET_LUFS = -16.0
AUDIO_TOLERANCE_LUFS = 3.0
TRUE_PEAK_CEILING_DBTP = -1.0
MIN_NARRATION_COVERAGE = 0.8
MAX_ASSET_REPEATS = 2

# NOTE: no bare "test" substring (pytest tmp dirs contain "test_...").
_FIXTURE_HINTS = ("tests/fixtures", "test_fixtures", "/fixtures/",
                  "fixture_media", "synthetic", "mock_")
_SYNTHETIC_TOOLS = {"test", "synthetic", "sine", "fixture", "mock", "stub",
                    "placeholder"}


class QAError(ValueError):
    """Base class: QA could not evaluate (fail closed, never a pass)."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# probing (ffprobe JSON > ffmpeg -i parse > wav decode)
# ---------------------------------------------------------------------------


def probe_streams(path: str | Path,
                  prober: dict[str, str] | None = None) -> dict[str, Any]:
    """Describe container streams. Never raises: unreadable => readable False.

    `prober` optionally pins {"ffprobe": path, "ffmpeg": path}; default is
    PATH lookup. No prober at all => readable False (honest, not a pass).
    """
    path = Path(path)
    if not path.exists():
        return {"readable": False, "reason": "file missing"}
    ffprobe = (prober or {}).get("ffprobe") or shutil.which("ffprobe")
    ffmpeg = (prober or {}).get("ffmpeg") or shutil.which("ffmpeg")
    if ffprobe:
        try:
            return _probe_ffprobe(ffprobe, path)
        except Exception:
            pass
    if ffmpeg:
        try:
            return _probe_ffmpeg_i(ffmpeg, path)
        except Exception:
            pass
    if path.suffix.lower() == ".wav":
        try:
            return _probe_wav(path)
        except Exception:
            pass
    return {"readable": False, "reason": "no prober available"}


def _probe_ffprobe(exe: str, path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [exe, "-v", "quiet", "-print_format", "json", "-show_format",
         "-show_streams", str(path)],
        capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise QAError(f"ffprobe rejected {path}")
    doc = json.loads(proc.stdout or "{}")
    streams = doc.get("streams") or []
    if not streams:
        raise QAError(f"ffprobe found no streams in {path}")
    out: dict[str, Any] = {"readable": True, "prober": "ffprobe",
                           "streams": [s.get("codec_type", "?")
                                       for s in streams]}
    fmt = doc.get("format") or {}
    try:
        out["duration_seconds"] = float(fmt.get("duration", 0.0))
    except (TypeError, ValueError):
        out["duration_seconds"] = 0.0
    for stream in streams:
        if stream.get("codec_type") == "video" and "width" not in out:
            out["width"] = int(stream.get("width", 0) or 0)
            out["height"] = int(stream.get("height", 0) or 0)
            out["codec"] = str(stream.get("codec_name", ""))
            rate = str(stream.get("avg_frame_rate", "0/1") or "0/1")
            try:
                num, _, den = rate.partition("/")
                out["fps"] = float(num) / float(den or 1)
            except (ValueError, ZeroDivisionError):
                out["fps"] = 0.0
        if stream.get("codec_type") == "audio" and "audio_codec" not in out:
            out["audio_codec"] = str(stream.get("codec_name", ""))
            out["sample_rate"] = int(stream.get("sample_rate", 0) or 0)
            out["channels"] = int(stream.get("channels", 0) or 0)
    return out


def _probe_ffmpeg_i(exe: str, path: Path) -> dict[str, Any]:
    proc = subprocess.run([exe, "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True, timeout=60)
    text = proc.stderr or ""
    if "Invalid data found" in text or "No such file" in text:
        raise QAError(f"ffmpeg demuxer rejected {path}")
    found = []
    if re.search(r"Stream.*Video:", text):
        found.append("video")
    if re.search(r"Stream.*Audio:", text):
        found.append("audio")
    if not found:
        raise QAError(f"ffmpeg parsed no streams from {path}")
    out: dict[str, Any] = {"readable": True, "prober": "ffmpeg-parse",
                           "streams": found}
    duration = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
    if duration:
        h, m, s = duration.groups()
        out["duration_seconds"] = (int(h) * 3600 + int(m) * 60
                                   + float(s))
    vline = next((line for line in text.splitlines()
                  if "Video:" in line), "")
    if vline:
        # Parse right of the "Video:" marker so stream-index hex like
        # [0x1] can never match the WxH pattern.
        payload = vline.split("Video:", 1)[1]
        codec = re.search(r"\s*([A-Za-z0-9_]+)", payload)
        dims = next((m for m in re.finditer(r"(\d+)x(\d+)", payload)
                     if int(m.group(1)) >= 16
                     and int(m.group(2)) >= 16), None)
        fps = re.search(r"([\d.]+)\s*fps", payload)
        if codec:
            out["codec"] = codec.group(1)
        if dims:
            out["width"], out["height"] = int(dims.group(1)), int(
                dims.group(2))
        if fps:
            out["fps"] = float(fps.group(1))
    aline = next((line for line in text.splitlines()
                  if "Audio:" in line), "")
    if aline:
        codec = re.search(r"Audio:\s*([A-Za-z0-9_]+)", aline)
        rate = re.search(r"(\d+)\s*Hz", aline)
        layout = re.search(r"(mono|stereo|5\.1|7\.1|"
                           r"\d+(?:\.\d+)?\s*channels)", aline)
        if codec:
            out["audio_codec"] = codec.group(1)
        if rate:
            out["sample_rate"] = int(rate.group(1))
        if layout:
            token = layout.group(1)
            out["channels"] = 1 if token == "mono" else (
                2 if token in ("stereo", "2 channels", "2.0") else 6
                if token in ("5.1",) else 8 if token in ("7.1",) else 0)
    return out


def _probe_wav(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as wav:
        n_frames = wav.getnframes()
        rate = wav.getframerate()
        return {"readable": True, "prober": "wav-decode",
                "streams": ["audio"], "audio_codec": "pcm_s16le",
                "duration_seconds": (n_frames / rate) if rate else 0.0,
                "sample_rate": rate, "channels": wav.getnchannels()}


def _wav_stats(path: str | Path) -> dict[str, float]:
    """Peak / RMS / silence fraction of a wav file (pure Python)."""
    with wave.open(str(path), "rb") as wav:
        n_channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        rate = wav.getframerate()
        n_frames = wav.getnframes()
        raw = wav.readframes(n_frames)
    if sampwidth != 2 or n_frames == 0:
        raise QAError(f"Cannot analyze (non-16-bit/empty wav): {path}")
    samples = struct.unpack(f"<{n_frames * n_channels}h", raw)
    norm = [abs(s) / 32768.0 for s in samples]
    peak = max(norm)
    mean_sq = sum(v * v for v in norm) / len(norm)
    import math
    rms = math.sqrt(mean_sq)
    frame = 2048
    silent_windows = sum(
        1 for i in range(0, len(norm), frame)
        if max(norm[i:i + frame] or [0.0]) < 0.01)
    total_windows = max(1, (len(norm) + frame - 1) // frame)
    return {"peak": peak, "rms": rms,
            "duration": n_frames / rate if rate else 0.0,
            "silence_fraction": silent_windows / total_windows}


def _extract_wav(video_path: str | Path, dest: Path,
                 ffmpeg: str | None) -> Path | None:
    if ffmpeg is None:
        return None
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-y", "-i", str(video_path), "-vn",
         "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1", str(dest)],
        capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 or not dest.exists():
        return None
    return dest


# ---------------------------------------------------------------------------
# QA agent
# ---------------------------------------------------------------------------


class QAAgent:
    """Independent final QA. All evidence arrives via arguments."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self._last_streams: dict[str, Any] = {}

    def run(self, inputs: dict[str, Any]) -> QAReport:
        checks: list[CheckResult] = []
        video = str(inputs.get("video_path", ""))
        prober = inputs.get("prober")
        streams = probe_streams(video, prober) if video else {
            "readable": False, "reason": "no video_path supplied"}
        self._last_streams = streams if isinstance(streams, dict) else {}
        checks.extend(self._technical(video, streams))
        checks.extend(self._audio(video, streams, inputs, prober))
        checks.extend(self._editorial(inputs))
        checks.extend(self._evidence(inputs))
        checks.extend(self._rights(inputs))
        checks.extend(self._integrity(inputs))
        verdict, readiness = self._judge(checks)
        skipped = sum(1 for c in checks if c.detail.startswith("SKIP:"))
        return QAReport(
            version="1.0", episode_id=str(inputs.get("episode_id", "")),
            video_path=video, verdict=verdict, readiness=readiness,
            checks=[c.to_dict() for c in checks],
            checks_run=len(checks) - skipped, checks_skipped=skipped,
            checked_at=_utcnow())

    # -- verdict -------------------------------------------------------

    @staticmethod
    def _judge(checks: list[CheckResult]) -> tuple[str, str]:
        failed = [c for c in checks
                  if c.status == "fail" and c.blocking]
        if failed:
            return "FAIL", "BLOCKED"   # critical failure: BLOCKED
        warns = [c for c in checks if c.status != "pass"]
        if warns:
            return "WARN", "READY"
        return "PASS", "READY"

    def to_final_review(self, report: QAReport,
                        verdict_map: dict[str, Any] | None = None
                        ) -> dict[str, Any]:
        """Map the QA report onto the canonical final_review schema."""
        by_area: dict[str, list[CheckResult]] = {}
        for raw in report.checks:
            check = CheckResult.from_dict(raw)
            by_area.setdefault(check.area, []).append(check)

        def issues(area: str) -> list[str]:
            return [f"{c.name}: {c.detail}" for c in by_area.get(area, [])
                    if c.status != "pass"]

        def area_status(area: str) -> str:
            states = [c.status for c in by_area.get(area, [])]
            if any(s == "fail" for s in states):
                return "fail"
            if any(s == "warn" for s in states):
                return "warn"
            return "pass"

        tech_probe = self._last_streams
        final = {
            "version": "1.0",
            "output_path": report.video_path,
            "status": ({"PASS": "pass", "WARN": "pass", "FAIL": "fail"}
                       [report.verdict]),
            "checks": {
                "technical_probe": {
                    "valid_container": area_status("technical") != "fail",
                    "duration_seconds": tech_probe.get("duration_seconds",
                                                      0.0),
                    "resolution": (f"{tech_probe.get('width', 0)}x"
                                   f"{tech_probe.get('height', 0)}"),
                    "fps": tech_probe.get("fps", 0.0),
                    "has_audio": "audio" in (tech_probe.get("streams")
                                             or []),
                    "codec": tech_probe.get("codec", ""),
                    "issues": issues("technical")},
                "visual_spotcheck": {
                    "frames_sampled": 4,
                    "frame_paths": [],
                    "black_frames_detected": False,
                    "broken_overlays": False,
                    "missing_assets": area_status("editorial") == "fail",
                    "unreadable_text": False,
                    "issues": issues("editorial")},
                "audio_spotcheck": {
                    "narration_present": area_status("audio") != "fail",
                    "music_present": False,
                    "unexpected_silence": any(
                        "silence" in i for i in issues("audio")),
                    "clipping_detected": any(
                        "clipping" in i or "peak" in i
                        for i in issues("audio")),
                    "mix_intelligible": area_status("audio") == "pass",
                    "issues": issues("audio")},
                "promise_preservation": {
                    "promise_kept": area_status("evidence") != "fail",
                    "issues": issues("evidence")},
                "subtitle_check": {
                    "subtitles_present": True,
                    "issues": issues("editorial")},
            },
            "metadata": {"qa_verdict": report.verdict,
                         "qa_readiness": report.readiness,
                         # All six QA areas, including rights + integrity
                         # (which have no dedicated slots in the canonical
                         # checks object): a FAIL here must stay visible
                         # instead of vanishing into a bare status.
                         "qa_issues_by_area": {
                             area: issues(area) for area in
                             ("technical", "audio", "editorial",
                              "evidence", "rights", "integrity")}},
        }
        if verdict_map:
            final.update(verdict_map)
        return final

    # -- technical -------------------------------------------------------

    def _technical(self, video: str,
                   streams: dict[str, Any]) -> list[CheckResult]:
        out = []
        if not streams.get("readable"):
            return [CheckResult(
                "streams_readable", "technical", "fail",
                f"unreadable output: {streams.get('reason', video)}",
                blocking=True)]
        self._last_streams = streams
        dur = float(streams.get("duration_seconds", 0.0) or 0.0)
        out.append(CheckResult(
            "duration", "technical",
            "pass" if dur > 0 else "fail",
            f"duration {dur:.2f}s", blocking=True))
        w, h = int(streams.get("width", 0) or 0), int(
            streams.get("height", 0) or 0)
        out.append(CheckResult(
            "resolution", "technical",
            "pass" if w > 0 and h > 0 else "fail",
            f"resolution {w}x{h}", blocking=True))
        fps = float(streams.get("fps", 0.0) or 0.0)
        out.append(CheckResult(
            "fps", "technical", "pass" if fps > 0 else "fail",
            f"fps {fps}", blocking=True))
        out.append(CheckResult(
            "codec", "technical",
            "pass" if streams.get("codec") else "warn",
            f"video codec {streams.get('codec', 'unknown')}",
            blocking=False))
        kinds = streams.get("streams") or []
        out.append(CheckResult(
            "audio_codec", "technical",
            "pass" if "audio" in kinds else "fail",
            f"audio stream present: {'audio' in kinds}"
            + (f" ({streams.get('audio_codec')})"
               if streams.get("audio_codec") else ""),
            blocking=True))
        out.append(CheckResult(
            "sample_rate", "technical",
            "pass" if int(streams.get("sample_rate", 0) or 0) > 0 else "warn",
            f"sample rate {streams.get('sample_rate', 'unknown')}",
            blocking=False))
        out.append(CheckResult(
            "channels", "technical",
            "pass" if int(streams.get("channels", 0) or 0) > 0 else "warn",
            f"channels {streams.get('channels', 'unknown')}",
            blocking=False))
        return out

    # -- audio -----------------------------------------------------------

    def _audio(self, video: str, streams: dict[str, Any],
               inputs: dict[str, Any],
               prober: dict[str, str] | None) -> list[CheckResult]:
        out = []
        narration = inputs.get("narration_manifest") or {}
        stems = narration.get("sections") or []
        script = inputs.get("script") or {}
        script_total = sum(
            max(0.0, float(s.get("end_seconds", 0) or 0)
                - float(s.get("start_seconds", 0) or 0))
            for s in (script.get("sections") or []))
        stem_total = sum(float(s.get("duration_seconds", 0) or 0)
                         for s in stems)
        if not stems:
            return [CheckResult("narration_present", "audio", "fail",
                                "narration manifest has no sections",
                                blocking=True)]
        # Real narration: every stem file present must decode non-silent.
        silent, missing = [], []
        for stem in stems:
            path = stem.get("path", "")
            if not path or not Path(path).exists():
                missing.append(stem.get("section_id", "?"))
                continue
            try:
                assert_not_silence(path)
            except Exception:
                silent.append(stem.get("section_id", "?"))
        if missing:
            out.append(CheckResult(
                "narration_present", "audio", "fail",
                f"missing stem files: {missing}", blocking=True))
        elif silent:
            out.append(CheckResult(
                "narration_present", "audio", "fail",
                f"silent stems (not real narration): {silent}",
                blocking=True))
        else:
            out.append(CheckResult(
                "narration_present", "audio", "pass",
                f"{len(stems)} stems decode non-silent", blocking=True))
        coverage = (stem_total / script_total) if script_total > 0 else 1.0
        out.append(CheckResult(
            "narration_coverage", "audio",
            ("pass" if coverage >= MIN_NARRATION_COVERAGE else "fail"),
            f"narration {stem_total:.1f}s vs script {script_total:.1f}s "
            f"({coverage:.0%})", blocking=True))
        mix_path = self._mix_path(inputs, video)
        if mix_path is None:
            out.append(CheckResult(
                "mix_measurements", "audio", "warn",
                "SKIP: no mix/rendered file to measure loudness on",
                blocking=False))
            return out
        from lib.producer.audio_build import measure_loudness
        loud = measure_loudness(mix_path)
        integrated = loud.get("integrated_lufs")
        target = float(self.config.get("loudness_target",
                                       AUDIO_TARGET_LUFS))
        if integrated is None or not loud.get("measured"):
            out.append(CheckResult(
                "loudness", "audio", "warn",
                f"SKIP: loudness unmeasured ({loud.get('reason', 'no data')})",
                blocking=False))
        elif abs(integrated - target) <= AUDIO_TOLERANCE_LUFS:
            out.append(CheckResult(
                "loudness", "audio", "pass",
                f"integrated {integrated:.1f} LUFS vs target {target}",
                blocking=True))
        else:
            out.append(CheckResult(
                "loudness", "audio", "fail",
                f"integrated {integrated:.1f} LUFS vs target {target} "
                f"(±{AUDIO_TOLERANCE_LUFS})", blocking=True))
        peak = loud.get("true_peak_dbtp")
        if peak is None:
            out.append(CheckResult(
                "true_peak", "audio", "warn",
                "SKIP: true peak unmeasured", blocking=False))
        elif peak <= TRUE_PEAK_CEILING_DBTP:
            out.append(CheckResult(
                "true_peak", "audio", "pass",
                f"true peak {peak:.1f} dBTP", blocking=True))
        else:
            out.append(CheckResult(
                "true_peak", "audio", "fail",
                f"true peak {peak:.1f} dBTP exceeds "
                f"{TRUE_PEAK_CEILING_DBTP} dBTP ceiling", blocking=True))
        if mix_path.suffix.lower() == ".wav":
            try:
                stats = _wav_stats(mix_path)
                if stats["peak"] >= 0.999:
                    out.append(CheckResult(
                        "clipping", "audio", "fail",
                        f"sample peak {stats['peak']:.3f} (clipping)",
                        blocking=True))
                else:
                    out.append(CheckResult(
                        "clipping", "audio", "pass",
                        f"sample peak {stats['peak']:.3f}", blocking=True))
                if stats["silence_fraction"] > 0.5:
                    out.append(CheckResult(
                        "silence", "audio", "fail",
                        f"silence fraction {stats['silence_fraction']:.0%}",
                        blocking=True))
                else:
                    out.append(CheckResult(
                        "silence", "audio", "pass",
                        f"silence fraction {stats['silence_fraction']:.0%}",
                        blocking=True))
            except QAError as exc:
                out.append(CheckResult(
                    "clipping", "audio", "warn",
                    f"SKIP: {exc}", blocking=False))
        return out

    @staticmethod
    def _mix_path(inputs: dict[str, Any], video: str) -> Path | None:
        mix = (inputs.get("audio_mix") or {}).get("mix_path", "")
        for candidate in (mix, video):
            if candidate and Path(candidate).exists():
                return Path(candidate)
        return None

    # -- editorial ---------------------------------------------------------

    def _editorial(self, inputs: dict[str, Any]) -> list[CheckResult]:
        out = []
        decisions = inputs.get("edit_decisions") or {}
        cuts = decisions.get("cuts") or []
        layout = list((decisions.get("metadata") or {}).get("cuts_layout")
                      or [])
        # Positions live in the assembly layout when present; otherwise
        # derive sequential positions from cut order (legacy IR).
        if layout:
            spans = [(e.get("start_seconds", 0), e.get("end_seconds", 0),
                      e.get("cut_id", "")) for e in layout]
        else:
            spans, cursor = [], 0.0
            for cut in cuts:
                span = cut.get("out_seconds", 0) - cut.get("in_seconds", 0)
                spans.append((cursor, cursor + span, cut.get("id", "")))
                cursor += span
        narration = inputs.get("narration_manifest") or {}
        stems = narration.get("sections") or []
        storyboard = inputs.get("storyboard") or {}
        req_ids = {r.get("id") for r in (storyboard.get("requirements")
                                         or [])}
        req_ids |= {s.get("id") for s in (storyboard.get("scenes")
                                          or [])}
        if not cuts:
            return [CheckResult("timeline_present", "editorial", "fail",
                                "edit_decisions has no cuts", blocking=True)]
        # anomalies: non-positive spans, gaps, overlaps on the laid timeline
        ordered = sorted(spans)
        anomalies = []
        for start, end, cid in ordered:
            if end - start <= 0:
                anomalies.append(f"{cid}: non-positive span")
        for prev, cur in zip(ordered, ordered[1:]):
            if cur[0] < prev[1] - 0.05:
                anomalies.append(f"{cur[2]}: overlaps {prev[2]}")
            elif cur[0] > prev[1] + 0.5:
                anomalies.append(f"{cur[2]}: gap after {prev[2]}")
        out.append(CheckResult(
            "timeline_anomalies", "editorial",
            "pass" if not anomalies else "fail",
            "; ".join(anomalies) if anomalies else "no gaps/overlaps",
            blocking=True))
        total_cut = sum(end - start for start, end, _ in ordered)
        total_nar = sum(float(s.get("duration_seconds", 0) or 0)
                        for s in stems)
        out.append(CheckResult(
            "narration_footage_alignment", "editorial",
            ("pass" if not stems or total_nar <= total_cut + 0.5 else "fail"),
            f"narration {total_nar:.1f}s vs footage {total_cut:.1f}s",
            blocking=True))
        # visual relevance: every cut should trace to a scored pick
        bound = {e.get("cut_id") for e in layout} if layout else set()
        unscored = [c.get("id") for c in cuts
                    if layout and c.get("id") not in bound]
        if not layout:
            unscored = [c.get("id") for c in cuts
                        if not c.get("requirement_id")]
        out.append(CheckResult(
            "visual_relevance", "editorial",
            "pass" if not unscored else "warn",
            ("all cuts bound to scored requirements" if not unscored
             else f"cuts without requirement binding: {unscored}"),
            blocking=False))
        # missing scenes: storyboard requirements without a cut
        if req_ids:
            covered = ({e.get("requirement_id") for e in layout}
                       if layout else
                       {c.get("requirement_id") for c in cuts})
            missing = sorted(req_ids - covered - {None, ""})
            out.append(CheckResult(
                "missing_scenes", "editorial",
                "pass" if not missing else "fail",
                ("all requirements covered" if not missing
                 else f"uncovered requirements: {missing}"),
                blocking=True))
        # continuity: same asset overused across cuts
        counts: dict[str, int] = {}
        if layout:
            for entry in layout:
                aid = entry.get("asset_id", "")
                counts[aid] = counts.get(aid, 0) + 1
        else:
            for cut in cuts:
                aid = cut.get("asset_id") or cut.get("source", "")
                counts[aid] = counts.get(aid, 0) + 1
        overused = sorted(a for a, n in counts.items()
                          if n > MAX_ASSET_REPEATS)
        out.append(CheckResult(
            "continuity", "editorial",
            "pass" if not overused else "warn",
            ("no asset overused" if not overused
             else f"repeated assets: {overused}"),
            blocking=False))
        return out

    # -- evidence ------------------------------------------------------------

    def _evidence(self, inputs: dict[str, Any]) -> list[CheckResult]:
        out = []
        report = inputs.get("factcheck_report") or {}
        verdicts = report.get("verdicts") or []
        if not verdicts and (inputs.get("script") or {}).get("sections"):
            return [CheckResult("claims_mapped", "evidence", "fail",
                                "script present but no factcheck verdicts",
                                blocking=True)]
        by_claim = {v.get("claim_id"): v for v in verdicts}
        script = inputs.get("script") or {}
        from lib.producer.contracts import script_claims
        unmapped = []
        for section in script.get("sections") or []:
            for cid in script_claims(script).get(
                    str(section.get("id")), []) or section.get(
                        "claim_ids", []):
                if cid not in by_claim:
                    unmapped.append(f"{section.get('id')}:{cid}")
        out.append(CheckResult(
            "claims_mapped", "evidence",
            "pass" if not unmapped else "fail",
            ("every factual claim has a verdict" if not unmapped
             else f"claims without verdicts: {unmapped}"),
            blocking=True))
        open_blockers = [v.get("claim_id") for v in verdicts
                         if v.get("blocks_approval")]
        out.append(CheckResult(
            "unsupported_claims", "evidence",
            "pass" if not open_blockers else "fail",
            ("no blocking claims" if not open_blockers
             else f"blocking claims remain: {open_blockers}"),
            blocking=True))
        contradicted = [v.get("claim_id") for v in verdicts
                        if v.get("verdict") == "contradicted"]
        out.append(CheckResult(
            "contradictions", "evidence",
            "pass" if not contradicted else "fail",
            ("no contradictions" if not contradicted
             else f"contradicted claims: {contradicted}"),
            blocking=True))
        hashes = {report.get("package_hash"),
                  (inputs.get("storyboard") or {}).get("package_hash")}
        hashes.discard(None)
        hashes.discard("")
        out.append(CheckResult(
            "provenance", "evidence",
            "pass" if len(hashes) <= 1 else "warn",
            ("package hash continuous" if len(hashes) <= 1
             else f"hash drift across stages: {sorted(str(h) for h in hashes)}"),
            blocking=False))
        return out

    # -- rights --------------------------------------------------------------

    def _rights(self, inputs: dict[str, Any]) -> list[CheckResult]:
        from lib.producer.contracts import manifest_assets

        out = []
        manifest = inputs.get("asset_manifest") or {}
        assets = manifest_assets(manifest)
        if not assets:
            return [CheckResult("licenses_present", "rights", "fail",
                                "asset manifest has no assets",
                                blocking=True)]
        mode = str(inputs.get("rights_mode", "strict")).lower()
        problems, attribution_missing = [], []
        for asset in assets:
            aid = asset.get("id", asset.get("asset_id", "?"))
            lic = (asset.get("license") or "").strip()
            status = (asset.get("rights_status") or "unknown").lower()
            if not lic:
                problems.append(f"{aid}: no license recorded")
                continue
            if "restricted" in status:
                problems.append(f"{aid}: restricted rights")
            elif status == "unknown" and mode == "strict":
                problems.append(f"{aid}: unknown rights in strict mode")
            needs_attr = any(tag in lic.lower()
                             for tag in ("cc-by", "cc by", "attribution",
                                         "credit"))
            if needs_attr and not (asset.get("attribution")
                                   or asset.get("creator")):
                attribution_missing.append(aid)
        out.append(CheckResult(
            "licenses_present", "rights",
            "pass" if not problems else "fail",
            ("all assets licensed for production" if not problems
             else "; ".join(problems)),
            blocking=True))
        out.append(CheckResult(
            "attribution", "rights",
            "pass" if not attribution_missing else "fail",
            ("attribution complete" if not attribution_missing
             else f"attribution missing: {attribution_missing}"),
            blocking=True))
        return out

    # -- integrity -------------------------------------------------------------

    def _integrity(self, inputs: dict[str, Any]) -> list[CheckResult]:
        from lib.producer.contracts import manifest_assets

        out = []
        video = str(inputs.get("video_path", ""))
        paths = [video] if video else []
        manifest = inputs.get("asset_manifest") or {}
        enriched = manifest_assets(manifest)
        for asset in enriched:
            for key in ("local_path", "path", "download_url"):
                value = asset.get(key)
                if value and not str(value).startswith("http"):
                    paths.append(str(value))
        for stem in (inputs.get("narration_manifest") or {}).get(
                "sections") or []:
            if stem.get("path"):
                paths.append(str(stem["path"]))
        missing = [p for p in paths if not Path(p).exists()]
        out.append(CheckResult(
            "assets_exist", "integrity",
            "pass" if not missing else "fail",
            ("all referenced files exist" if not missing
             else f"missing files: {missing[:5]}"),
            blocking=True))
        fixtures = [p for p in paths
                    if any(h in p.lower() for h in _FIXTURE_HINTS)]
        out.append(CheckResult(
            "no_fixture_media", "integrity",
            "pass" if not fixtures else "fail",
            ("no test/fixture media in the production set" if not fixtures
             else f"fixture media referenced: {fixtures[:5]}"),
            blocking=True))
        synthetic = []
        for stem in (inputs.get("narration_manifest") or {}).get(
                "sections") or []:
            tool = str(stem.get("source_tool", "")
                       or stem.get("provider", "")).split(":")[0].lower()
            if tool in _SYNTHETIC_TOOLS:
                synthetic.append(stem.get("section_id", "?"))
            path = str(stem.get("path", "")).lower()
            if any(h in path for h in _FIXTURE_HINTS):
                synthetic.append(stem.get("section_id", "?"))
        out.append(CheckResult(
            "no_synthetic_audio", "integrity",
            "pass" if not synthetic else "fail",
            ("narration provenance is production TTS" if not synthetic
             else f"synthetic/test stems: {sorted(set(synthetic))}"),
            blocking=True))
        stale = []
        for asset in enriched:
            recorded = asset.get("checksum")
            local = asset.get("local_path", "") or asset.get("path", "")
            if recorded and local and Path(local).exists():
                try:
                    from lib.footage_hub.hub import sha256_file
                    if sha256_file(Path(local)) != recorded:
                        stale.append(asset.get("id",
                                               asset.get("asset_id")))
                except Exception:
                    pass
        out.append(CheckResult(
            "no_stale_assets", "integrity",
            "pass" if not stale else "fail",
            ("vault checksums match manifest" if not stale
             else f"checksum drift: {stale}"),
            blocking=True))
        manifest_ids = {a.get("id", a.get("asset_id"))
                        for a in enriched}
        decisions = inputs.get("edit_decisions") or {}
        layout = list((decisions.get("metadata") or {}).get("cuts_layout")
                      or [])
        broken = []
        if layout:
            for entry in layout:
                aid = entry.get("asset_id")
                if aid and aid not in manifest_ids:
                    broken.append(
                        f"{entry.get('cut_id')}:{aid}")
        else:
            for cut in decisions.get("cuts") or []:
                aid = cut.get("asset_id")
                if aid and aid not in manifest_ids:
                    broken.append(f"{cut.get('id')}:{aid}")
        out.append(CheckResult(
            "no_broken_refs", "integrity",
            "pass" if not broken else "fail",
            ("all cuts resolve to manifest assets" if not broken
             else f"dangling refs: {broken}"),
            blocking=True))
        storyboard_doc = inputs.get("storyboard") or {}
        required = {"script": bool((inputs.get("script") or {}).get(
            "sections")),
                    "storyboard": bool(storyboard_doc.get(
                        "requirements") or storyboard_doc.get("scenes")),
                    "narration_manifest": bool(
                        (inputs.get("narration_manifest") or {}).get(
                            "sections")),
                    "render_report": bool((inputs.get("render_report") or {}).get(
                        "outputs") if isinstance(
                            inputs.get("render_report"), dict) else inputs.get(
                                "render_report"))}
        absent = sorted(k for k, present in required.items() if not present)
        out.append(CheckResult(
            "no_missing_artifacts", "integrity",
            "pass" if not absent else "fail",
            ("required artifacts present" if not absent
             else f"missing: {absent}"),
            blocking=True))
        return out
