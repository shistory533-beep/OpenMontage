"""Kokoro adapter — the fully implemented primary provider.

Backend: the `kokoro` PyTorch package (KPipeline), local CPU inference,
24 kHz mono output. Lazy singleton pipeline (model weights load once per
process). Deterministic given (text, voice, speed): same inputs render the
same bytes through the same weights — and the content-hash cache in
lib/tts_hub/cache.py makes repeat requests byte-identical without
re-inference.

Failure semantics: empty text / unknown voice / unsupported language fail
fast with typed errors (no retry). Inference crashes raise
ProviderFailureError (retryable by the caller). Measured silence raises
SilenceRejectedError — the file is still written for debugging, but the
result is never returned as usable narration.
"""
from __future__ import annotations

import hashlib
import time
import wave
from pathlib import Path
from typing import Any

from lib.tts_hub.contracts import SpeechResult, TTSStatus
from lib.tts_hub.interface import (
    EmptyTextError,
    InvalidVoiceError,
    ProviderFailureError,
    UnsupportedLanguageError,
)

SAMPLE_RATE = 24000
CHANNELS = 1

# Curated Kokoro voice catalog (82M v1.0). American English default first.
VOICES: tuple[dict[str, Any], ...] = (
    {"id": "af_heart", "language": "en", "gender": "female", "style": "warm"},
    {"id": "af_bella", "language": "en", "gender": "female", "style": "bright"},
    {"id": "af_nicole", "language": "en", "gender": "female", "style": "calm"},
    {"id": "af_sarah", "language": "en", "gender": "female", "style": "confident"},
    {"id": "af_sky", "language": "en", "gender": "female", "style": "airy"},
    {"id": "am_adam", "language": "en", "gender": "male", "style": "deep"},
    {"id": "am_michael", "language": "en", "gender": "male", "style": "steady"},
    {"id": "bf_emma", "language": "en", "gender": "female", "style": "warm"},
    {"id": "bf_isabella", "language": "en", "gender": "female", "style": "soft"},
    {"id": "bm_george", "language": "en", "gender": "male", "style": "authoritative"},
    {"id": "bm_lewis", "language": "en", "gender": "male", "style": "measured"},
)

_PIPELINE: Any = None


class _forced_offline:
    """Force hermetic HF init/inference (constants freeze at first import).

    Restores env + library constants on exit. Used as a bounded retry:
    normal attempt first (allows fresh weight/voice download), offline
    retry second (uses cache only)."""

    def __init__(self) -> None:
        self.saved_env: dict[str, str | None] = {}
        self.saved_const: Any = None

    def __enter__(self) -> "_forced_offline":
        import os

        self.saved_env = {k: os.environ.get(k) for k in
                          ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
        try:
            import huggingface_hub.constants as _hfc
            self.saved_const = _hfc.HF_HUB_OFFLINE
            _hfc.HF_HUB_OFFLINE = True
        except ImportError:
            pass
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        return self

    def __exit__(self, *args: Any) -> None:
        import os

        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if self.saved_const is not None:
            try:
                import huggingface_hub.constants as _hfc2
                _hfc2.HF_HUB_OFFLINE = self.saved_const
            except ImportError:
                pass


def _pipeline(lang_code: str = "a") -> Any:
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    try:
        from kokoro import KPipeline
    except ImportError as exc:
        raise ProviderFailureError(
            "kokoro package not installed (pip install kokoro; "
            "needs torch + weights download)") from exc
    try:
        _PIPELINE = KPipeline(lang_code=lang_code)
    except Exception as first_exc:
        with _forced_offline():
            try:
                _PIPELINE = KPipeline(lang_code=lang_code)
            except Exception:
                raise ProviderFailureError(
                    f"kokoro model load failed: {type(first_exc).__name__}: "
                    f"{first_exc}"
                ) from first_exc
    return _PIPELINE


class KokoroAdapter:
    name = "kokoro"
    display_name = "Kokoro"
    install_instructions = ("pip install kokoro torch scipy transformers "
                            "huggingface_hub num2words loguru + "
                            "spacy en_core_web_sm; weights auto-download "
                            "from HuggingFace on first run.")

    def is_available(self) -> bool:
        try:
            import kokoro  # noqa: F401
            import torch  # noqa: F401
            return True
        except ImportError:
            return False

    def voices(self) -> list[dict[str, Any]]:
        return [dict(v) for v in VOICES]

    def synthesize(self, text: str, voice: str, out_path: str,
                   language: str = "en", **options: Any) -> SpeechResult:
        from lib.tts_hub.audio import assert_not_silence

        if not (text or "").strip():
            raise EmptyTextError("refusing to synthesize empty text")
        if language != "en":
            raise UnsupportedLanguageError(
                f"kokoro adapter serves en only, got {language!r}")
        ids = {v["id"] for v in VOICES}
        if voice not in ids:
            raise InvalidVoiceError(
                f"unknown kokoro voice {voice!r}; available: {sorted(ids)}")
        speed = float(options.get("speed", 1.0))
        started = time.time()
        try:
            pipe = _pipeline()
            chunks: list[tuple[str, Any]] = []
            for gs, _ps, audio in pipe(text, voice=voice, speed=speed):
                chunks.append((gs, audio))
        except (EmptyTextError, InvalidVoiceError, UnsupportedLanguageError):
            raise
        except Exception as first_exc:
            # Voice files download on first use; retry hermetically so a
            # blocked freshness check falls back to cache, never to silence.
            with _forced_offline():
                try:
                    pipe = _pipeline()
                    chunks = [(gs, audio) for gs, _ps, audio
                              in pipe(text, voice=voice, speed=speed)]
                except (EmptyTextError, InvalidVoiceError,
                        UnsupportedLanguageError):
                    raise
                except Exception:
                    raise ProviderFailureError(
                        f"kokoro inference failed: "
                        f"{type(first_exc).__name__}: {first_exc}"
                    ) from first_exc
        if not chunks:
            raise ProviderFailureError("kokoro returned zero audio chunks")
        import torch
        import numpy as np

        tensors = [torch.as_tensor(c[1]).float().reshape(-1) for c in chunks]
        audio = torch.cat(tensors).numpy()
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        with wave.open(str(out), "wb") as w:
            w.setnchannels(CHANNELS)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        info = assert_not_silence(out)  # raises; never ships silence
        alignment: list[dict[str, Any]] = []
        cursor = 0.0
        for gs, tensor in chunks:
            dur = tensor.numel() / SAMPLE_RATE
            alignment.append({"text": gs, "start_seconds": round(cursor, 3),
                              "end_seconds": round(cursor + dur, 3)})
            cursor += dur
        with open(out, "rb") as f:
            checksum = "sha256:" + hashlib.sha256(f.read()).hexdigest()
        return SpeechResult(
            provider="kokoro", voice=voice, language=language,
            input_text=text, output_audio_path=str(out),
            sample_rate=SAMPLE_RATE, channels=CHANNELS,
            duration=info["duration"], alignment=alignment,
            generation_metadata={"engine": "kokoro-torch",
                                 "speed": speed,
                                 "chunks": len(chunks),
                                 "peak": round(info["peak"], 4),
                                 "mean_abs": round(info["mean_abs"], 6),
                                 "inference_seconds": round(time.time() - started, 2)},
            checksum=checksum, status=TTSStatus.DONE)
