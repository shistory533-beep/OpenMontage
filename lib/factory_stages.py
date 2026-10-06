"""Factory episode stage machine — pure deterministic FSM, no I/O.

Additive layer for the YouTube Factory. This module is the ONE source of
truth for factory stage IDs and owns:

  - the canonical ordered stage list (19 stages, one per Episode Package
    domain, in factory order),
  - the explicit prerequisite chain (direct predecessor per stage),
  - the approval gates (stages that must pass through APPROVED),
  - the allowed state transitions per stage,
  - pure validators (transition, prerequisites, manifest alignment),
  - the legacy stage-ID map for pre-canonical episode documents.

It does not touch the render pipeline, Timeline IR, footage intelligence,
narration implementation, or QA architecture. Persistence lives in
``lib/episode_store.py``; artifact schemas live in
``schemas/factory/episode_package.schema.json`` (envelope) plus the existing
``schemas/artifacts/*`` (payloads, when applicable).
"""

from __future__ import annotations

from typing import Any, Mapping


class StageModelError(ValueError):
    """Base class for canonical stage-model violations."""


class IllegalTransitionError(StageModelError):
    """Raised when a stage transition is not in the deterministic table."""


class PrerequisiteViolationError(StageModelError):
    """Raised when a stage starts before its prerequisites are satisfied."""


class ApprovalGateError(StageModelError):
    """Raised when a gated stage completes without human approval."""


class ManifestStageError(StageModelError):
    """Raised when a pipeline manifest diverges from the canonical model."""


# Canonical factory stages, in factory order. One stage per Episode Package
# domain. This tuple is the single source of truth for stage IDs: the episode
# envelope schema, the EpisodeStore, and the youtube-documentary manifest must
# all agree with it (see validate_manifest_against_canonical).
FACTORY_STAGES: tuple[str, ...] = (
    "topic",
    "research",
    "evidence",
    "script",
    "fact_check",
    "storyboard",
    "narration",
    "footage",
    "footage_intelligence",
    "editorial",
    "timeline",
    "audio",
    "render",
    "qa",
    "packaging",
    "thumbnail",
    "human_review",
    "publish",
    "analytics",
)

STAGE_INDEX: dict[str, int] = {name: i for i, name in enumerate(FACTORY_STAGES)}

# Explicit prerequisites: each stage's direct predecessor in factory order.
# Transitive closure = every earlier stage. The chain is linear by design, so
# "prerequisites met" == "all earlier stages DONE". Render additionally
# consumes the audio mix (audio precedes render); analytics runs only after
# publish/export. Linear order encodes all of this — no side channels.
STAGE_PREREQUISITES: dict[str, tuple[str, ...]] = {
    stage: (FACTORY_STAGES[i - 1],) if i else ()
    for i, stage in enumerate(FACTORY_STAGES)
}

# Stages whose DONE requires a prior APPROVED (human sign-off). Mirrors the
# manifest's human_approval_default=true set for youtube-documentary; the
# alignment test fails if the two drift apart. In particular: publish is
# blocked before human_review approval, and analytics is blocked before
# publish (prerequisite chain).
APPROVAL_GATES: frozenset[str] = frozenset({
    "topic",
    "script",
    "storyboard",
    "footage",
    "human_review",
    "publish",
})

# Pre-canonical Episode Store IDs -> canonical IDs. The old store split
# research output across three stages (sources/facts/claims); the canonical
# model consolidates them into one evidence bundle. The old store's metadata
# stage (upload metadata) is the packaging stage's metadata duty. All other
# legacy IDs survived unchanged; stages with no legacy equivalent
# (footage_intelligence, packaging, human_review) start empty on migration.
LEGACY_STAGE_MAP: dict[str, str] = {
    "topic": "topic",
    "research": "research",
    "sources": "evidence",
    "facts": "evidence",
    "claims": "evidence",
    "script": "script",
    "fact_check": "fact_check",
    "storyboard": "storyboard",
    "narration": "narration",
    "footage": "footage",
    "editorial": "editorial",
    "timeline": "timeline",
    "audio": "audio",
    "render": "render",
    "qa": "qa",
    "thumbnail": "thumbnail",
    "metadata": "packaging",
    "publish": "publish",
    "analytics": "analytics",
}

# Legacy stages merged into one canonical stage (many-to-one).
LEGACY_MERGE_GROUPS: dict[str, tuple[str, ...]] = {
    "evidence": ("sources", "facts", "claims"),
}

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


def prerequisites(stage: str) -> tuple[str, ...]:
    """Direct prerequisites of a canonical stage. Pure function."""
    if stage not in FACTORY_STAGES:
        raise PrerequisiteViolationError(f"Unknown factory stage: {stage!r}")
    return STAGE_PREREQUISITES[stage]


def all_prerequisites(stage: str) -> tuple[str, ...]:
    """Transitive prerequisite chain (every earlier stage, in order)."""
    if stage not in FACTORY_STAGES:
        raise PrerequisiteViolationError(f"Unknown factory stage: {stage!r}")
    return FACTORY_STAGES[:STAGE_INDEX[stage]]


def requires_approval(stage: str) -> bool:
    """Whether DONE on this stage requires a prior APPROVED."""
    if stage not in FACTORY_STAGES:
        raise StageModelError(f"Unknown factory stage: {stage!r}")
    return stage in APPROVAL_GATES


def assert_prerequisites_met(
    status: Mapping[str, str], stage: str
) -> None:
    """Fail closed when a stage's prerequisites are not DONE.

    status maps stage ID -> lifecycle state. Unknown stage IDs in status
    are ignored; missing predecessors count as unmet. The entry stage
    (topic) has no prerequisites by definition.
    """
    if stage not in FACTORY_STAGES:
        raise PrerequisiteViolationError(f"Unknown factory stage: {stage!r}")
    unmet = [p for p in all_prerequisites(stage) if status.get(p) != "DONE"]
    if unmet:
        raise PrerequisiteViolationError(
            f"Stage {stage!r} is not ready: prerequisites not DONE: {unmet}"
        )


def validate_manifest_against_canonical(manifest: Mapping[str, Any]) -> None:
    """Check a factory pipeline manifest against the canonical stage model.

    Every manifest stage must be a canonical ID, appear at most once, and
    follow canonical relative order. Generic (non-factory) pipelines are
    out of scope — only call this for factory manifests. Raises
    ManifestStageError on any divergence.
    """
    raw = manifest.get("stages", [])
    names = [s.get("name") for s in raw]
    unknown = [n for n in names if n not in FACTORY_STAGES]
    if unknown:
        raise ManifestStageError(
            f"Manifest {manifest.get('name', '?')!r} has non-canonical "
            f"stages: {unknown}. Canonical IDs: {list(FACTORY_STAGES)}"
        )
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ManifestStageError(f"Duplicate stages in manifest: {dupes}")
    order = [STAGE_INDEX[n] for n in names]
    if order != sorted(order):
        raise ManifestStageError(
            f"Manifest stages violate canonical order: {names}"
        )
