"""TTS Hub package init — re-exports only."""
from lib.tts_hub.contracts import SpeechResult, TTSStatus, WordAlignment  # noqa: F401
from lib.tts_hub.interface import (  # noqa: F401
    EmptyTextError,
    InvalidVoiceError,
    ProviderFailureError,
    ProviderUnavailableError,
    SilenceRejectedError,
    TTSError,
    TTSProvider,
    UnsupportedLanguageError,
)
