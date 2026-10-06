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

from lib.tts_hub.contracts import SpeechResult, TTSStatus


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
    from lib.tts_hub.audio import assert_not_silence, probe_wav

    cache = Path(cache_dir) if cache_dir else default_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    key = cache_key(provider.name, voice, language, text, options)
    blob = cache / f"{key}.wav"
    sidecar = cache / f"{key}.json"
    if blob.exists() and sidecar.exists():
        info = assert_not_silence(blob)  # cached bytes re-validated, never trusted blind
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(blob, out)
        with open(sidecar, encoding="utf-8") as f:
            meta = json.load(f)
        with open(out, "rb") as f:
            import hashlib as _hl
            checksum = "sha256:" + _hl.sha256(f.read()).hexdigest()
        return SpeechResult(
            provider=provider.name, voice=voice, language=language,
            input_text=text, output_audio_path=str(out),
            sample_rate=int(info["sample_rate"]),
            channels=int(info["channels"]), duration=info["duration"],
            alignment=list(meta.get("alignment", [])),
            generation_metadata={**meta.get("generation_metadata", {}),
                                 "cache": "hit", "cache_key": key},
            checksum=checksum, status=TTSStatus.CACHED)
    result = provider.synthesize(text, voice, str(blob), language=language,
                                 **options)
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump({"alignment": result.alignment,
                   "generation_metadata": result.generation_metadata},
                  f, indent=2)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(blob, out)
    result.output_audio_path = str(out)
    result.generation_metadata = {**result.generation_metadata,
                                  "cache": "miss", "cache_key": key}
    return result
