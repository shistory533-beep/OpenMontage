"""Content-hash cache for synthesized narration.

Key: sha256(provider | voice | language | text | sorted options).
Hit: copy cached WAV to the requested path, return SpeechResult with
status=CACHED (bytes identical to the original render). Miss: synthesize,
validate, then store WAV + sidecar JSON. Failures are never cached —
a FAILED synthesis always re-runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from lib.tts_hub.contracts import SpeechResult, TTSStatus, input_hash_for


def _expected_format(provider: Any) -> tuple[int | None, int | None]:
    """Provider-declared (sample_rate, channels); None when unknown."""
    return (getattr(provider, "sample_rate", None),
            getattr(provider, "channels", None))


def default_cache_dir() -> Path:
    override = os.environ.get("OPENMONTAGE_TTS_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    from pathlib import Path as _P
    return _P.home() / ".openmontage" / "tts_cache"


def cache_key(provider: str, voice: str, language: str, text: str,
              options: dict[str, Any]) -> str:
    opts = "|".join(f"{k}={options[k]}" for k in sorted(options))
    return hashlib.sha256(
        f"{provider}|{voice}|{language}|{text}|{opts}".encode()).hexdigest()


def synthesize_cached(provider: Any, text: str, voice: str, out_path: str,
                      language: str = "en",
                      cache_dir: Path | str | None = None,
                      **options: Any) -> SpeechResult:
    from lib.tts_hub.audio import assert_not_silence, verify_audio_result
    from lib.tts_hub.interface import ProviderFailureError

    cache = Path(cache_dir) if cache_dir else default_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    key = cache_key(provider.name, voice, language, text, options)
    blob = cache / f"{key}.wav"
    sidecar = cache / f"{key}.json"
    exp_rate, exp_channels = _expected_format(provider)
    if blob.exists() and sidecar.exists():
        try:
            # Cached bytes are re-validated, never trusted blind: real decode,
            # silence rejection, and format match against the provider's
            # declared output format.
            info = assert_not_silence(blob)
            if exp_rate is not None and int(info["sample_rate"]) != exp_rate:
                raise ProviderFailureError(
                    f"cached blob sample_rate {info['sample_rate']:.0f} != "
                    f"provider {provider.name} declared {exp_rate}")
            if exp_channels is not None and int(info["channels"]) != exp_channels:
                raise ProviderFailureError(
                    f"cached blob channels {info['channels']:.0f} != "
                    f"provider {provider.name} declared {exp_channels}")
            with open(sidecar, encoding="utf-8") as f:
                meta = json.load(f)
            out = Path(out_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(blob, out)
        except Exception:
            # Corrupt/foreign/silent cache entry: self-heal by dropping it
            # and re-synthesizing below. Failures are never served from
            # cache; a re-synthesis that still fails raises normally.
            for p in (blob, sidecar):
                try:
                    p.unlink()
                except OSError:
                    pass
        else:
            with open(out, "rb") as f:
                import hashlib as _hl
                checksum = "sha256:" + _hl.sha256(f.read()).hexdigest()
            return SpeechResult(
                provider=provider.name,
                model=getattr(provider, "model", ""),
                voice=voice, language=language,
                input_text=text, input_hash=input_hash_for(text),
                output_audio_path=str(out),
                sample_rate=int(info["sample_rate"]),
                channels=int(info["channels"]), duration=info["duration"],
                alignment=list(meta.get("alignment", [])),
                generation_metadata={**meta.get("generation_metadata", {}),
                                     "cache": "hit", "cache_key": key},
                checksum=checksum, status=TTSStatus.CACHED)
    result = provider.synthesize(text, voice, str(blob), language=language,
                                 **options)
    # Fresh renders are verified too: decoded bytes must match the result's
    # own claims (rate/channels/duration) or the render is corrupt.
    verify_audio_result(str(blob), sample_rate=result.sample_rate,
                        channels=result.channels, duration=result.duration)
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump({"alignment": result.alignment,
                   "generation_metadata": result.generation_metadata},
                  f, indent=2)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(blob, out)
    result.output_audio_path = str(out)
    result.input_hash = result.input_hash or input_hash_for(text)
    result.generation_metadata = {**result.generation_metadata,
                                  "cache": "miss", "cache_key": key}
    return result
