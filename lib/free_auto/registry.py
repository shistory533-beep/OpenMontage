"""Data-driven model registry for FREE-AUTO.

The registry is seed data, not the decision: ranking comes from
lib/free_auto/scoring.py applied to registry capabilities plus live
telemetry from lib/free_auto/health.py. Router-style entries and
safety-classifier entries are marked ineligible as general candidates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parent / "model_registry.json"

# Model IDs that are routers, never leaf candidates.
ROUTER_IDS = {
    "openrouter/auto",
    "openrouter/free",
    "openrouter/fusion",
    "openrouter/bodybuilder",
    "openrouter/pareto-code",
    "kilo-auto/free",
    "kilo-auto/balanced",
    "kilo-auto/efficient",
    "kilo-auto/frontier",
    "kilo-auto/small",
}

# Classifier-only models: never general coding candidates.
SAFETY_ONLY_IDS = {
    "nvidia/nemotron-3.5-content-safety",
}


@dataclass(frozen=True)
class Upstream:
    gateway: str  # "openrouter" | "kilo"
    model: str  # upstream model ID on that gateway
    free_tier: str = "unknown"  # "free" | "paid" | "unknown"
    api_key_env: str = "OPENROUTER_API_KEY"
    base_url_env: str = "OPENROUTER_BASE_URL"
    base_url_default: str | None = None

    def normalized_free_tier(self) -> str:
        tier = (self.free_tier or "unknown").strip().lower()
        return tier if tier in ("free", "paid") else "unknown"


@dataclass(frozen=True)
class ModelEntry:
    id: str
    display: str
    category: str
    upstreams: tuple[Upstream, ...]
    tool_use: bool | None = None
    structured_output: bool | None = None
    context_tokens: int | None = None
    multimodal: bool | None = None
    reasoning: bool = False
    prior_quality: float | None = None
    prior_coding: float | None = None
    prior_reasoning: float | None = None
    prior_agentic: float | None = None
    latency_class: str = "medium"
    benchmark_source: str | None = None
    benchmark_date: str | None = None
    benchmark_note: str = ""
    initial_priority: int = 99
    experimental: bool = False

    @property
    def has_measured_benchmark(self) -> bool:
        return bool(self.benchmark_source)


@dataclass
class Registry:
    entries: list[ModelEntry] = field(default_factory=list)

    def eligible(self) -> list[ModelEntry]:
        """Leaf candidates only: no routers, no safety-classifiers."""
        out = []
        for e in self.entries:
            if e.id in ROUTER_IDS or e.id in SAFETY_ONLY_IDS:
                continue
            out.append(e)
        return out

    def by_id(self, candidate_id: str) -> ModelEntry | None:
        for e in self.entries:
            if e.id == candidate_id:
                return e
        return None

    def free_tier_for(self, candidate_id: str, gateway: str,
                      upstream_model: str) -> str:
        """Verified free status of one provider:model upstream."""
        entry = self.by_id(candidate_id)
        if entry is None:
            return "unknown"
        for up in entry.upstreams:
            if up.gateway == gateway and up.model == upstream_model:
                return up.normalized_free_tier()
        return "unknown"

    def free_only_entries(self) -> list[ModelEntry]:
        """Entries with at least one upstream not known-paid.

        Unknown stays eligible (untested != incapable); only explicit
        "paid" on EVERY upstream drops the entry.
        """
        out = []
        for e in self.eligible():
            tiers = [u.normalized_free_tier() for u in e.upstreams]
            if tiers and all(t == "paid" for t in tiers):
                continue
            out.append(e)
        return out

    def filter_for_task(
        self,
        *,
        needs_multimodal: bool,
        needs_tool_use: bool = False,
        needs_structured_output: bool = False,
    ) -> list[ModelEntry]:
        """Drop candidates that cannot satisfy hard capability requirements.

        Unknown (None) capabilities stay eligible: unknown means untested,
        not incapable. Only explicit False is filtered.
        """
        out = []
        for e in self.eligible():
            if needs_multimodal and e.multimodal is False:
                continue
            if needs_tool_use and e.tool_use is False:
                continue
            if needs_structured_output and e.structured_output is False:
                continue
            out.append(e)
        return out


def _entry_from_dict(raw: dict[str, Any]) -> ModelEntry:
    caps = raw.get("capabilities", {})
    priors = raw.get("priors", {})
    bench = raw.get("benchmark", {})
    return ModelEntry(
        id=raw["id"],
        display=raw.get("display", raw["id"]),
        category=raw.get("category", "general-coding"),
        upstreams=tuple(Upstream(**u) for u in raw.get("upstreams", [])),
        tool_use=caps.get("tool_use"),
        structured_output=caps.get("structured_output"),
        context_tokens=caps.get("context_tokens"),
        multimodal=caps.get("multimodal"),
        reasoning=bool(caps.get("reasoning", False)),
        prior_quality=priors.get("quality"),
        prior_coding=priors.get("coding"),
        prior_reasoning=priors.get("reasoning"),
        prior_agentic=priors.get("agentic"),
        latency_class=raw.get("latency_class", "medium"),
        benchmark_source=bench.get("source"),
        benchmark_date=bench.get("date"),
        benchmark_note=bench.get("note", ""),
        initial_priority=int(raw.get("initial_priority", 99)),
        experimental=bool(raw.get("experimental", False)),
    )


def load_registry(path: str | Path = REGISTRY_PATH) -> Registry:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return Registry(entries=[_entry_from_dict(e) for e in raw["models"]])
