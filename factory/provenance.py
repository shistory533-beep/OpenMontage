"""Provenance / telemetry — provider/model, artifacts, timings, fallbacks, free/paid."""
from __future__ import annotations
import time, json
from typing import Any, Dict, Optional, List

class ProvenanceLog:
    def __init__(self):
        self.entries: List[Dict[str, Any]] = []
    def log_step(self, stage: str, provider: str, model: Optional[str] = None,
                 artifact: Optional[str] = None, duration_s: float = 0.0,
                 fallback: bool = False, free: bool = True, error: Optional[str] = None):
        self.entries.append({
            "stage": stage,
            "provider": provider,
            "model": model,
            "artifact": artifact,
            "duration_s": duration_s,
            "fallback": fallback,
            "free": free,
            "error": error,
            "timestamp": time.time(),
        })
    def to_json(self, path: str):
        with open(path, "w") as f:
            json.dump({"entries": self.entries}, f, indent=2)
    def summary(self) -> Dict[str, Any]:
        total_time = sum(e.get("duration_s",0) for e in self.entries)
        fallbacks = sum(1 for e in self.entries if e.get("fallback"))
        free_count = sum(1 for e in self.entries if e.get("free"))
        errors = [e for e in self.entries if e.get("error")]
        return {"total_steps": len(self.entries), "total_time_s": total_time,
                "fallbacks": fallbacks, "free_steps": free_count,
                "paid_steps": len(self.entries) - free_count,
                "errors": len(errors)}
