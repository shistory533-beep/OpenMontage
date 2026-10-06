"""TTS provider registry: discovery, capabilities, deterministic selection.

Kokoro first, always. Fallback order is fixed (kokoro -> chatterbox-turbo ->
qwen3-tts) and stubs report unavailable rather than synthesizing, so a run
with only Kokoro installed deterministically selects Kokoro. Voice selection
is a pure hash over (language, style_hint) into the sorted available voice
catalog — same inputs pick the same voice on every machine, no randomness.
"""
from __future__ import annotations

import hashlib
from typing import Any

PROVIDER_ORDER: tuple[str, ...] = ("kokoro", "chatterbox-turbo", "qwen3-tts")


def providers() -> list[Any]:
    from lib.tts_hub.kokoro_provider import KokoroAdapter
    from lib.tts_hub.stubs import ChatterboxTurboStub, Qwen3TTSStub

    return [KokoroAdapter(), ChatterboxTurboStub(), Qwen3TTSStub()]


def get_provider(name: str) -> Any:
    for p in providers():
        if p.name == name:
            return p
    raise KeyError(f"Unknown TTS provider {name!r}")


def capabilities() -> list[dict[str, Any]]:
    out = []
    for p in providers():
        try:
            available = bool(p.is_available())
            voice_list = p.voices() if available else []
        except Exception:
            available, voice_list = False, []
        out.append({"name": p.name,
                    "display_name": getattr(p, "display_name", p.name),
                    "model": getattr(p, "model", ""),
                    "available": available,
                    "voices": voice_list,
                    "install_instructions": getattr(p, "install_instructions", "")})
    return out


def select_provider(preferred: str | None = None) -> Any:
    """Deterministic provider choice. Raises when nothing usable exists."""
    from lib.tts_hub.interface import ProviderUnavailableError

    ordered = providers()
    if preferred:
        ordered = sorted(ordered, key=lambda p: p.name != preferred)
    for p in ordered:
        try:
            if p.is_available():
                return p
        except Exception:
            continue
    raise ProviderUnavailableError(
        "no TTS provider available (kokoro not installed, no stub keys); "
        "narration stays missing — never synthesized as silence")


def deterministic_voice(language: str = "en",
                        style_hint: str = "warm",
                        provider: Any | None = None) -> str:
    """Hash (language, style_hint) into the provider's sorted voice catalog."""
    from lib.tts_hub.interface import ProviderUnavailableError

    p = provider or select_provider()
    catalog = sorted(v["id"] for v in p.voices()
                     if v.get("language") == language)
    if not catalog:
        raise ProviderUnavailableError(
            f"provider {p.name} offers no {language!r} voices")
    digest = hashlib.sha256(f"{language}|{style_hint}".encode()).hexdigest()
    return catalog[int(digest, 16) % len(catalog)]
