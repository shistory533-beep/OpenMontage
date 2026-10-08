"""Task classification for FREE-AUTO routing.

Deterministic keyword heuristic over the request's text content. This mirrors
the tokenization philosophy of lib/scoring.py (overlap of intent tokens with
known signal sets) but is scoped to LLM chat tasks, so it does not duplicate
the media-provider scorer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re


class TaskClass(str, Enum):
    CODING = "coding"
    PLANNING = "planning"
    RESEARCH = "research"
    MULTIMODAL = "multimodal"
    FAST_SIMPLE = "fast_simple"
    GENERAL = "general"


class Complexity(str, Enum):
    """Adaptive depth tier: T0 trivial -> T3 architectural/high-risk.

    T0: one-liner, greeting, rename, typo — fastest capable model wins.
    T1: local single-file edit — efficient coding model.
    T2: multi-file feature — strong coding/reasoning model.
    T3: architectural, review, or high-risk — strongest eligible model.
    """

    T0 = "t0"
    T1 = "t1"
    T2 = "t2"
    T3 = "t3"


_TOKEN_RE = re.compile(r"[a-z0-9](?:[a-z0-9+._-]*[a-z0-9])?")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


# Signal keyword sets. Kept small and literal on purpose: classification must
# be explainable and deterministic, not clever.
_SIGNALS: dict[TaskClass, set[str]] = {
    TaskClass.CODING: {
        "code", "coding", "function", "bug", "debug", "refactor", "implement",
        "test", "tests", "pytest", "typescript", "python", "javascript",
        "compile", "error", "traceback", "stacktrace", "api", "sdk",
        "regex", "sql", "script", "cli", "docker", "git", "merge",
        "pull", "commit", "review", "lint", "typecheck", "patch", "diff",
    },
    TaskClass.PLANNING: {
        "plan", "planning", "design", "architect", "architecture", "strategy",
        "roadmap", "steps", "breakdown", "approach", "proposal", "decide",
        "decision", "tradeoff", "compare", "evaluate", "spec", "specification",
        "orchestrate", "workflow",
    },
    TaskClass.RESEARCH: {
        "research", "summarize", "summary", "explain", "what", "why", "how",
        "compare", "survey", "literature", "paper", "docs", "documentation",
        "find", "search", "lookup", "overview", "analyse", "analyze",
        "benchmark", "benchmarks", "evidence", "sources",
    },
    TaskClass.MULTIMODAL: {
        "image", "images", "picture", "photo", "screenshot", "video",
        "audio", "diagram", "chart", "figure", "vision", "ocr", "draw",
        "thumbnail", "frame", "attachment",
    },
    TaskClass.FAST_SIMPLE: {
        "hi", "hello", "hey", "thanks", "ok", "yes", "no", "ping",
        "quick", "short", "one-line", "translate", "rephrase", "typo",
        "format", "rename",
    },
}

# Priority when several classes match: specific beats generic. MULTIMODAL is
# a capability gate (checked first by the registry filter), then CODING and
# PLANNING outrank RESEARCH, which outranks FAST_SIMPLE.
_PRECEDENCE = (
    TaskClass.MULTIMODAL,
    TaskClass.CODING,
    TaskClass.PLANNING,
    TaskClass.RESEARCH,
    TaskClass.FAST_SIMPLE,
)


@dataclass(frozen=True)
class Classification:
    task_class: TaskClass
    confidence: float
    signals: tuple[str, ...] = field(default_factory=tuple)
    complexity: Complexity = Complexity.T2


# Explicit depth tags win over heuristics: "[T0]" .. "[T3]", "T3:" prefix, etc.
_COMPLEXITY_TAG_RE = re.compile(r"\b[Tt]([0-3])\b")

# Heuristic signals for the high end: architecture/review language.
_T3_SIGNALS = {
    "architect", "architecture", "roadmap", "strategy", "tradeoff",
    "review", "audit", "security", "migration", "redesign", "specification",
    "orchestrate", "workflow",
}

# Heuristic signals for a scoped local edit (T1): single-file verbs.
_T1_SIGNALS = {
    "rename", "typo", "format", "rephrase", "translate", "one-line",
    "oneliner",
}


def detect_complexity(messages, task_class: TaskClass) -> Complexity:
    """Detect adaptive depth tier. Pure function: same input, same output."""
    text = _extract_text(messages)
    tag = _COMPLEXITY_TAG_RE.search(text or "")
    if tag:
        return Complexity(f"t{tag.group(1)}")
    toks = _tokens(text)
    if task_class is TaskClass.FAST_SIMPLE:
        return Complexity.T0
    if task_class is TaskClass.MULTIMODAL:
        return Complexity.T2
    if toks & _T3_SIGNALS or (
        task_class is TaskClass.PLANNING and len(toks) > 60
    ):
        return Complexity.T3
    if toks & _T1_SIGNALS and len(toks) <= 24:
        return Complexity.T1
    if len(toks) <= 12:
        # Floor coding at T1: even a short code ask needs an efficient
        # coding model, not the fastest greeter.
        if task_class is TaskClass.CODING:
            return Complexity.T1
        return Complexity.T0
    if task_class is TaskClass.CODING and len(toks) > 80:
        return Complexity.T3
    return Complexity.T2


def parse_complexity(value: str | None) -> Complexity | None:
    """Parse an explicit complexity override ("t0".."t3", "T2", ...)."""
    if value is None:
        return None
    text = str(value).strip().lower().lstrip("t")
    if text in ("0", "1", "2", "3"):
        return Complexity(f"t{text}")
    return None


def _extract_text(messages) -> str:
    if isinstance(messages, str):
        return messages
    parts: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "image_url" and block.get("image_url"):
                        parts.append("image attachment")
                    elif isinstance(block.get("text"), str):
                        parts.append(block["text"])
    return "\n".join(parts)


def classify_task(messages) -> Classification:
    """Classify a chat request. Pure function: same input, same output."""
    text = _extract_text(messages)
    toks = _tokens(text)

    # Image content blocks force multimodal regardless of keywords.
    has_image_block = False
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") in ("image_url", "image", "input_image")
                for b in content
            ):
                has_image_block = True
    if has_image_block:
        return Classification(TaskClass.MULTIMODAL, 1.0, ("image_block",))

    hits: dict[TaskClass, set[str]] = {}
    for cls, signals in _SIGNALS.items():
        matched = toks & signals
        if matched:
            hits[cls] = matched

    if not hits:
        return Classification(TaskClass.GENERAL, 0.5, (),
                              detect_complexity(messages, TaskClass.GENERAL))

    # Short messages matching only FAST_SIMPLE stay fast; anything longer or
    # matching a specific class uses the specific class.
    specific = [c for c in _PRECEDENCE if c in hits]
    chosen = specific[0]
    if chosen is TaskClass.FAST_SIMPLE and len(toks) > 24:
        cls = Classification(TaskClass.GENERAL, 0.5, tuple(sorted(hits[chosen])))
        return Classification(cls.task_class, cls.confidence, cls.signals,
                              detect_complexity(messages, cls.task_class))
    strength = len(hits[chosen])
    confidence = min(1.0, 0.55 + 0.15 * strength)
    return Classification(
        chosen, confidence, tuple(sorted(hits[chosen])),
        detect_complexity(messages, chosen))
