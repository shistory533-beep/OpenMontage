"""Producer Agent: deterministic orchestration over existing services.

The Producer coordinates; it does not author content and duplicates no
domain logic:

- state            -> EpisodeStore (transitions, versioned artifacts)
- order + gates    -> pipeline manifest + pipeline_guard + lib.checkpoint
- research/script  -> lib.editorial agents (driven by the directing agent;
                      the Producer only records supplied payloads)
- narration        -> TTS Hub (synthesize per script section)
- footage          -> FootageHub search + VisualScorer picks + download
- edit             -> lib.producer.assembly (Timeline IR, existing schema)
- audio            -> audio_mixer via lib.producer.audio_build plans
- render           -> video_compose
- qa/review/pack   -> lib.producer.qa / .review / .packaging

Stage execution is delegated to injected handlers
(``StageHandler`` protocol). Content stages default to recording
pre-supplied payloads from ``stage_inputs``; mechanical stages default
to running the real service named above. Tests inject fakes.

Failure semantics: any stage failure (handler exception, gate/prereq
violation, schema rejection) marks the stage FAILED with a reason,
writes a failed checkpoint, emits an event, and halts the run by
raising ProducerHalted. The run never continues past a failure.
Resume skips DONE stages; retry_failed re-runs FAILED ones.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from lib.episode_store import EpisodeStore
from lib.pipeline_guard import assert_stage_ready, read_checkpoints
from lib.pipeline_loader import get_stage_order, load_pipeline
from lib.producer.contracts import PRODUCER_STAGES, ProducerEvent

PIPELINE_TYPE = "youtube-documentary"


class ProducerError(ValueError):
    """Base class for producer failures."""


class ProducerHalted(ProducerError):
    """A stage failed; the run stopped instead of continuing."""


class MissingStageInput(ProducerError):
    """A content stage had no supplied payload to record."""


class CriticalStageError(ProducerError):
    """A handler-reported critical failure. Never continued past."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StageContext:
    """Everything a stage handler may read. Handlers return artifacts."""

    episode_id: str
    stage: str
    inputs: dict[str, Any]       # prior stages' artifacts, keyed by name
    workdir: Path               # episode directory (all outputs land here)
    attempt: int = 1
    config: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = {}


StageHandler = Callable[[StageContext], dict[str, Any]]


def _manifest() -> dict[str, Any]:
    return load_pipeline(PIPELINE_TYPE)


def _manifest_stage(name: str) -> dict[str, Any]:
    for stage in _manifest().get("stages", []):
        if stage.get("name") == name:
            return stage
    raise ProducerError(f"Stage {name!r} not in {PIPELINE_TYPE} manifest.")


def _produces(name: str) -> list[str]:
    return list(_manifest_stage(name).get("produces", []))


def _requires_in(name: str) -> list[str]:
    return list(_manifest_stage(name).get("required_artifacts_in", []))


class ProducerAgent:
    """Episode-Store-backed orchestrator for topic -> human_review."""

    def __init__(
        self,
        episode_id: str,
        *,
        projects_dir: Optional[Path] = None,
        handlers: Optional[Mapping[str, StageHandler]] = None,
        stage_inputs: Optional[Mapping[str, Any]] = None,
        approvals: Optional[Mapping[str, bool]] = None,
        start_from: Optional[str] = None,
        stop_after: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> None:
        if start_from is not None and start_from not in PRODUCER_STAGES:
            raise ProducerError(f"Unknown start stage: {start_from!r}")
        if stop_after is not None and stop_after not in PRODUCER_STAGES:
            raise ProducerError(f"Unknown stop stage: {stop_after!r}")
        self.episode_id = episode_id
        self.projects_dir = Path(projects_dir) if projects_dir else None
        self.store = (EpisodeStore(episode_id, projects_dir=projects_dir)
                      if projects_dir else EpisodeStore(episode_id))
        # Checkpoints live beside episode.json so pipeline_guard reads the
        # same directory the store persists in.
        self.checkpoint_dir = self.store.episode_dir
        self.stage_inputs: dict[str, Any] = dict(stage_inputs or {})
        self.approvals: dict[str, bool] = dict(approvals or {})
        self.config: dict[str, Any] = dict(config or {})
        self.handlers: dict[str, StageHandler] = dict(
            default_handlers(self))
        if handlers:
            self.handlers.update(handlers)
        self.stages = list(PRODUCER_STAGES)
        if start_from:
            self.stages = self.stages[self.stages.index(start_from):]
        if stop_after:
            self.stages = self.stages[:self.stages.index(stop_after) + 1]
        self.events_path = self.store.episode_dir / "producer_events.jsonl"

    # -- events --------------------------------------------------------

    def emit(self, stage: str, kind: str, detail: str = "") -> None:
        event = ProducerEvent(timestamp=_utcnow(), episode_id=self.episode_id,
                              stage=stage, kind=kind, detail=detail)
        try:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except OSError:
            pass  # observability never breaks production

    def events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        out = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    # -- planning --------------------------------------------------------

    def plan(self) -> list[dict[str, Any]]:
        """Dry run: ordered stage plan with inputs/outputs. Writes nothing."""
        from lib.producer.contracts import StagePlan

        try:
            states = self.store.status()
        except (OSError, ValueError):
            states = {}
        plans = []
        for stage in self.stages:
            state = states.get(stage, "PENDING")
            will_skip = state == "DONE"
            plans.append(StagePlan(
                stage=stage,
                inputs=_requires_in(stage),
                produces=_produces(stage),
                will_skip=will_skip,
                skip_reason=("already DONE" if will_skip else ""),
            ).to_dict())
        return plans

    def inspect(self) -> dict[str, Any]:
        """Full status dump: store states, checkpoints, versions, events."""
        states: dict[str, Any]
        try:
            doc = self.store.load()
            states = {k: {"state": v["state"],
                          "artifact_version": v.get("artifact_version", 0),
                          "failure_reason": v.get("failure_reason")}
                      for k, v in doc["stages"].items()
                      if k in PRODUCER_STAGES}
        except (OSError, ValueError) as exc:
            states = {"_error": str(exc)}  # type: ignore[assignment]
        checkpoints: dict[str, Any] = {}
        manifest = _manifest()
        try:
            cps = read_checkpoints(self.checkpoint_dir, self.episode_id,
                                   manifest)
            for name, cp in cps.items():
                checkpoints[name] = {"status": cp.get("status"),
                                     "human_approved": cp.get(
                                         "human_approved", False),
                                     "artifacts": sorted(
                                         (cp.get("artifacts") or {}).keys())}
        except (OSError, ValueError) as exc:
            checkpoints = {"_error": str(exc)}
        events = self.events()
        return {"episode_id": self.episode_id,
                "pipeline_type": PIPELINE_TYPE,
                "stages": states,
                "checkpoints": checkpoints,
                "next_stage": self._next_pending(states),
                "event_count": len(events),
                "recent_events": events[-10:]}

    def _next_pending(self, states: Mapping[str, Any]) -> Optional[str]:
        for stage in self.stages:
            entry = states.get(stage)
            state = entry.get("state") if isinstance(entry, dict) else entry
            if state != "DONE":
                return stage
        return None

    # -- execution -------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run all pending stages in order. Halts (raising) on failure."""
        from lib.checkpoint import (  # local import: heavy module, rarely needed twice
            init_project,
            write_checkpoint,
        )

        self.store.init(self.config.get("title", self.episode_id))
        init_project(self.episode_id, title=self.config.get(
            "title", self.episode_id), pipeline_type=PIPELINE_TYPE,
            pipeline_dir=self.store.projects_dir)
        self.emit("", "run_started",
                  f"stages={self.stages}")
        completed: list[str] = []
        manifest = _manifest()
        for stage in self.stages:
            state = self.store.status().get(stage, "PENDING")
            if state == "DONE":
                self.emit(stage, "stage_skipped", "already DONE")
                completed.append(stage)
                continue
            try:
                self._run_stage(stage, manifest, write_checkpoint)
            except ProducerHalted:
                raise
            except Exception as exc:
                # Defensive: _run_stage always converts to ProducerHalted,
                # but a bug must still halt loudly, never slip through.
                raise ProducerHalted(
                    f"Stage {stage!r} halted run: {exc}") from exc
            state_after = self.store.status().get(stage)
            if state_after == "DONE":
                completed.append(stage)
            else:
                # Awaiting-human gate: orderly halt, resumable, not a failure.
                self.emit("", "run_finished",
                          f"completed={completed} awaiting_human={stage}")
                return {"completed": completed,
                        "awaiting_human": stage,
                        "failed": None}
        self.emit("", "run_finished", f"completed={completed}")
        return {"completed": completed, "awaiting_human": None,
                "failed": None}

    def _run_stage(self, stage: str, manifest: dict[str, Any],
                   write_checkpoint: Any) -> None:
        from lib.checkpoint import CheckpointValidationError

        self.emit(stage, "stage_started", "")
        checkpoints = read_checkpoints(self.checkpoint_dir, self.episode_id,
                                       manifest)
        try:
            assert_stage_ready(manifest, stage, checkpoints)
        except Exception as exc:
            return self._fail(stage, write_checkpoint,
                              f"prerequisites unmet: {exc}")
        cur = self.store.status().get(stage, "PENDING")
        if cur == "FAILED":
            self.emit(stage, "retry_started", "FAILED -> RUNNING")
        try:
            self.store.transition(stage, "RUNNING")
        except Exception as exc:
            return self._fail(stage, write_checkpoint,
                              f"cannot start stage: {exc}")
        write_checkpoint(self.checkpoint_dir, self.episode_id, stage,
                         "in_progress", {},
                         pipeline_type=PIPELINE_TYPE)
        handler = self.handlers.get(stage)
        if handler is None:
            return self._fail(
                stage, write_checkpoint,
                f"no handler registered for stage {stage!r}")
        try:
            artifacts = handler(self._context(stage))
        except (ProducerError, CriticalStageError) as exc:
            return self._fail(stage, write_checkpoint, str(exc))
        except Exception as exc:
            return self._fail(
                stage, write_checkpoint,
                f"handler crashed: {type(exc).__name__}: {exc}")
        if not isinstance(artifacts, dict):
            return self._fail(
                stage, write_checkpoint,
                f"handler for {stage!r} returned non-dict artifacts")
        try:
            produced = _produces(stage)
            if produced:
                if len(produced) != 1:
                    raise ProducerError(
                        f"Stage {stage!r} produces {produced}: Producer "
                        f"records exactly one artifact payload per stage.")
                name = produced[0]
                payload = artifacts.get(name, {})
                if not isinstance(payload, dict):
                    raise ProducerError(
                        f"Stage {stage!r} artifact {name!r} must be a dict.")
                self.store.set_artifact(stage, payload)
        except Exception as exc:
            return self._fail(stage, write_checkpoint,
                              f"artifact rejected: {exc}")
        gated = any(s.get("name") == stage
                    and s.get("human_approval_default", False)
                    for s in manifest.get("stages", []))
        approved = bool(self.approvals.get(stage, False))
        try:
            if gated and not approved:
                write_checkpoint(
                    self.checkpoint_dir, self.episode_id, stage,
                    "awaiting_human", artifacts,
                    pipeline_type=PIPELINE_TYPE,
                    human_approval_required=True)
                self.store.transition(stage, "REVIEW")
                self.emit(stage, "stage_awaiting_human",
                          "gate requires explicit human approval")
                return
            write_checkpoint(self.checkpoint_dir, self.episode_id, stage,
                             "completed", artifacts,
                             pipeline_type=PIPELINE_TYPE,
                             human_approved=approved)
            if gated:
                self.store.transition(stage, "APPROVED")
            self.store.transition(stage, "DONE")
        except CheckpointValidationError as exc:
            return self._fail(stage, write_checkpoint,
                              f"checkpoint rejected: {exc}")
        except Exception as exc:
            return self._fail(stage, write_checkpoint,
                              f"completion failed: {exc}")
        self.emit(stage, "stage_completed",
                  f"artifacts={sorted(artifacts)}")

    def _fail(self, stage: str, write_checkpoint: Any,
              reason: str) -> None:
        try:
            self.store.fail(stage, reason)
        except Exception:
            pass
        try:
            write_checkpoint(self.checkpoint_dir, self.episode_id, stage,
                             "failed", {}, pipeline_type=PIPELINE_TYPE,
                             error=reason)
        except Exception:
            pass
        self.emit(stage, "stage_failed", reason)
        raise ProducerHalted(f"Stage {stage!r} FAILED: {reason} "
                             f"(run halted, nothing downstream ran)")

    def retry_failed(self) -> dict[str, Any]:
        """Re-run FAILED stages in order, then continue the run."""
        failed = [s for s, st in self.store.status().items()
                  if st == "FAILED" and s in self.stages]
        if not failed:
            return {"retried": [], "note": "no FAILED stages"}
        self.emit("", "retry_started", f"stages={failed}")
        return self.run()

    def record_approval(self, stage: str, approved: bool = True) -> None:
        """Record an explicit human approval for a gated stage."""
        self.approvals[stage] = approved
        self.emit(stage, "gate_decision",
                  f"human approval recorded: {approved}")

    def _context(self, stage: str) -> "StageContext":
        doc = self.store.load()
        inputs: dict[str, Any] = {}
        for prior in self.stages:
            if prior == stage:
                break
            art = (doc["stages"].get(prior) or {}).get("artifact") or {}
            if not isinstance(art, dict):
                continue
            # Key by stage id AND by produced artifact name so handlers
            # can read ctx.inputs["script"] / ["asset_manifest"] / ...
            # without collisions (a flat merge would let narration
            # "sections" overwrite script "sections"). Later priors win
            # under a shared name (timeline refines editorial's
            # edit_decisions), so walk forward in stage order.
            inputs[prior] = art
            try:
                for name in _produces(prior):
                    inputs[name] = art
            except ProducerError:
                pass
        return StageContext(episode_id=self.episode_id, stage=stage,
                            inputs=inputs,
                            workdir=self.store.episode_dir, attempt=1,
                            config=self.config)


def default_handlers(producer: ProducerAgent) -> dict[str, StageHandler]:
    """Real-service handlers. Content stages record supplied payloads."""
    from lib.producer import runners
    return runners.build(producer)
