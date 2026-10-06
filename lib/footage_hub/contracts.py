"""FootageHub normalized asset contract.

One normalized interface over every provider. A NormalizedAsset is plain
data (no provider imports, no network) so it survives JSON round-trips
into vault manifests, episode packages, and checkpoints.

Field provenance: mapped 1:1 from StockSource.Candidate (existing
retrieval system) plus download-time enrichment (format, fps,
retrieved_at, checksum). Nothing here duplicates Candidate — it extends
it with the rights/download metadata a documentary factory must track.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class NormalizedAsset:
    provider: str = ""
    source_id: str = ""
    title: str = ""
    description: str = ""     # free-text description when the source exposes one
    source_url: str = ""
    download_url: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    format: str = ""            # file container, e.g. "mp4" (known after download)
    creator: str = ""
    license: str = ""
    rights_status: str = "unknown"   # see lib/footage_hub/rights.py RightsStatus
    attribution: str = ""       # human-readable credit line (may be "" when not required)
    retrieved_at: str = ""      # UTC ISO-8601 of normalization
    checksum: str = ""          # "sha256:<hex>"; empty until downloaded
    kind: str = "video"         # "video" | "image"
    local_path: str = ""        # vault blob path once downloaded
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def asset_id(self) -> str:
        return f"{self.provider}_{self.source_id}"

    @property
    def media_type(self) -> str:
        """Media-type alias for kind ("video" | "image")."""
        return self.kind

    @property
    def orientation(self) -> str:
        """Derived from dimensions: landscape | portrait | square | unknown."""
        from lib.footage_hub.verify import orientation_of

        return orientation_of(self.width, self.height)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NormalizedAsset":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def required_fields(cls) -> list[str]:
        return ["provider", "source_id", "title", "description", "source_url",
                "download_url", "duration", "width", "height", "fps",
                "format", "creator", "license", "rights_status",
                "attribution", "retrieved_at", "checksum"]


@dataclass
class ProviderCapability:
    """Advertised capability for one provider (agent-facing, no secrets)."""

    name: str
    display_name: str
    available: bool
    supports_video: bool
    supports_image: bool
    needs_key: bool
    install_instructions: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
