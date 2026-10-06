"""FootageHub provider registry.

Thin wrapper over the existing stock_sources discovery
(tools/video/stock_sources/__init__.py). No duplicate adapter list, no
parallel protocol: availability, search, and download all resolve to the
same StockSource instances corpus_builder uses, so the Footage Vault
(lib/corpus.py + clip_cache.py) and the hub always agree on what exists.

The eight factory providers are named here for capability reporting; any
additionally installed adapter (coverr, dareful, ...) is reported too —
never hidden, never mandatory.
"""
from __future__ import annotations

from typing import Any

from lib.footage_hub.contracts import ProviderCapability

FACTORY_PROVIDERS: tuple[str, ...] = (
    "archive_org",
    "wikimedia",
    "nasa",
    "openverse",
    "loc",
    "dvids",
    "pexels",
    "pixabay_video",
)


def capabilities() -> list[ProviderCapability]:
    """Advertise every registered provider: availability + media support."""
    from tools.video.stock_sources import all_sources

    out: list[ProviderCapability] = []
    for src in all_sources():
        cls = src.__class__
        try:
            available = bool(src.is_available())
        except Exception:
            available = False  # broken availability check => unavailable, not a crash
        supports = getattr(cls, "supports", {}) or {}
        out.append(ProviderCapability(
            name=src.name,
            display_name=getattr(cls, "display_name", src.name),
            available=available,
            supports_video=bool(supports.get("video", True)),
            supports_image=bool(supports.get("image", True)),
            needs_key="API_KEY" in getattr(
                cls, "install_instructions", "") or "key" in getattr(
                cls, "install_instructions", "").lower(),
            install_instructions=getattr(cls, "install_instructions", ""),
        ))
    return out


def capability_map() -> dict[str, dict[str, Any]]:
    return {c.name: c.to_dict() for c in capabilities()}


def get_adapter(name: str) -> Any:
    """Resolve one adapter by name. Raises KeyError for unknown names."""
    from tools.video.stock_sources import get_source

    return get_source(name)
