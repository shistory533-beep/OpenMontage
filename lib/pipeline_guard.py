"""Pipeline guard for youtube-documentary (and any manifest-driven pipeline).

Additive validation layer — not a state machine. Stage order, gates, and
resumption live in pipeline_defs/*.yaml + lib/checkpoint.py; this module
only answers three questions agents and tests ask before running a stage:

  - assert_stage_ready: are all predecessors completed+approved and all
    required_artifacts_in present? (fail closed)
  - validate_sequence: does a run history respect manifest order?
  - next_pending: which stage should run next? (resume helper)

Publish rule: the publish stage additionally requires the human_review
checkpoint completed with human_approved=True. Without it, publish is
disabled — the guard raises PublishBlockedError before any tool runs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional


class PipelineGuardError(ValueError):
    """Base class: stage must not run."""


class PrerequisiteError(PipelineGuardError):
    """A predecessor stage or required artifact is missing/unapproved."""


class PublishBlockedError(PipelineGuardError):
    """Publish attempted before human_review APPROVED."""


def _stages(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(manifest.get("stages", []))


def stage_names(manifest: Mapping[str, Any]) -> list[str]:
    return [s["name"] for s in _stages(manifest)]


def predecessors(manifest: Mapping[str, Any], stage: str) -> list[str]:
    names = stage_names(manifest)
    if stage not in names:
        raise PrerequisiteError(f"Unknown stage {stage!r} for pipeline "
                                f"{manifest.get('name', '?')!r}")
    return names[:names.index(stage)]


def _gate_required(manifest: Mapping[str, Any], stage: str) -> bool:
    for s in _stages(manifest):
        if s["name"] == stage:
            return bool(s.get("human_approval_default", False))
    return False


def assert_stage_ready(
    manifest: Mapping[str, Any],
    stage: str,
    checkpoints: Mapping[str, Mapping[str, Any]],
) -> None:
    """Fail closed when a stage's prerequisites are unmet.

    checkpoints maps stage name -> checkpoint dict with at least
    {status, human_approved, artifacts}. Absent entry = stage not run.
    """
    names = stage_names(manifest)
    if stage not in names:
        raise PrerequisiteError(
            f"Unknown stage {stage!r}; pipeline order is {names}")
    if stage == "topic":
        return  # entry stage: no prerequisites by definition
    missing_stages: list[str] = []
    unapproved: list[str] = []
    for pred in predecessors(manifest, stage):
        cp = checkpoints.get(pred)
        if cp is None or cp.get("status") != "completed":
            missing_stages.append(pred)
            continue
        if _gate_required(manifest, pred) and not cp.get("human_approved"):
            unapproved.append(pred)
    problems: list[str] = []
    if missing_stages:
        problems.append(f"incomplete predecessors: {missing_stages}")
    if unapproved:
        problems.append(f"completed without required approval: {unapproved}")
    # Required input artifacts must exist across completed predecessors.
    required: list[str] = next(
        (s.get("required_artifacts_in", []) for s in _stages(manifest)
         if s["name"] == stage), [])
    available: dict[str, str] = {}
    for pred in predecessors(manifest, stage):
        cp = checkpoints.get(pred) or {}
        for key in (cp.get("artifacts") or {}):
            available.setdefault(key, pred)
    absent = [a for a in required if a not in available]
    if absent:
        problems.append(f"missing required artifacts: {absent} "
                        f"(required_artifacts_in for {stage!r})")
    if stage == "publish":
        hr = checkpoints.get("human_review") or {}
        if hr.get("status") != "completed" or not hr.get("human_approved"):
            problems.append(
                "publish disabled until human_review is completed AND "
                "human_approved (APPROVED)")
    if problems:
        err = (PublishBlockedError if stage == "publish"
               and any("human_review" in p for p in problems)
               else PrerequisiteError)
        raise err(f"Stage {stage!r} is not ready: " + "; ".join(problems))


def validate_sequence(manifest: Mapping[str, Any], sequence: list[str]) -> None:
    """Reject run histories that violate manifest order or name unknown stages."""
    names = stage_names(manifest)
    seen: set[str] = set()
    for stage in sequence:
        if stage not in names:
            raise PrerequisiteError(f"Unknown stage {stage!r}; order is {names}")
        for pred in predecessors(manifest, stage):
            if pred not in seen:
                raise PrerequisiteError(
                    f"Invalid stage order: {stage!r} ran before "
                    f"predecessor {pred!r}")
        seen.add(stage)


def next_pending(manifest: Mapping[str, Any],
                 checkpoints: Mapping[str, Mapping[str, Any]]) -> Optional[str]:
    """First stage without a completed checkpoint (resume pointer)."""
    for name in stage_names(manifest):
        cp = checkpoints.get(name) or {}
        if cp.get("status") != "completed":
            return name
    return None


def read_checkpoints(pipeline_dir: Path, project_id: str,
                     manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Load all existing checkpoints for a project (resume support)."""
    from lib.checkpoint import read_checkpoint

    out: dict[str, dict[str, Any]] = {}
    for name in stage_names(manifest):
        cp = read_checkpoint(Path(pipeline_dir), project_id, name)
        if cp is not None:
            out[name] = cp
    return out
