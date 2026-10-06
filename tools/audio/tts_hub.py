"""TTS Hub tool — local-first narration over lib/tts_hub.

Capability "tts": auto-discovered by tts_selector alongside the existing
providers (replaceable, never exclusive). Local Kokoro renders at $0;
failures return success=False with typed reasons — silence is never
emitted as narration.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class TTSHub(BaseTool):
    name = "tts_hub"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "tts_hub"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["python:torch", "python:kokoro"]
    install_instructions = (
        "pip install kokoro torch scipy transformers huggingface_hub "
        "num2words loguru + spacy en_core_web_sm; Kokoro weights "
        "auto-download from HuggingFace on first run (CPU OK).")
    agent_skills = ["text-to-speech"]

    capabilities = ["local_narration", "voice_discovery",
                    "content_hash_cache", "alignment", "dry_run"]
    supports = {"offline": True, "multilingual": False,
                "voice_cloning": False, "native_audio": True,
                "silence_fallback": False}
    best_for = ["local-first documentary narration",
                "deterministic re-renders (pinned voice + cache)"]
    not_good_for = ["non-English narration (kokoro adapter: en only)",
                    "voice cloning (use elevenlabs_tts / fish_audio_tts)"]
    fallback_tools = ["piper_tts", "google_tts"]
    retry_policy = RetryPolicy(max_retries=2,
                               retryable_errors=["ProviderFailureError"])

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {"type": "string",
                          "enum": ["synthesize", "voices", "capabilities",
                                   "dry_run"]},
            "text": {"type": "string"},
            "voice": {"type": "string"},
            "language": {"type": "string", "default": "en"},
            "style_hint": {"type": "string", "default": "warm"},
            "provider": {"type": "string", "default": "kokoro"},
            "output_path": {"type": "string"},
            "use_cache": {"type": "boolean", "default": True},
            "speed": {"type": "number", "default": 1.0},
        },
    }
    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=4096, vram_mb=0, disk_mb=2000,
        network_required=False)
    side_effects = ["writes WAV narration to output_path",
                    "caches bytes under ~/.openmontage/tts_cache"]
    user_visible_verification = [
        "Play output_path and confirm spoken narration (never silence)",
        "Check duration/sample_rate in the returned result dict",
    ]

    def get_status(self) -> ToolStatus:
        try:
            from lib.tts_hub.registry import get_provider
            return (ToolStatus.AVAILABLE
                    if get_provider("kokoro").is_available()
                    else ToolStatus.UNAVAILABLE)
        except Exception:
            return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0  # local inference

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            op = inputs["operation"]
            if op == "capabilities":
                from lib.tts_hub.registry import capabilities
                return ToolResult(
                    success=True, data={"providers": capabilities()},
                    duration_seconds=round(time.time() - start, 3))
            if op == "voices":
                from lib.tts_hub.registry import get_provider
                prov = get_provider(inputs.get("provider", "kokoro"))
                return ToolResult(
                    success=True,
                    data={"provider": prov.name, "voices": prov.voices()},
                    duration_seconds=round(time.time() - start, 3))
            if op == "dry_run":
                # Plan without synthesis: provider/voice resolution, cache
                # key, and whether bytes are already cached. Writes nothing.
                from lib.tts_hub.cache import cache_key, default_cache_dir
                from lib.tts_hub.contracts import input_hash_for
                from lib.tts_hub.registry import get_provider
                from lib.tts_hub import registry as reg
                try:
                    prov = get_provider(inputs.get("provider", "kokoro"))
                except KeyError as exc:
                    return ToolResult(success=False, error=str(exc))
                text = inputs.get("text", "")
                language = inputs.get("language", "en")
                speed = float(inputs.get("speed", 1.0))
                voice = inputs.get("voice") or reg.deterministic_voice(
                    language, inputs.get("style_hint", "warm"),
                    provider=prov)
                key = cache_key(prov.name, voice, language, text,
                                {"speed": speed})
                blob = default_cache_dir() / f"{key}.wav"
                return ToolResult(
                    success=True,
                    data={"provider": prov.name,
                          "model": getattr(prov, "model", ""),
                          "voice": voice, "language": language,
                          "speed": speed,
                          "input_hash": input_hash_for(text),
                          "cache_key": key,
                          "cache_hit": bool(blob.exists()),
                          "available": bool(prov.is_available()),
                          "output_path": inputs.get("output_path") or str(
                              Path("projects") / "tts_hub" / "out.wav")},
                    duration_seconds=round(time.time() - start, 3))
            if op == "synthesize":
                from lib.tts_hub import registry as reg
                from lib.tts_hub.cache import synthesize_cached
                from lib.tts_hub.interface import (
                    EmptyTextError, InvalidVoiceError,
                    ProviderFailureError, ProviderUnavailableError,
                    SilenceRejectedError, UnsupportedLanguageError,
                )
                text = inputs.get("text", "")
                if not text or not text.strip():
                    return ToolResult(success=False,
                                      error="EmptyTextError: refusing empty text")
                try:
                    prov = reg.get_provider(inputs.get("provider", "kokoro"))
                    if not prov.is_available():
                        raise ProviderUnavailableError(
                            f"{prov.name} unavailable")
                except (KeyError, ProviderUnavailableError) as exc:
                    return ToolResult(success=False, error=str(exc))
                voice = inputs.get("voice") or reg.deterministic_voice(
                    inputs.get("language", "en"),
                    inputs.get("style_hint", "warm"), provider=prov)
                out = inputs.get("output_path") or str(
                    Path("projects") / "tts_hub" / "out.wav")
                attempts, last_err = 0, ""
                while attempts <= self.retry_policy.max_retries:
                    try:
                        if inputs.get("use_cache", True):
                            res = synthesize_cached(
                                prov, text, voice, out,
                                language=inputs.get("language", "en"),
                                speed=float(inputs.get("speed", 1.0)))
                        else:
                            res = prov.synthesize(
                                text, voice, out,
                                language=inputs.get("language", "en"),
                                speed=float(inputs.get("speed", 1.0)))
                        return ToolResult(
                            success=True, data={"result": res.to_dict()},
                            artifacts=[res.output_audio_path], cost_usd=0.0,
                            duration_seconds=round(time.time() - start, 3))
                    except (EmptyTextError, InvalidVoiceError,
                            UnsupportedLanguageError,
                            SilenceRejectedError) as exc:
                        return ToolResult(
                            success=False,
                            error=f"{type(exc).__name__}: {exc}")
                    except Exception as exc:  # retryable transient
                        last_err = (f"{type(exc).__name__}: {exc}")
                        attempts += 1
                return ToolResult(
                    success=False,
                    error=f"ProviderFailureError: {last_err} "
                          f"(after {attempts} attempts)")
            return ToolResult(success=False, error=f"Unknown operation: {op!r}")
        except Exception as exc:
            import traceback
            return ToolResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}\n"
                      f"{traceback.format_exc()[-800:]}")
