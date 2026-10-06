"""Factory episode stage machine — pure deterministic FSM, no I/O.

Additive layer for the YouTube Factory. This module owns NOTHING except:
  - the canonical ordered stage list (one entry per Episode Package domain),
  - the allowed state transitions per stage,
  - a pure validator.

It does not touch the render pipeline, Timeline IR, footage intelligence,
narration implementation, or QA architecture. Persistence lives in
``lib/episode_store.py``; artifact schemas live in
``schemas/factory/episode_package.schema.json`` (envelope) plus the existing
``schemas/artifacts/*`` (payloads, when applicable).
"""

from __future__ import annotations

# One stage per Episode Package domain, in factory order.
FACTORY_STAGES: tuple[str, ...] = (
    "topic",
    "research",
    "sources",
    "facts",
    "claims",
    "script",
    "fact_check",
    "storyboard",
    "narration",
    "footage",
    "editorial",
    "timeline",
    "audio",
    "render",
    "qa",
    "thumbnail",
    "metadata",
    "publish",
    "analytics",
)

STAGE_STATES: tuple[str, ...] = (
    "PENDING",
    "RUNNING",
    "REVIEW",
    "APPROVED",
    "DONE",
    "FAILED",
)

# Deterministic transition table. Absent edge => IllegalTransitionError.
# DONE is terminal per artifact version; content change requires explicit
# reopen (DONE -> RUNNING, which bumps nothing by itself — the subsequent
# artifact write bumps the version). FAILED always carries a reason
# (enforced in episode_store, which requires failure_reason on FAILED).
_ALLOWED: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"RUNNING"}),
    "RUNNING": frozenset({"REVIEW", "APPROVED", "DONE", "FAILED"}),
    "REVIEW": frozenset({"APPROVED", "RUNNING", "FAILED"}),
    "APPROVED": frozenset({"DONE", "RUNNING"}),
    "DONE": frozenset({"RUNNING"}),
    "FAILED": frozenset({"RUNNING"}),
}


class IllegalTransitionError(ValueError):
    """Raised when a stage transition is not in the deterministic table."""


def validate_transition(stage: str, from_state: str, to_state: str) -> None:
    """Raise IllegalTransitionError if the edge is not allowed."""
    if stage not in FACTORY_STAGES:
        raise IllegalTransitionError(f"Unknown factory stage: {stage!r}")
    if from_state not in STAGE_STATES:
        raise IllegalTransitionError(f"Unknown from_state: {from_state!r}")
    if to_state not in STAGE_STATES:
        raise IllegalTransitionError(f"Unknown to_state: {to_state!r}")
    if from_state == to_state:
        return  # idempotent heartbeat, always legal
    if to_state not in _ALLOWED[from_state]:
        raise IllegalTransitionError(
            f"Illegal transition for stage {stage!r}: {from_state} -> {to_state}. "
            f"Allowed: {sorted(_ALLOWED[from_state])}"
        )


def allowed_targets(from_state: str) -> list[str]:
    """Legal next states for display / tests. Pure function."""
    return sorted(_ALLOWED[from_state]) if from_state in _ALLOWED else []
