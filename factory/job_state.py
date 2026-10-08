"""Persistent job state, checkpoints, resume, idempotency, failure handling.
Uses lib/checkpoint.py conventions (atomic tmp + history); never mutates frozen core."""
from __future__ import annotations
import os, json, time
from typing import Any, Dict, Optional, List

class JobState:
    TRANSIENT_ERRORS = ("timeout","rate_limit","connection_refused","502","503")
    PERMANENT_ERRORS = ("invalid_schema","missing_prerequisite","approval_gate_failed","quarantine","bad_key")

    def __init__(self, job_id: str, checkpoint_dir: str = "projects/factory_state"):
        self.job_id = job_id
        self.dir = os.path.join(checkpoint_dir, job_id)
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "state.json")
        self.prov_path = os.path.join(self.dir, "provenance.json")
        self.load()

    def load(self):
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                self.data = json.load(f)
        else:
            self.data = {"job_id": self.job_id, "created": time.time(),
                         "stages_done": [], "current_stage": "topic",
                         "status": "running", "failures": [],
                         "idempotency_key": self.job_id}
        # Idempotency: if completed and same key, skip mutation on replay
        self.idempotency_key = self.data.get("idempotency_key", self.job_id)

    def save(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.rename(tmp, self.state_path)

    def set_stage(self, stage: str, status: str = "done", artifact: Optional[str] = None,
                  error: Optional[str] = None):
        if self.data.get("status") == "completed" and self.idempotency_key == self.job_id:
            return  # idempotent replay
        self.data["current_stage"] = stage
        if status == "done" and stage not in self.data["stages_done"]:
            self.data["stages_done"].append(stage)
        self.data["status"] = status
        if error:
            kind = "transient" if any(t in error.lower() for t in self.TRANSIENT_ERRORS) else "permanent"
            self.data["failures"].append({"stage": stage, "error": error, "kind": kind, "ts": time.time()})
            if kind == "permanent":
                self.data["status"] = "failed_permanent"
            else:
                self.data["status"] = "failed_transient"
        if artifact:
            self.data.setdefault("artifacts", {})[stage] = artifact
        self.save()

    def can_resume(self) -> bool:
        # Resume allowed if transient failure only, prerequisites met
        if self.data["status"] == "failed_transient":
            return True
        if self.data["status"] == "running" and self.data["current_stage"]:
            return True
        return False

    def resume(self, stage: Optional[str] = None):
        if not self.can_resume():
            raise RuntimeError("Cannot resume: permanent failure or completed")
        self.data["status"] = "running"
        if stage:
            self.data["current_stage"] = stage
        self.save()
