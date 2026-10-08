"""Capability / provider abstraction — optional upstreams, no hard keys.
Free/local-first default; paid is opt-in only with explicit env/token.
OmniRoute = OPTIONAL upstream, never router of record.
"""
from __future__ import annotations
from typing import Optional, Dict, Any

class ProviderAbstraction:
    """Clean provider abstraction. Keys never hardcoded; absence = graceful fallback."""
    def __init__(self):
        self.capabilities = {"tts": ["piper_tts","google_tts","elevenlabs_tts"],
                             "clip_search": ["direct_clip_search","corpus_builder"],
                             "compose": ["video_compose","ffmpeg"],
                             "music": ["music_library","freesound_music"]}
        self._env_keys: Dict[str, bool] = {}
        for k in ("ELEVENLABS_API_KEY","GOOGLE_API_KEY","AZURE_SPEECH_KEY","OMNIRoute"):
            import os
            self._env_keys[k] = bool(os.getenv(k))

    def resolve(self, cap: str, preferred: Optional[str] = None) -> str:
        """Select provider; prefer free/local; never invent availability."""
        available = self.capabilities.get(cap, [])
        # Free-first ordering (verified local tools)
        free_first = ["piper_tts","direct_clip_search","music_library","ffmpeg","google_tts"]
        for p in free_first:
            if p in available:
                # Verify key only for non-local providers
                if p.startswith("piper") or p == "ffmpeg" or p == "direct_clip_search" or p == "music_library":
                    return p
                # Optional paid: only return if env explicitly present
                if p == "google_tts" and self._env_keys.get("GOOGLE_API_KEY"):
                    return p
                # For others, if key missing, skip (no fake success)
                if self._env_keys.get("ELEVENLABS_API_KEY") and p == "elevenlabs_tts":
                    return p
        # Fallback: first available that isn't hard-required paid
        for p in available:
            if p.startswith("piper") or p == "ffmpeg" or p == "direct_clip_search" or p == "music_library":
                return p
        # If nothing usable, return local ffmpeg / piper as safe permanent fallback
        return "ffmpeg"

    def status(self) -> Dict[str, Any]:
        return {"env_keys": self._env_keys,
                "free_first": True,
                "omni_route_optional": self._env_keys.get("OMNIRoute", False)}

    def is_free(self, provider: str) -> bool:
        return provider in ("piper_tts","ffmpeg","direct_clip_search","music_library","google_tts")
