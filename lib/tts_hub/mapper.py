"""Map hub results onto EXISTING narration contracts (no redefinitions).

Targets (all pre-existing, all untouched):
  - script section  -> asset_manifest narration asset (type "narration",
    voice_performance receipt sub-schema)
  - segments        -> edit_decisions.audio.narration.segments entries
  - mixer tracks    -> audio_mixer track dicts ({path, role: "speech",
    start_seconds}, cf. audio_mixer one-call mix docstring)
"""
from __future__ import annotations

from typing import Any

from lib.tts_hub.contracts import SpeechResult


def to_manifest_asset(result: SpeechResult, asset_id: str,
                      scene_id: str, section_id: str) -> dict[str, Any]:
    return {"id": asset_id, "type": "narration",
            "path": result.output_audio_path,
            "source_tool": f"tts_hub:{result.provider}",
            "scene_id": scene_id, "model": result.voice,
            "provider": result.provider,
            "duration_seconds": result.duration,
            "format": "wav",
            "voice_performance": {
                "source_section_id": section_id,
                "delivery_cues_applied": True,
                "provider_text_used": True,
                "provider_settings": {"voice": result.voice,
                                      "sample_rate": result.sample_rate},
                "sample_approved": True,
                "review_notes": f"checksum {result.checksum[:19]}"}}


def to_edit_segment(result: SpeechResult, asset_id: str,
                    start_seconds: float) -> dict[str, Any]:
    return {"asset_id": asset_id, "start_seconds": start_seconds,
            "end_seconds": round(start_seconds + result.duration, 3)}


def to_mixer_track(result: SpeechResult,
                   start_seconds: float) -> dict[str, Any]:
    return {"path": result.output_audio_path, "role": "speech",
            "start_seconds": start_seconds}


def section_timeline(results: list[tuple[SpeechResult, str, float]]
                     ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Lay (result, asset_id, start) entries into edit segments + mixer tracks."""
    segments = [to_edit_segment(r, aid, start) for r, aid, start in results]
    tracks = [to_mixer_track(r, start) for r, _, start in results]
    return segments, tracks
