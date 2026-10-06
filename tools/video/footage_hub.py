"""FootageHub tool — thin agent-facing wrapper over lib/footage_hub.

Capability: clip_acquisition (same family as direct_clip_search, listed as
a fallback). No generative capability anywhere in this module or its
lib/footage_hub/* dependencies — missing footage is reported as a gap,
never synthesized.

Operations:
  capabilities — advertise every provider (availability + media support)
  search       — normalized, rights-filtered, deterministically ranked assets
  download     — content-addressed download of one asset into a vault dir
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
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class FootageHub(BaseTool):
    name = "footage_hub"
    version = "0.1.0"
    tier = ToolTier.SOURCE
    capability = "clip_acquisition"
    provider = "openmontage"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.HYBRID  # local logic + network source APIs

    dependencies = ["python:requests"]
    install_instructions = (
        "No provider is mandatory. Keyless sources (archive.org, NASA, "
        "Wikimedia, Openverse, Library of Congress) work out of the box. "
        "Optional free keys unlock more: PEXELS_API_KEY, PIXABAY_API_KEY, "
        "UNSPLASH_ACCESS_KEY, DVIDS_API_KEY."
    )
    agent_skills = []

    capabilities = ["provider_search", "rights_filtering", "deterministic_ranking",
                    "content_addressed_download"]
    supports = {"multi_source": True, "video_and_image": True,
                "rights_policy": True, "dedupe_by_checksum": True,
                "generative_fallback": False}
    best_for = ["real-footage discovery with provenance and rights tracking",
                "multi-provider documentary B-roll acquisition",
                "free/local-first footage pipelines"]
    not_good_for = ["AI-generated filler (explicitly unsupported — no such path)",
                    "semantic embedding retrieval (use corpus_builder + clip_search)"]
    fallback_tools = ["direct_clip_search", "corpus_builder"]

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {"type": "string",
                          "enum": ["capabilities", "search", "download"]},
            "query": {"type": "string"},
            "kind": {"type": "string", "enum": ["video", "image", "any"],
                     "default": "video"},
            "providers": {"type": "array", "items": {"type": "string"}},
            "per_provider": {"type": "integer", "default": 10,
                             "minimum": 1, "maximum": 50},
            "require_verified_rights": {"type": "boolean", "default": False},
            "vault_dir": {"type": "string"},
            "asset": {"type": "object",
                      "description": "NormalizedAsset dict from a prior search."},
            "provider": {"type": "string",
                         "description": "Adapter name for download."},
        },
    }
    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=2000, network_required=True)
    side_effects = ["calls provider search APIs",
                    "downloads files into <vault_dir>/blobs"]
    user_visible_verification = [
        "Inspect returned assets' provider/license/rights_status fields",
        "Open <vault_dir>/footage_hub_manifest.jsonl for the provenance log",
    ]

    def get_status(self) -> ToolStatus:
        try:
            from tools.video.stock_sources import available_sources
            return (ToolStatus.AVAILABLE if available_sources()
                    else ToolStatus.UNAVAILABLE)
        except Exception:
            return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0  # all hub providers are free-tier paths

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            op = inputs["operation"]
            if op == "capabilities":
                from lib.footage_hub.registry import capability_map

                return ToolResult(success=True,
                                  data={"providers": capability_map()},
                                  duration_seconds=round(time.time() - start, 3))
            if op == "search":
                from lib.footage_hub import hub as fh

                res = fh.search(
                    inputs.get("query", ""),
                    kind=inputs.get("kind", "video"),
                    providers=inputs.get("providers"),
                    per_provider=int(inputs.get("per_provider", 10)),
                    require_verified_rights=bool(
                        inputs.get("require_verified_rights", False)),
                )
                return ToolResult(
                    success=True,
                    data={"assets": [a.to_dict() for a in res.assets],
                          "failures": [f.to_dict() for f in res.failures],
                          "resolved_providers": res.resolved_providers},
                    cost_usd=0.0,
                    duration_seconds=round(time.time() - start, 3))
            if op == "download":
                from lib.footage_hub import hub as fh
                from lib.footage_hub.contracts import NormalizedAsset
                from lib.footage_hub.registry import get_adapter

                if not inputs.get("vault_dir") or not inputs.get("asset"):
                    return ToolResult(success=False,
                                      error="download requires vault_dir + asset")
                asset = NormalizedAsset.from_dict(dict(inputs["asset"]))
                adapter = get_adapter(inputs.get("provider") or asset.provider)
                mgr = fh.DownloadManager(Path(inputs["vault_dir"]))
                asset, is_new = mgr.download(asset, adapter)
                return ToolResult(
                    success=True,
                    data={"asset": asset.to_dict(), "is_new_blob": is_new},
                    artifacts=[asset.local_path],
                    duration_seconds=round(time.time() - start, 3))
            return ToolResult(success=False, error=f"Unknown operation: {op!r}")
        except Exception as exc:
            import traceback
            return ToolResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-800:]}")
