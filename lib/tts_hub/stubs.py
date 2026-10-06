"""Secondary provider contracts: Chatterbox-Turbo + Qwen3-TTS.

Capability stubs, deliberately. They implement the TTSProvider interface so
selection, discovery, and fallback logic treat every provider uniformly —
but synthesize() raises ProviderUnavailableError with install instructions
instead of fabricating audio. A stub can never return silence, speech, or
anything else: absence is explicit.
"""
from __future__ import annotations

from typing import Any

from lib.tts_hub.contracts import SpeechResult
from lib.tts_hub.interface import ProviderUnavailableError


class ChatterboxTurboStub:
    """Chatterbox-Turbo (Resemble AI open-weight TTS) — contract stub."""

    name = "chatterbox-turbo"
    display_name = "Chatterbox-Turbo"
    model = "chatterbox-turbo"  # concrete weights TBD on implementation
    sample_rate: int | None = None  # unknown until synthesis is implemented
    channels: int | None = None
    install_instructions = (
        "pip install chatterbox-tts (needs GPU for practical inference); "
        "then implement synthesis in lib/tts_hub/chatterbox_provider.py "
        "behind this same interface. Not required for Kokoro-first runs.")

    def is_available(self) -> bool:
        try:
            import chatterbox  # noqa: F401
            return True
        except ImportError:
            return False

    def voices(self) -> list[dict[str, Any]]:
        # Declared catalog (voice-clone design: reference-audio driven).
        return [{"id": "default", "language": "en", "gender": "any",
                 "style": "clone-via-reference-audio"}]

    def synthesize(self, text: str, voice: str, out_path: str,
                   language: str = "en", **options: Any) -> SpeechResult:
        raise ProviderUnavailableError(
            "chatterbox-turbo is a capability stub: " + self.install_instructions)


class Qwen3TTSStub:
    """Qwen3-TTS (Alibaba DashScope) — contract stub."""

    name = "qwen3-tts"
    display_name = "Qwen3-TTS"
    model = "qwen3-tts-flash"  # DashScope TTS model family
    sample_rate: int | None = None  # unknown until synthesis is implemented
    channels: int | None = None
    install_instructions = (
        "Set DASHSCOPE_API_KEY (see tools/audio/dashscope_tts.py, already "
        "shipped); then implement synthesis in lib/tts_hub/qwen3_provider.py "
        "behind this same interface. Not required for Kokoro-first runs.")

    def is_available(self) -> bool:
        import os
        return bool(os.environ.get("DASHSCOPE_API_KEY"))

    def voices(self) -> list[dict[str, Any]]:
        return [{"id": "Cherry", "language": "zh", "gender": "female",
                 "style": "mandarin-narration"}]

    def synthesize(self, text: str, voice: str, out_path: str,
                   language: str = "en", **options: Any) -> SpeechResult:
        raise ProviderUnavailableError(
            "qwen3-tts is a capability stub: " + self.install_instructions)
