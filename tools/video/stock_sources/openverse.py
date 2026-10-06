"""Openverse adapter (images + audio, no video).

Openverse (WordPress Photo Directory aggregator) indexes CC-licensed and
public-domain works. Free anonymous access — no API key required
(authenticated access raises rate limits but is optional, so this adapter
is available out of the box and never mandatory).

Capabilities (honest):
  - kind="image"  -> /v1/images/ search
  - kind="video"  -> [] (Openverse has no video catalog; the hub reports
    this via `supports` instead of failing)
  - kind="any"    -> images only

License: every record carries a machine-readable `license` slug
(CC0, BY, BY-SA, ...). Records with an unparseable license are kept but
flagged — rights validation happens in lib/footage_hub/rights.py, not here.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .base import Candidate, SearchFilters

_API_BASE = "https://api.openverse.org/v1"


class OpenverseSource:
    name = "openverse"
    display_name = "Openverse"
    provider = "openverse"
    priority = 40
    install_instructions = (
        "No setup required — anonymous access works out of the box. "
        "For higher rate limits, set OPENVERSE_API_KEY (free registration at "
        "https://api.openverse.org/) — optional, never required."
    )
    supports = {"video": False, "image": True, "audio": False}

    def is_available(self) -> bool:
        return True  # free anonymous path; no key, no binary needed

    def search(self, query: str, filters: SearchFilters) -> list[Candidate]:
        import requests

        kind = (filters.kind or "video").lower()
        if kind == "video":
            return []
        headers = {"User-Agent": "OpenMontage-footagehub/1.0"}
        token = os.environ.get("OPENVERSE_API_KEY")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        params: dict[str, Any] = {
            "q": query,
            "page_size": max(1, min(filters.per_page or 20, 50)),
            "page": max(1, filters.page or 1),
        }
        resp = requests.get(f"{_API_BASE}/images/", params=params,
                             headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return [_to_candidate(item) for item in data.get("results", [])]

    def download(self, candidate: Candidate, out_path: Path) -> Path:
        import requests

        if not candidate.download_url:
            raise ValueError(f"Candidate {candidate.clip_id} has no download_url")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(candidate.download_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            expected = r.headers.get("Content-Length")
            written = 0
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        written += len(chunk)
                        f.write(chunk)
            if expected is not None and written < int(expected):
                # Partial download: truncated bytes must never enter the vault.
                out_path.unlink(missing_ok=True)
                raise ValueError(
                    f"partial download for {candidate.clip_id}: "
                    f"{written} of {expected} bytes")
        return out_path


def _to_candidate(item: dict[str, Any]) -> Candidate:
    """Parse one Openverse image record. Defensive: every field optional."""
    source_id = str(item.get("id", ""))
    direct = item.get("url") or ""
    landing = item.get("foreign_landing_url") or direct
    title = item.get("title") or ""
    creator = item.get("creator") or ""
    lic = (item.get("license") or "").upper()
    lic_ver = item.get("license_version") or ""
    license_str = f"CC-{lic} {lic_ver}".strip() if lic else ""
    tags = item.get("tags") or []
    tag_text = " ".join(t.get("name", "") for t in tags if isinstance(t, dict))
    width = int(item.get("width") or 0)
    height = int(item.get("height") or 0)
    return Candidate(
        source="openverse",
        source_id=source_id,
        source_url=landing,
        download_url=direct,
        kind="image",
        width=width,
        height=height,
        duration=0.0,
        creator=creator,
        license=license_str or "Openverse (verify per-file license)",
        source_tags=" ".join(p for p in (title, tag_text) if p),
        thumbnail_url=item.get("thumbnail") or direct,
        extra={"license_slug": lic, "license_version": lic_ver},
    )
