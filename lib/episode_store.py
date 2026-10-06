"""Episode Package store — durable, resumable, non-destructive factory state.

Design rules (per task constraints):
  - Reuses existing infrastructure: PROJECTS_DIR root (lib/paths.py), UTC
    timestamps, atomic tmp-write + os.replace, history/ archival copies
    (same pattern as lib/checkpoint.py), jsonschema validation.
  - Does NOT rewrite: render pipeline, Timeline IR, footage intelligence,
    narration implementation, QA architecture. Stage payloads are opaque
    provider-agnostic dicts; this module never imports a provider tool.
  - No destructive rewriting: every mutation archives the pre-mutation
    episode.json into history/ and bumps artifact_version on payload change.
    History files are never deleted by this module.
  - Resumable: all state on disk (projects/<episode_id>/episode.json).
    Re-instantiating the store after a crash yields identical state.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import jsonschema

from lib.factory_stages import (
    FACTORY_STAGES,
    IllegalTransitionError,
    validate_transition,
)
from lib.paths import PROJECTS_DIR

EPISODE_FILENAME = "episode.json"
HISTORY_DIRNAME = "history"
EPISODE_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "factory"
    / "episode_package.schema.json"
)

# Map factory stages to canonical OpenMontage artifact names where one exists.
# Payloads for these stages are additionally validated with
# schemas/artifacts/<name>. Validation is best-effort by design: unknown
# names are skipped (provider-agnostic custom payloads stay legal).
ARTIFACT_SCHEMA_MAP: dict[str, str] = {
    "research": "research_brief",
    "script": "script",
    "storyboard": "scene_plan",  # storyboard is a visual approval view over slots; scene_plan is the closest canonical contract
    "footage": "asset_manifest",
    "editorial": "edit_decisions",
    "timeline": "edit_decisions",
    "render": "render_report",
    "qa": "final_review",
    "publish": "publish_log",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_episode_schema() -> dict[str, Any]:
    with open(EPISODE_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _blank_stage(now: str) -> dict[str, Any]:
    return {
        "state": "PENDING",
        "artifact_version": 0,
        "artifact": {},
        "failure_reason": None,
        "provider": None,
        "started_at": None,
        "updated_at": now,
        "reviewed_at": None,
        "approved_at": None,
        "done_at": None,
    }


class EpisodeStore:
    """Durable per-episode state. One instance per episode directory."""

    def __init__(self, episode_id: str, projects_dir: Optional[Path] = None) -> None:
        self.episode_id = episode_id
        self.projects_dir = Path(projects_dir) if projects_dir else PROJECTS_DIR
        self.episode_dir = self.projects_dir / episode_id
        self.episode_path = self.episode_dir / EPISODE_FILENAME
        self.history_dir = self.episode_dir / HISTORY_DIRNAME

    # -- lifecycle ----------------------------------------------------

    def init(self, title: str) -> dict[str, Any]:
        """Create a new episode package. Idempotent: re-init returns existing."""
        if self.episode_path.exists():
            return self.load()
        now = _utcnow()
        doc = {
            "version": "1.0",
            "episode_id": self.episode_id,
            "title": title,
            "pipeline_type": "youtube-documentary",
            "created_at": now,
            "updated_at": now,
            "stages": {name: _blank_stage(now) for name in FACTORY_STAGES},
        }
        self._write_validated(doc)
        return doc

    def load(self) -> dict[str, Any]:
        with open(self.episode_path, encoding="utf-8") as f:
            doc = json.load(f)
        self.validate(doc)
        return doc

    def validate(self, doc: dict[str, Any]) -> None:
        jsonschema.validate(instance=doc, schema=_load_episode_schema())

    # -- transitions --------------------------------------------------

    def transition(
        self,
        stage: str,
        to_state: str,
        *,
        failure_reason: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> dict[str, Any]:
        """Move one stage to to_state with deterministic checks + timestamps."""
        doc = self.load()
        if stage not in doc["stages"]:
            raise IllegalTransitionError(f"Unknown factory stage: {stage!r}")
        cur = doc["stages"][stage]
        validate_transition(stage, cur["state"], to_state)
        if to_state == "FAILED" and not (failure_reason or cur.get("failure_reason")):
            raise ValueError(
                f"Stage {stage!r} -> FAILED requires a failure_reason "
                "(clear failure reason is mandatory)."
            )
        now = _utcnow()
        cur["state"] = to_state
        cur["updated_at"] = now
        if to_state == "RUNNING" and cur.get("started_at") is None:
            cur["started_at"] = now
        if to_state == "REVIEW":
            cur["reviewed_at"] = now
        if to_state == "APPROVED":
            cur["approved_at"] = now
        if to_state == "DONE":
            cur["done_at"] = now
        if to_state == "FAILED":
            cur["failure_reason"] = failure_reason or cur.get("failure_reason")
        else:
            # A successful move clears a prior failure reason; retry starts clean.
            if to_state == "RUNNING":
                cur["failure_reason"] = None
        if provider is not None:
            cur["provider"] = provider  # label only, never imported
        doc["updated_at"] = now
        self._write_validated(doc)
        return doc

    def set_artifact(
        self,
        stage: str,
        artifact: dict[str, Any],
        *,
        provider: Optional[str] = None,
    ) -> dict[str, Any]:
        """Versioned artifact write. Bumps artifact_version, archives history."""
        if not isinstance(artifact, dict):
            raise ValueError("Artifact payload must be a JSON object (dict).")
        doc = self.load()
        if stage not in doc["stages"]:
            raise IllegalTransitionError(f"Unknown factory stage: {stage!r}")
        schema_name = ARTIFACT_SCHEMA_MAP.get(stage)
        if schema_name is not None:
            try:
                from schemas.artifacts import validate_artifact
            except Exception:
                validate_artifact = None  # type: ignore[assignment]
            if validate_artifact is not None:
                validate_artifact(schema_name, artifact)
        cur = doc["stages"][stage]
        cur["artifact"] = artifact
        cur["artifact_version"] = int(cur.get("artifact_version", 0)) + 1
        cur["updated_at"] = _utcnow()
        if provider is not None:
            cur["provider"] = provider
        doc["updated_at"] = cur["updated_at"]
        self._write_validated(doc)
        return doc

    def fail(self, stage: str, reason: str) -> dict[str, Any]:
        """Shorthand: RUNNING/REVIEW -> FAILED with mandatory reason."""
        if not reason or not reason.strip():
            raise ValueError("fail() requires a non-empty reason.")
        return self.transition(stage, "FAILED", failure_reason=reason.strip())

    def status(self) -> dict[str, str]:
        """Lightweight resumability probe: stage -> state."""
        return {k: v["state"] for k, v in self.load()["stages"].items()}

    # -- persistence --------------------------------------------------

    def _write_validated(self, doc: dict[str, Any]) -> None:
        self.validate(doc)
        self.episode_dir.mkdir(parents=True, exist_ok=True)
        self._archive_current()
        tmp = self.episode_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
        os.replace(tmp, self.episode_path)

    def _archive_current(self) -> None:
        """Copy pre-mutation episode.json into history/. Never deletes."""
        if not self.episode_path.exists():
            return
        try:
            with open(self.episode_path, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}
        stamp = str(existing.get("updated_at", "")) or _utcnow()
        safe = "".join(c for c in stamp if c.isalnum()) or "unknown"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        target = self.history_dir / f"episode_{safe}.json"
        if target.exists():
            target = self.history_dir / f"episode_{safe}_{os.getpid()}.json"
        try:
            shutil.copyfile(self.episode_path, target)
        except OSError:
            pass  # archival is best-effort; the atomic replace below still runs
