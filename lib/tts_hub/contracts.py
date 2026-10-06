"""TTS Hub normalized speech contract.

Plain data (JSON round-trippable) describing one narration synthesis.
Mirrors the FootageHub NormalizedAsset pattern: provider-agnostic payload,
all provenance retained, checksum for dedupe. Maps onto existing narration
abstractions (script sections, asset_manifest narration assets,
edit_decisions.audio.narration segments, audio_mixer speech tracks) via
lib/tts_hub/mapper.py — those contracts are reused, never redefined here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class TTSStatus:
    DONE = "done"        # freshly synthesized, validated real audio
    CACHED = "cached"    # served from content-hash cache (bytes identical)
    FAILED = "failed"    # synthesis did not produce usable audio


@dataclass
class WordAlignment:
    """Chunk-level alignment. Kokoro yields per-chunk audio; boundaries are
    measured from real sample counts, never estimated from character rates."""
    text: str = ""
    start_seconds: float = 0.0
    end_seconds: float = 0.0


@dataclass
class SpeechResult:
    provider: str = ""
    voice: str = ""
    language: str = ""
    input_text: str = ""
    output_audio_path: str = ""
    sample_rate: int = 0
    channels: int = 0
    duration: float = 0.0          # measured from decoded audio, never predicted
    alignment: list[dict[str, Any]] = field(default_factory=list)
    generation_metadata: dict[str, Any] = field(default_factory=dict)
    checksum: str = ""             # "sha256:<hex>" of the output file
    status: str = TTSStatus.DONE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SpeechResult":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def required_fields(cls) -> list[str]:
        return ["provider", "voice", "language", "input_text",
                "output_audio_path", "sample_rate", "channels", "duration",
                "alignment", "generation_metadata", "checksum", "status"]
