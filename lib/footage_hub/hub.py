"""FootageHub facade: search -> normalize -> rights-filter -> rank -> download.

Integration contract with the existing system (nothing redesigned):
  - Discovery/adapters: reuses tools/video/stock_sources (same StockSource
    instances corpus_builder fans out over).
  - Retrieval math: hub ranking is a deterministic pre-rank ONLY
    (token overlap + resolution + provider order). Semantic rerank stays in
    lib/corpus.py rank_by_text / tools/video/clip_search.py — the hub never
    reimplements embeddings.
  - Vault: downloaded bytes are ingested into ClipCache (content dedupe by
    checksum here, byte-level LRU there) and recorded in a
    footage_hub_manifest.jsonl sidecar the corpus builder can read later.
    Corpus index/embedding writes remain corpus_builder's job.

Failure semantics: one provider raising (network, auth, parse) yields a
ProviderFailure entry and the run continues. A run where every provider
fails returns success=False with per-provider errors — never an exception,
never a silent substitution (there is NO generative fallback anywhere in
this module).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from lib.footage_hub.contracts import NormalizedAsset
from lib.footage_hub.rights import RightsMode, RightsStatus, classify, validate
from lib.footage_hub.rights import validate_with_mode
from lib.footage_hub.verify import MediaCorruptError, probe_file


@dataclass
class ProviderFailure:
    provider: str
    phase: str  # "search" | "download"
    error: str

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "phase": self.phase, "error": self.error}


@dataclass
class SearchResult:
    assets: list[NormalizedAsset] = field(default_factory=list)
    failures: list[ProviderFailure] = field(default_factory=list)
    resolved_providers: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.assets)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_candidate(candidate: Any) -> NormalizedAsset:
    """Candidate -> NormalizedAsset. Provenance + license copied verbatim."""
    from urllib.parse import urlparse

    dl = getattr(candidate, "download_url", "") or ""
    fmt = Path(urlparse(dl).path).suffix.lower().lstrip(".")
    extra = dict(getattr(candidate, "extra", {}) or {})
    lic = getattr(candidate, "license", "") or ""
    creator = getattr(candidate, "creator", "") or ""
    title_bits = (getattr(candidate, "source_tags", "") or "").split()
    title = " ".join(title_bits[:12])
    return NormalizedAsset(
        provider=getattr(candidate, "source", ""),
        source_id=getattr(candidate, "source_id", ""),
        title=title,
        description=str(extra.get("description", "") or ""),
        source_url=getattr(candidate, "source_url", ""),
        download_url=dl,
        duration=float(getattr(candidate, "duration", 0.0) or 0.0),
        width=int(getattr(candidate, "width", 0) or 0),
        height=int(getattr(candidate, "height", 0) or 0),
        fps=float(extra.get("fps", 0.0) or 0.0),
        format=fmt,
        creator=creator,
        license=lic,
        rights_status=classify(lic),
        attribution=creator,
        retrieved_at=_utcnow(),
        checksum="",
        kind=getattr(candidate, "kind", "video") or "video",
        extra=extra,
    )


def search(
    query: str,
    *,
    kind: str = "video",
    providers: Optional[list[str]] = None,
    per_provider: int = 10,
    require_verified_rights: bool = False,
    rights_mode: str = RightsMode.STRICT,
    min_width: Optional[int] = None,
    min_duration: Optional[float] = None,
    max_duration: Optional[float] = None,
    orientation: Optional[str] = None,
) -> SearchResult:
    """Fan out across providers with per-provider failure isolation.

    Rights default to strict production policy (verified rights only);
    pass rights_mode="permissive"/"audit-only" to relax explicitly.
    Resolution/duration/orientation constraints are forwarded to adapters
    via SearchFilters AND enforced post-normalization (adapters may
    ignore filters they don't understand).
    """
    from tools.video.stock_sources import SearchFilters, all_sources

    mode = RightsMode.STRICT if require_verified_rights else rights_mode
    if mode not in RightsMode.all():
        return SearchResult(failures=[ProviderFailure(
            "*", "search", f"unknown rights mode {mode!r}")])

    wanted = {s.name: s for s in all_sources()}
    if providers:
        unknown = [p for p in providers if p not in wanted]
        if unknown:
            return SearchResult(
                failures=[ProviderFailure(p, "search",
                                          f"unknown provider {p!r}") for p in unknown])
        sources = [wanted[p] for p in providers]
    else:
        sources = list(wanted.values())

    result = SearchResult()
    for src in sources:
        try:
            if not src.is_available():
                continue
            result.resolved_providers.append(src.name)
            filters = SearchFilters(kind=kind, per_page=per_provider,
                                    min_duration=min_duration,
                                    max_duration=max_duration,
                                    orientation=orientation,
                                    min_width=min_width)
            for cand in src.search(query, filters):
                try:
                    asset = normalize_candidate(cand)
                except Exception as exc:
                    result.failures.append(ProviderFailure(
                        src.name, "search",
                        f"normalize failed: {type(exc).__name__}: {exc}"))
                    continue
                if kind != "any" and asset.kind != kind:
                    continue  # image/video media type enforced, not assumed
                if not _passes_filters(asset, min_width=min_width,
                                       min_duration=min_duration,
                                       max_duration=max_duration,
                                       orientation=orientation):
                    continue
                ok, _ = validate_with_mode(asset, mode)
                if ok:
                    result.assets.append(asset)
        except Exception as exc:
            result.failures.append(ProviderFailure(
                src.name, "search", f"{type(exc).__name__}: {exc}"))
    result.assets = rank_assets(query, result.assets)
    return result


def _passes_filters(asset: NormalizedAsset, *,
                    min_width: Optional[int] = None,
                    min_duration: Optional[float] = None,
                    max_duration: Optional[float] = None,
                    orientation: Optional[str] = None) -> bool:
    """Post-normalization enforcement (adapters may ignore SearchFilters)."""
    if min_width is not None and (asset.width or 0) < min_width:
        return False
    if asset.kind == "video":
        if min_duration is not None and (asset.duration or 0) < min_duration:
            return False
        if max_duration is not None and (asset.duration or 0) > max_duration:
            return False
    if orientation not in (None, "any"):
        if orientation not in ("landscape", "portrait", "square"):
            return False
        if asset.orientation != orientation:
            # Unknown dimensions cannot satisfy an explicit orientation
            # demand (fail closed).
            return False
    return True


def coverage_verdict(*, found: bool, slot_match: bool = True,
                     rights_ok: bool = True, media_ok: bool = True) -> str:
    """Slot-coverage verdict for footage intelligence reporting.

    MISSING — no candidate acquired for the slot (gap, never filled
      synthetically).
    WRONG   — candidates exist but none match the slot intent/kind.
    WEAK    — a match exists but rights are unverified or the media is
      unverified/corrupt (needs re-acquisition or human clearance).
    PASS    — matched, rights-verified, media-verified.
    """
    if not found:
        return "MISSING"
    if not slot_match:
        return "WRONG"
    if not (rights_ok and media_ok):
        return "WEAK"
    return "PASS"


def rank_assets(query: str, assets: list[NormalizedAsset]) -> list[NormalizedAsset]:
    """Deterministic pre-rank. Same input multiset => same output order.

    Key: (-token_overlap, -resolution, provider, source_id). No randomness,
    no wall-clock, no network. Semantic rerank remains lib/corpus.py's job.
    """
    tokens = {t.lower() for t in query.split() if t}
    scored: list[tuple[tuple, NormalizedAsset]] = []
    for a in assets:
        hay = f"{a.title} {a.provider}".lower()
        overlap = sum(1 for t in tokens if t in hay)
        res = (a.width or 0) * (a.height or 0)
        scored.append(((-overlap, -res, a.provider, a.source_id), a))
    scored.sort(key=lambda s: s[0])
    return [a for _, a in scored]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


class DownloadManager:
    """Content-addressed downloads with checksum dedupe + vault integration.

    Layout under vault_dir:
      blobs/<sha256hex>.<ext>   — one copy per unique byte string
      footage_hub_manifest.jsonl — one row per asset_id (provenance + blob ref)
      checksums.json             — sha256 -> {"blob": ..., "aliases": [asset_id]}
    Identical bytes from different providers collapse to one blob; every
    alias keeps its own provenance row. Bytes are additionally ingested
    into ClipCache so corpus_builder reuses them without re-downloading.
    """

    def __init__(self, vault_dir: Path) -> None:
        self.vault_dir = Path(vault_dir)
        self.blobs_dir = self.vault_dir / "blobs"
        self.manifest_path = self.vault_dir / "footage_hub_manifest.jsonl"
        self.checksum_path = self.vault_dir / "checksums.json"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)

    # -- public ------------------------------------------------------

    def download(self, asset: NormalizedAsset,
                 adapter: Any, *,
                 max_retries: int = 2,
                 retry_backoff_seconds: float = 0.5
                 ) -> tuple[NormalizedAsset, bool]:
        """Download one asset. Returns (asset_with_checksum, is_new_blob).

        Transient transport errors (OSError family, incl. requests network
        errors) retry with linear backoff; anything else — empty file,
        corrupt media, adapter bugs — fails fast with no retry. Either way
        failure propagates as failure: never substituted, never silenced.
        """
        from lib.footage_hub.registry import get_adapter  # noqa (kept local: registry seam)

        _ = get_adapter  # adapter passed in; registry remains the lookup path
        attempt = 0
        while True:
            try:
                return self._download_once(asset, adapter)
            except OSError:
                if attempt >= max_retries:
                    raise
                attempt += 1
                time.sleep(retry_backoff_seconds * attempt)

    def _download_once(self, asset: NormalizedAsset,
                       adapter: Any) -> tuple[NormalizedAsset, bool]:
        tmp = self.blobs_dir / f".tmp_{asset.asset_id}_{os.getpid()}"
        try:
            adapter.download(_to_candidate(asset), tmp)
            if not tmp.exists() or tmp.stat().st_size < 1024:
                raise ValueError(f"download produced empty file for {asset.asset_id}")
            # Media verification (best available: ffprobe > ffmpeg parse >
            # stdlib sniff). Proven-corrupt bytes raise MediaCorruptError
            # (fail closed, no retry); unrecognized-but-unproven bytes are
            # recorded as unverified and proceed — unknown != corrupt.
            report = probe_file(tmp, kind=asset.kind)
            asset.extra["verification"] = report
            self._enrich_from_probe(asset, report)
            checksum = sha256_file(tmp)
            index = self._read_index()
            if checksum in index:
                blob = index[checksum]["blob"]
                aliases = index[checksum].setdefault("aliases", [])
                if asset.asset_id not in aliases:
                    aliases.append(asset.asset_id)
                is_new = False
            else:
                ext = Path(asset.download_url.split("?")[0]).suffix or ".mp4"
                blob = f"blobs/{checksum[7:16]}{ext}"
                (self.vault_dir / blob).parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp, self.vault_dir / blob)
                index[checksum] = {"blob": blob, "aliases": [asset.asset_id]}
                is_new = True
            self._write_index(index)
            asset.checksum = checksum
            asset.local_path = index[checksum]["blob"]
            asset.format = Path(asset.local_path).suffix.lstrip(".") or asset.format
            self._append_manifest(asset)
            self._ingest_cache(asset)
            return asset, is_new
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    # -- internals ---------------------------------------------------

    @staticmethod
    def _enrich_from_probe(asset: NormalizedAsset,
                           report: dict[str, Any]) -> None:
        """Fill unknown dimensions from measured probe values.

        Only fills fields the provider left at zero — provider metadata is
        never overwritten, measured values are additive enrichment.
        """
        for field in ("width", "height"):
            try:
                measured = int(report.get(field) or 0)
            except (TypeError, ValueError):
                measured = 0
            if not getattr(asset, field, 0) and measured > 0:
                setattr(asset, field, measured)
        for field in ("fps", "duration"):
            try:
                measured_f = float(report.get(field) or 0.0)
            except (TypeError, ValueError):
                measured_f = 0.0
            if not getattr(asset, field, 0.0) and measured_f > 0:
                setattr(asset, field, measured_f)

    def _read_index(self) -> dict[str, Any]:
        if not self.checksum_path.exists():
            return {}
        try:
            with open(self.checksum_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_index(self, index: dict[str, Any]) -> None:
        tmp = self.checksum_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)
        os.replace(tmp, self.checksum_path)

    def _append_manifest(self, asset: NormalizedAsset) -> None:
        with open(self.manifest_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asset.to_dict()) + "\n")

    def _ingest_cache(self, asset: NormalizedAsset) -> None:
        try:
            from tools.video.clip_cache import get_default_cache

            blob_abs = self.vault_dir / asset.local_path
            get_default_cache().ingest(asset.asset_id, blob_abs, metadata={
                "source": asset.provider, "source_id": asset.source_id,
                "source_url": asset.source_url, "license": asset.license,
                "creator": asset.creator, "source_tags": asset.title,
            })
        except Exception:
            pass  # cache faults never block the pipeline


def _to_candidate(asset: NormalizedAsset) -> Any:
    """Rebuild the minimal download surface adapters expect."""
    from tools.video.stock_sources.base import Candidate

    return Candidate(
        source=asset.provider, source_id=asset.source_id,
        source_url=asset.source_url, download_url=asset.download_url,
        kind=asset.kind, width=asset.width, height=asset.height,
        duration=asset.duration, creator=asset.creator, license=asset.license,
        source_tags=asset.title, extra=dict(asset.extra),
    )


def manifest_rows(vault_dir: Path) -> list[dict[str, Any]]:
    """Read back the vault manifest (provenance audit)."""
    path = Path(vault_dir) / "footage_hub_manifest.jsonl"
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


__all__ = ["DownloadManager", "ProviderFailure", "SearchResult",
           "coverage_verdict", "manifest_rows", "normalize_candidate",
           "rank_assets", "search", "sha256_file"]
