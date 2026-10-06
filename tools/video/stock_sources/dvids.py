"""DVIDS adapter (U.S. military public-affairs media).

DVIDS Hub (dvidshub.net) distributes public-domain U.S. DoD photos and
videos — strong documentary source for military/history topics. The v2
search API needs a free API key (registration at dvidshub.net); without
one this adapter reports unavailable and the hub skips it. Never mandatory.

Fetch pattern: single GET /api/v2/search with api_key + q. Records carry
a direct file URL when the API exposes one; otherwise download_url falls
back to the landing page and download() raises a clear error for that
candidate (per-candidate failure, never a pipeline crash).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .base import Candidate, SearchFilters

_API_BASE = "https://www.dvidshub.net/api/v2"


class DvidsSource:
    name = "dvids"
    display_name = "DVIDS"
    provider = "dvids"
    priority = 60
    install_instructions = (
        "Set DVIDS_API_KEY in .env (free registration at "
        "https://www.dvidshub.net/). Optional — the hub skips DVIDS "
        "when unconfigured."
    )
    supports = {"video": True, "image": True}

    def is_available(self) -> bool:
        return bool(os.environ.get("DVIDS_API_KEY"))

    def search(self, query: str, filters: SearchFilters) -> list[Candidate]:
        import requests

        params: dict[str, Any] = {
            "api_key": os.environ.get("DVIDS_API_KEY", ""),
            "q": query,
            "max_results": max(1, min(filters.per_page or 20, 50)),
        }
        resp = requests.get(f"{_API_BASE}/search", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", data if isinstance(data, list) else [])
        out: list[Candidate] = []
        for item in results:
            if isinstance(item, dict):
                cand = _to_candidate(item, filters)
                if cand is not None:
                    out.append(cand)
        return out

    def download(self, candidate: Candidate, out_path: Path) -> Path:
        import requests

        if not candidate.download_url or not candidate.download_url.startswith("http"):
            raise ValueError(
                f"Candidate {candidate.clip_id} has no direct file URL "
                f"(landing page only: {candidate.source_url})"
            )
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(candidate.download_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
        return out_path


def _to_candidate(item: dict[str, Any], filters: SearchFilters) -> Candidate | None:
    """Parse one DVIDS record. Returns None when it cannot be normalized."""
    source_id = str(item.get("id", item.get("asset_id", "")))
    if not source_id:
        return None
    media_type = str(item.get("media_type", item.get("type", "video"))).lower()
    kind = "image" if "image" in media_type or "photo" in media_type else "video"
    wanted = (filters.kind or "video").lower()
    if wanted in ("video", "image") and kind != wanted:
        return None
    title = item.get("title", "")
    direct = item.get("file_url") or item.get("download_url") or ""
    landing = item.get("url") or item.get("landing_url") or ""
    return Candidate(
        source="dvids",
        source_id=source_id,
        source_url=landing or direct,
        download_url=direct or landing,
        kind=kind,
        width=int(item.get("width") or 0),
        height=int(item.get("height") or 0),
        duration=float(item.get("duration") or item.get("duration_seconds") or 0.0),
        creator=str(item.get("credit") or item.get("creator") or "U.S. DoD"),
        license="Public domain (U.S. federal government work)",
        source_tags=" ".join(
            p for p in (title, str(item.get("description", ""))) if p
        ),
        thumbnail_url=item.get("thumbnail_url") or "",
        extra={"media_type": media_type},
    )
