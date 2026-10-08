"""Live availability tracking for FREE-AUTO candidates.

Per (candidate, gateway, upstream-model) records: health, last success /
failure, failure class, rate-limit state, quota/reset, cooldown, latency,
tool-call and structured-output failure rates.

State persists as JSON so cooldowns survive gateway restarts. Secrets are
never stored here: only key-environment names, never key values.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class FailureClass(str, Enum):
    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTH_FAILURE = "auth_failure"
    INVALID_REQUEST = "invalid_request"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    CAPABILITY_MISMATCH = "capability_mismatch"
    TIMEOUT = "timeout"


# Failure classes that may be retried on a *different* candidate.
RETRYABLE = {
    FailureClass.TRANSIENT,
    FailureClass.RATE_LIMIT,
    FailureClass.QUOTA_EXHAUSTED,
    FailureClass.PROVIDER_UNAVAILABLE,
    FailureClass.MODEL_UNAVAILABLE,
    FailureClass.TIMEOUT,
}

DEFAULT_COOLDOWN_S = 300.0
RATE_LIMIT_COOLDOWN_S = 60.0
QUOTA_COOLDOWN_S = 3600.0


def _default_state_path() -> Path:
    override = os.environ.get("FREE_AUTO_STATE_PATH", "").strip()
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME", "").strip() or str(Path.home() / ".cache")
    return Path(base) / "openmontage" / "free-auto-health.json"


def classify_http_failure(status: int | None, body: str = "") -> FailureClass:
    """Map an HTTP outcome to a FailureClass. Pure function."""
    text = (body or "").lower()
    if status is None:
        return FailureClass.TIMEOUT
    if status == 429:
        if any(k in text for k in ("quota", "exhausted", "insufficient", "credit", "balance")):
            return FailureClass.QUOTA_EXHAUSTED
        return FailureClass.RATE_LIMIT
    if status in (401, 403):
        return FailureClass.AUTH_FAILURE
    if status == 404:
        if "model" in text:
            return FailureClass.MODEL_UNAVAILABLE
        return FailureClass.PROVIDER_UNAVAILABLE
    if status == 400 or status == 422:
        if any(k in text for k in ("tool", "function", "schema", "response_format", "json")):
            return FailureClass.CAPABILITY_MISMATCH
        return FailureClass.INVALID_REQUEST
    if status == 408 or status == 504:
        return FailureClass.TIMEOUT
    if status >= 500:
        return FailureClass.PROVIDER_UNAVAILABLE
    return FailureClass.TRANSIENT


@dataclass
class UpstreamHealth:
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    cooldown_until: float = 0.0
    reset_at: float | None = None
    last_success: float | None = None
    last_failure: float | None = None
    last_failure_class: str | None = None
    rate_limited: bool = False
    quota_exhausted: bool = False
    latency_ms_ema: float | None = None
    ttft_ms_ema: float | None = None
    tool_call_attempts: int = 0
    tool_call_failures: int = 0
    so_attempts: int = 0
    so_failures: int = 0

    def to_dict(self) -> dict:
        return {
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "cooldown_until": self.cooldown_until,
            "reset_at": self.reset_at,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_failure_class": self.last_failure_class,
            "rate_limited": self.rate_limited,
            "quota_exhausted": self.quota_exhausted,
            "latency_ms_ema": self.latency_ms_ema,
            "ttft_ms_ema": self.ttft_ms_ema,
            "tool_call_attempts": self.tool_call_attempts,
            "tool_call_failures": self.tool_call_failures,
            "so_attempts": self.so_attempts,
            "so_failures": self.so_failures,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "UpstreamHealth":
        h = cls()
        for k, v in (raw or {}).items():
            if hasattr(h, k):
                setattr(h, k, v)
        return h


@dataclass
class HealthStore:
    path: Path | None = None
    now_fn: object = None  # injectable clock for tests
    _entries: dict[str, UpstreamHealth] = field(default_factory=dict)
    _recent_failures: list[dict] = field(default_factory=list)
    _session_pins: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path is None:
            self.path = _default_state_path()

    def _now(self) -> float:
        if self.now_fn is not None:
            return float(self.now_fn())
        return time.time()

    @staticmethod
    def key(candidate_id: str, gateway: str, model: str) -> str:
        return f"{candidate_id}::{gateway}::{model}"

    def get(self, key: str) -> UpstreamHealth:
        h = self._entries.get(key)
        if h is None:
            h = UpstreamHealth()
            self._entries[key] = h
        return h

    # -- recording ------------------------------------------------------
    def record_success(self, key: str, latency_ms: float | None = None) -> None:
        h = self.get(key)
        now = self._now()
        h.consecutive_failures = 0
        h.consecutive_successes += 1
        h.last_success = now
        h.cooldown_until = 0.0
        h.reset_at = None
        h.rate_limited = False
        h.quota_exhausted = False
        if latency_ms is not None:
            h.latency_ms_ema = (
                latency_ms if h.latency_ms_ema is None
                else 0.3 * latency_ms + 0.7 * h.latency_ms_ema
            )
        self.save()

    def record_failure(
        self,
        key: str,
        failure: FailureClass,
        *,
        reset_at: float | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        h = self.get(key)
        now = self._now()
        h.consecutive_failures += 1
        h.consecutive_successes = 0
        h.last_failure = now
        h.last_failure_class = failure.value
        if failure is FailureClass.RATE_LIMIT:
            h.rate_limited = True
            h.cooldown_until = now + (retry_after_s or RATE_LIMIT_COOLDOWN_S)
            if reset_at:
                h.reset_at = reset_at
                h.cooldown_until = max(h.cooldown_until, reset_at)
        elif failure is FailureClass.QUOTA_EXHAUSTED:
            h.quota_exhausted = True
            h.cooldown_until = now + QUOTA_COOLDOWN_S
            if reset_at:
                h.reset_at = reset_at
                h.cooldown_until = max(h.cooldown_until, reset_at)
        elif failure in (FailureClass.AUTH_FAILURE, FailureClass.INVALID_REQUEST):
            # Non-retryable on this credential/shape: long cooldown, probe to recover.
            h.cooldown_until = now + QUOTA_COOLDOWN_S
        else:
            h.cooldown_until = now + min(
                DEFAULT_COOLDOWN_S * (2 ** min(h.consecutive_failures - 1, 3)),
                1800.0,
            )
        self._recent_failures.append(
            {"key": key, "failure": failure.value, "at": now}
        )
        self._recent_failures = self._recent_failures[-50:]
        self.save()

    def record_tool_call_result(self, key: str, ok: bool) -> None:
        h = self.get(key)
        h.tool_call_attempts += 1
        if not ok:
            h.tool_call_failures += 1
        self.save()

    def record_structured_output_result(self, key: str, ok: bool) -> None:
        h = self.get(key)
        h.so_attempts += 1
        if not ok:
            h.so_failures += 1
        self.save()

    def record_ttft(self, key: str, ttft_ms: float | None) -> None:
        """Record time-to-first-token (streaming) as an EMA. Advisory only."""
        if ttft_ms is None:
            return
        h = self.get(key)
        h.ttft_ms_ema = (
            ttft_ms if h.ttft_ms_ema is None
            else 0.3 * ttft_ms + 0.7 * h.ttft_ms_ema
        )
        self.save()

    # -- session affinity -----------------------------------------------
    # A session that had a good run on a candidate sticks to it while it
    # stays eligible. Pins are advisory routing hints, never guarantees:
    # an in-cooldown or unconfigured pin is skipped silently.

    def pin_session(self, session_id: str, key: str) -> None:
        if not session_id:
            return
        self._session_pins[session_id] = key
        self.save()

    def pinned_for(self, session_id: str) -> str | None:
        if not session_id:
            return None
        return self._session_pins.get(session_id)

    def unpin_session(self, session_id: str) -> None:
        if session_id in self._session_pins:
            del self._session_pins[session_id]
            self.save()

    # -- queries ---------------------------------------------------------
    def is_eligible(self, key: str) -> tuple[bool, str]:
        """Eligible unless in cooldown. Returns (eligible, reason)."""
        h = self._entries.get(key)
        if h is None:
            return True, "no telemetry; assumed healthy"
        now = self._now()
        if h.cooldown_until and now < h.cooldown_until:
            if h.reset_at and now >= h.reset_at:
                return True, "reset reached; needs probe"
            return False, f"cooldown until {h.cooldown_until:.0f} after {h.last_failure_class}"
        return True, "healthy"

    def needs_probe(self, key: str) -> bool:
        h = self._entries.get(key)
        if h is None or h.consecutive_failures == 0:
            return False
        now = self._now()
        return not h.cooldown_until or now >= h.cooldown_until

    def quota_health(self, key: str) -> float:
        h = self._entries.get(key)
        if h is None:
            return 1.0
        eligible, _ = self.is_eligible(key)
        if not eligible:
            return 0.0
        if h.quota_exhausted or h.rate_limited:
            return 0.3
        if h.consecutive_failures:
            return max(0.2, 1.0 - 0.2 * h.consecutive_failures)
        return 1.0

    def historical_success(self, key: str) -> float | None:
        h = self._entries.get(key)
        if h is None:
            return None
        total = h.consecutive_successes + h.consecutive_failures
        if total == 0 and h.last_success is None and h.last_failure is None:
            return None
        if h.last_success is None:
            return 0.0
        if h.last_failure is None:
            return 1.0
        # Recency-weighted: successes after last failure dominate.
        return min(1.0, h.consecutive_successes / max(1, total))

    def recent_failures(self, limit: int = 10) -> list[dict]:
        return list(self._recent_failures[-limit:])

    # -- persistence -----------------------------------------------------
    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "entries": {k: v.to_dict() for k, v in self._entries.items()},
                "recent_failures": self._recent_failures[-50:],
                "session_pins": dict(list(self._session_pins.items())[-200:]),
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass  # health tracking is advisory; never break routing on I/O

    def load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._entries = {
                k: UpstreamHealth.from_dict(v)
                for k, v in (raw.get("entries") or {}).items()
            }
            self._recent_failures = raw.get("recent_failures", [])[-50:]
            pins = raw.get("session_pins", {}) or {}
            self._session_pins = {k: v for k, v in pins.items()
                                  if isinstance(v, str)} if isinstance(pins, dict) else {}
        except (OSError, ValueError):
            pass
