"""Explainable candidate scoring for FREE-AUTO.

Twelve normalized components; per-task weights. Deterministic: identical
registry + telemetry snapshots always produce identical rankings and scores.

Unknown capabilities score neutral (0.5) but carry a confidence penalty, so
unmeasured models stay eligible yet rank below equally good measured ones.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lib.free_auto.health import HealthStore
from lib.free_auto.registry import ModelEntry
from lib.free_auto.task_classify import Complexity, TaskClass

COMPONENTS = (
    "quality",
    "coding",
    "reasoning",
    "agentic",
    "tool_use",
    "structured_output",
    "context",
    "multimodal",
    "reliability",
    "latency",
    "quota_health",
    "historical_success",
)

# Per-task weights. Each row sums to 1.0.
TASK_WEIGHTS: dict[TaskClass, dict[str, float]] = {
    TaskClass.CODING: {
        "quality": 0.12, "coding": 0.24, "reasoning": 0.10, "agentic": 0.14,
        "tool_use": 0.12, "structured_output": 0.06, "context": 0.06,
        "multimodal": 0.0, "reliability": 0.06, "latency": 0.03,
        "quota_health": 0.04, "historical_success": 0.03,
    },
    TaskClass.PLANNING: {
        "quality": 0.14, "coding": 0.08, "reasoning": 0.24, "agentic": 0.20,
        "tool_use": 0.06, "structured_output": 0.04, "context": 0.08,
        "multimodal": 0.0, "reliability": 0.06, "latency": 0.02,
        "quota_health": 0.04, "historical_success": 0.04,
    },
    TaskClass.RESEARCH: {
        "quality": 0.16, "coding": 0.02, "reasoning": 0.20, "agentic": 0.06,
        "tool_use": 0.04, "structured_output": 0.04, "context": 0.18,
        "multimodal": 0.02, "reliability": 0.08, "latency": 0.04,
        "quota_health": 0.08, "historical_success": 0.08,
    },
    TaskClass.MULTIMODAL: {
        "quality": 0.12, "coding": 0.04, "reasoning": 0.08, "agentic": 0.06,
        "tool_use": 0.04, "structured_output": 0.04, "context": 0.06,
        "multimodal": 0.30, "reliability": 0.08, "latency": 0.04,
        "quota_health": 0.07, "historical_success": 0.07,
    },
    TaskClass.FAST_SIMPLE: {
        "quality": 0.08, "coding": 0.04, "reasoning": 0.04, "agentic": 0.02,
        "tool_use": 0.02, "structured_output": 0.02, "context": 0.02,
        "multimodal": 0.0, "reliability": 0.08, "latency": 0.34,
        "quota_health": 0.17, "historical_success": 0.17,
    },
    TaskClass.GENERAL: {
        "quality": 0.16, "coding": 0.10, "reasoning": 0.12, "agentic": 0.10,
        "tool_use": 0.08, "structured_output": 0.06, "context": 0.08,
        "multimodal": 0.02, "reliability": 0.08, "latency": 0.06,
        "quota_health": 0.07, "historical_success": 0.07,
    },
}

_LATENCY_SCORE = {"fast": 0.9, "medium": 0.6, "slow": 0.3}


def _ema_latency_score(latency_ms_ema: float | None) -> float | None:
    """Measured latency EMA -> 0..1. None when unmeasured (use static class)."""
    if latency_ms_ema is None:
        return None
    if latency_ms_ema > 8000:
        return 0.2
    if latency_ms_ema > 3000:
        return 0.4
    if latency_ms_ema > 1500:
        return 0.6
    if latency_ms_ema > 600:
        return 0.75
    return 0.9


# Provider policy: prefer verified-free upstreams, avoid known-paid ones.
# Kept as a small total adjustment (not a 13th component) so the 12-component
# weight table and its per-task rows stay untouched and comparable.
_FREE_TIER_ADJUST = {"free": 0.03, "unknown": 0.0, "paid": -0.05}


def _complexity_weights(task_class: TaskClass,
                        complexity: Complexity | None) -> dict[str, float]:
    """Per-task weights, optionally re-weighted for adaptive depth.

    None (or T1/T2) returns the base row unchanged, so existing rankings are
    bit-identical unless a depth tier is explicitly in play. T0 doubles the
    latency voice (fastest capable); T3 boosts quality/reasoning/agentic
    (strongest eligible). Renormalized to sum 1.0.
    """
    base = TASK_WEIGHTS[task_class]
    if complexity is None or complexity in (Complexity.T1, Complexity.T2):
        return base
    weights = dict(base)
    if complexity is Complexity.T0:
        weights["latency"] = weights.get("latency", 0.0) * 2.0
    elif complexity is Complexity.T3:
        for c in ("quality", "reasoning", "agentic"):
            weights[c] = weights.get(c, 0.0) * 1.5
    total = sum(weights[c] for c in COMPONENTS) or 1.0
    return {c: weights[c] / total for c in COMPONENTS}


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    gateway: str
    upstream_model: str
    task_class: TaskClass
    components: dict[str, float]
    total: float
    confidence: float
    explanation: str


def _cap(value: bool | None) -> tuple[float, bool]:
    """Capability flag -> (score, known). Unknown is neutral, not zero."""
    if value is None:
        return 0.5, False
    return (1.0 if value else 0.0), True


def score_candidate(
    entry: ModelEntry,
    *,
    task_class: TaskClass,
    health: HealthStore,
    gateway: str,
    upstream_model: str,
    free_tier: str = "unknown",
    complexity: Complexity | None = None,
    latency_ema_ms: float | None = None,
) -> CandidateScore:
    key = HealthStore.key(entry.id, gateway, upstream_model)

    quality = entry.prior_quality if entry.prior_quality is not None else 0.5
    coding = entry.prior_coding if entry.prior_coding is not None else 0.5
    reasoning = entry.prior_reasoning if entry.prior_reasoning is not None else 0.5
    agentic = entry.prior_agentic if entry.prior_agentic is not None else 0.5
    known_priors = entry.prior_quality is not None

    tool_use, known_tool = _cap(entry.tool_use)
    structured_output, known_so = _cap(entry.structured_output)
    if entry.context_tokens and entry.context_tokens >= 128000:
        context = 1.0
    elif entry.context_tokens and entry.context_tokens >= 32000:
        context = 0.7
    elif entry.context_tokens:
        context = 0.4
    else:
        context = 0.5
    known_context = entry.context_tokens is not None
    multimodal, known_mm = _cap(entry.multimodal)

    h = health._entries.get(key)
    # Live agentic reliability overrides the static prior when measured.
    # A candidate with no telemetry stays on its prior (unknown != incapable).
    if h is not None and h.tool_call_attempts:
        tool_use = 1.0 - (h.tool_call_failures / h.tool_call_attempts)
        known_tool = True
    if h is not None and h.so_attempts:
        structured_output = 1.0 - (h.so_failures / h.so_attempts)
        known_so = True
    if h is not None and h.consecutive_failures:
        reliability = max(0.0, 1.0 - 0.25 * h.consecutive_failures)
    elif h is not None and h.consecutive_successes:
        reliability = 1.0
    else:
        reliability = 0.7
    latency_static = _LATENCY_SCORE.get(entry.latency_class, 0.6)
    measured = _ema_latency_score(latency_ema_ms)
    # Blend static prior with measured EMA when telemetry exists; a candidate
    # with no telemetry stays on its prior (unknown != incapable).
    latency = (0.5 * latency_static + 0.5 * measured) if measured is not None else latency_static
    quota = health.quota_health(key)
    hist = health.historical_success(key)
    historical_success = hist if hist is not None else 0.5

    components = {
        "quality": quality,
        "coding": coding,
        "reasoning": reasoning,
        "agentic": agentic,
        "tool_use": tool_use,
        "structured_output": structured_output,
        "context": context,
        "multimodal": multimodal,
        "reliability": reliability,
        "latency": latency,
        "quota_health": quota,
        "historical_success": historical_success,
    }
    weights = _complexity_weights(task_class, complexity)
    total = sum(components[c] * weights[c] for c in COMPONENTS)
    total += _FREE_TIER_ADJUST.get(free_tier, 0.0)

    known_flags = [known_priors, known_tool, known_so, known_context, known_mm,
                   entry.has_measured_benchmark]
    confidence = 0.7 + 0.3 * (sum(1 for f in known_flags if f) / len(known_flags))
    if entry.experimental:
        confidence *= 0.9

    top = sorted(COMPONENTS, key=lambda c: components[c] * weights[c], reverse=True)[:3]
    explanation = (
        f"{entry.id} via {gateway}/{upstream_model} for {task_class.value}: "
        f"{total:.3f} (conf {confidence:.2f}); "
        + ", ".join(f"{c}={components[c]:.2f}(w={weights[c]:.2f})" for c in top)
    )
    return CandidateScore(
        candidate_id=entry.id,
        gateway=gateway,
        upstream_model=upstream_model,
        task_class=task_class,
        components=components,
        total=round(total, 6),
        confidence=round(confidence, 4),
        explanation=explanation,
    )


@dataclass
class RankedCandidate:
    entry: ModelEntry
    gateway: str
    upstream_model: str
    base_url: str
    api_key_env: str
    score: CandidateScore

    def health_key(self) -> str:
        return HealthStore.key(self.entry.id, self.gateway, self.upstream_model)


def rank_candidates(
    entries: list[ModelEntry],
    *,
    task_class: TaskClass,
    health: HealthStore,
    env: dict[str, str] | None = None,
    include_unconfigured: bool = False,
    complexity: Complexity | None = None,
    free_tier_for: Callable[[str, str, str], str] | None = None,
) -> list[RankedCandidate]:
    """Order (candidate x configured upstream) best-first. Deterministic.

    Ties break by (total desc, confidence desc, initial_priority asc,
    candidate id asc, gateway asc) so output is fully reproducible.
    complexity=None and unknown free tiers reproduce legacy scores exactly.
    """
    import os as _os

    ranked: list[RankedCandidate] = []
    for entry in entries:
        for up in entry.upstreams:
            api_key = (env or _os.environ).get(up.api_key_env, "")
            base_url = (env or _os.environ).get(up.base_url_env, "") or (up.base_url_default or "")
            if not api_key or not base_url:
                if not include_unconfigured:
                    continue
                api_key = api_key or ""
                base_url = base_url or ""
            key = HealthStore.key(entry.id, up.gateway, up.model)
            eligible, _ = health.is_eligible(key)
            if not eligible:
                continue
            tier = (free_tier_for(entry.id, up.gateway, up.model)
                    if free_tier_for is not None
                    else getattr(up, "normalized_free_tier", lambda: "unknown")())
            h = health._entries.get(key)
            ema = h.latency_ms_ema if h is not None else None
            score = score_candidate(
                entry, task_class=task_class, health=health,
                gateway=up.gateway, upstream_model=up.model,
                free_tier=tier, complexity=complexity, latency_ema_ms=ema,
            )
            ranked.append(RankedCandidate(
                entry=entry, gateway=up.gateway, upstream_model=up.model,
                base_url=base_url.rstrip("/"), api_key_env=up.api_key_env,
                score=score,
            ))
    ranked.sort(
        key=lambda r: (
            -r.score.total, -r.score.confidence,
            r.entry.initial_priority, r.entry.id, r.gateway,
        )
    )
    return ranked


def format_ranking(ranked: list[RankedCandidate], top_n: int = 10) -> str:
    lines = []
    for i, r in enumerate(ranked[:top_n], 1):
        lines.append(
            f"  {i}. {r.entry.id} via {r.gateway}/{r.upstream_model} "
            f"score={r.score.total:.3f} conf={r.score.confidence:.2f}"
        )
    return "\n".join(lines)


def snapshot_for_status(ranked: list[RankedCandidate], top_n: int = 10) -> list[dict[str, Any]]:
    return [
        {
            "candidate": r.entry.id,
            "gateway": r.gateway,
            "upstream_model": r.upstream_model,
            "score": r.score.total,
            "confidence": r.score.confidence,
            "reason": r.score.explanation,
        }
        for r in ranked[:top_n]
    ]
