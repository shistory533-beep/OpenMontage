"""TTS provider interface + error taxonomy.

Every provider (Kokoro, Chatterbox-Turbo stub, Qwen3-TTS stub) satisfies
TTSProvider. Errors are typed so callers retry only what is retryable:
transient load/inference failures may retry; invalid voice, empty text,
and silence rejection fail fast. Silence is NEVER a fallback output.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from lib.tts_hub.contracts import SpeechResult


class TTSError(Exception):
    """Base class for all TTS Hub failures."""


class InvalidVoiceError(TTSError):
    """Unknown voice for this provider. Fail fast — never guess a substitute."""


class EmptyTextError(TTSError):
    """Blank/whitespace-only input. Fail fast."""


class UnsupportedLanguageError(TTSError):
    """Language not offered by this provider."""


class ProviderFailureError(TTSError):
    """Transient backend failure (model load, inference crash). Retryable."""


class ProviderUnavailableError(TTSError):
    """Provider not installed/configured. Never mandatory — caller falls through."""


class SilenceRejectedError(TTSError):
    """Output measured as silence/near-silence. Rejected, never shipped."""


@runtime_checkable
class TTSProvider(Protocol):
    name: str

    def is_available(self) -> bool: ...
    def voices(self) -> list[dict[str, Any]]: ...
    def synthesize(self, text: str, voice: str, out_path: str,
                   language: str = "en",
                   **options: Any) -> SpeechResult: ...
