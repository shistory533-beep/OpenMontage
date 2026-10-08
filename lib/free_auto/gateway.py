"""FREE-AUTO local gateway: one virtual model over many free upstreams.

Exposes an OpenAI-compatible HTTP API on 127.0.0.1:<port>/v1:

- GET  /v1/models            -> lists the virtual ``free-auto`` model
- POST /v1/chat/completions  -> classify, rank, try candidates in order,
                                fail over on retryable failures
- GET  /health, /status      -> lightweight status / health snapshot

Secrets are never logged: Authorization headers are redacted and API keys
are read from the environment at call time, never persisted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from lib.free_auto.health import (
    RETRYABLE,
    FailureClass,
    HealthStore,
    classify_http_failure,
)
from lib.free_auto.registry import Registry, load_registry
from lib.free_auto.scoring import (
    RankedCandidate,
    format_ranking,
    rank_candidates,
    snapshot_for_status,
)
from lib.free_auto.task_classify import (
    Complexity,
    TaskClass,
    classify_task,
    parse_complexity,
)

VIRTUAL_MODEL = "free-auto"
DEFAULT_PORT = 4100
DEFAULT_TIMEOUT_S = 90.0

# Transport: (base_url, api_key, payload, timeout_s) ->
#   (http_status | None, body_json_or_text, latency_ms, headers dict)
Transport = Callable[[str, str, dict, float], tuple]


def urllib_transport(
    base_url: str, api_key: str, payload: dict, timeout_s: float
) -> tuple:
    started = time.time()
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", "replace")
            latency_ms = (time.time() - started) * 1000.0
            headers = {k.lower(): v for k, v in resp.headers.items()}
            try:
                return resp.status, json.loads(raw), latency_ms, headers
            except ValueError:
                return resp.status, raw, latency_ms, headers
    except urllib.error.HTTPError as e:
        latency_ms = (time.time() - started) * 1000.0
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        headers = {k.lower(): v for k, v in (e.headers or {}).items()}
        try:
            return e.code, json.loads(raw) if raw else {}, latency_ms, headers
        except ValueError:
            return e.code, raw, latency_ms, headers
    except Exception as e:  # timeout, DNS, connection refused
        latency_ms = (time.time() - started) * 1000.0
        return None, str(e), latency_ms, {}
    return None, "empty response", (time.time() - started) * 1000.0, {}


def _parse_reset(headers: dict, now: float) -> tuple[float | None, float | None]:
    """Best-effort (reset_at, retry_after_s) from rate-limit headers."""
    retry_after: float | None = None
    for k in ("retry-after", "x-retry-after"):
        if k in headers:
            try:
                retry_after = float(headers[k])
                break
            except ValueError:
                pass
    reset_at: float | None = None
    for k in ("x-ratelimit-reset", "x-rate-limit-reset", "ratelimit-reset"):
        if k in headers:
            try:
                v = float(headers[k])
                reset_at = v if v > 1e12 / 1000 else (v if v > now else now + v)
                if reset_at < now:  # relative seconds form
                    reset_at = now + v
                break
            except ValueError:
                pass
    return reset_at, retry_after


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: ("<redacted>" if k.lower() in ("authorization", "api_key", "apikey", "key") else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("Bearer "):
        return "Bearer <redacted>"
    return obj


def _log(msg: str) -> None:
    print(f"[free-auto] {msg}", file=sys.stderr, flush=True)


@dataclass
class AttemptRecord:
    candidate: str
    gateway: str
    upstream_model: str
    outcome: str
    failure: str | None = None


@dataclass
class FreeAutoRouter:
    registry: Registry
    health: HealthStore
    transport: Transport | None = None
    env: dict[str, str] | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S
    _history: list[dict] = field(default_factory=list)

    def _transport(self) -> Transport:
        return self.transport or urllib_transport

    def _env(self) -> dict[str, str]:
        return self.env if self.env is not None else os.environ

    def rank_for(
        self, messages, *, needs_tool_use: bool = False,
        needs_structured_output: bool = False,
        complexity: Complexity | None = None,
        session_id: str | None = None,
    ):
        classification = classify_task(messages)
        if complexity is None:
            complexity = classification.complexity
        needs_mm = classification.task_class is TaskClass.MULTIMODAL
        candidates = self.registry.filter_for_task(
            needs_multimodal=needs_mm,
            needs_tool_use=needs_tool_use,
            needs_structured_output=needs_structured_output,
        )
        relaxed = False
        if not candidates:
            # Never strand a request on an over-strict filter: fall back to
            # all eligible candidates and let scoring sort it out.
            candidates = self.registry.eligible()
            relaxed = True
        ranked = rank_candidates(
            candidates, task_class=classification.task_class,
            health=self.health, env=self._env(),
            complexity=complexity,
            free_tier_for=self.registry.free_tier_for,
        )
        pinned_key = self.health.pinned_for(session_id or "") if session_id else None
        if pinned_key:
            for i, cand in enumerate(ranked):
                if cand.health_key() == pinned_key:
                    pinned = ranked.pop(i)
                    pinned.score = replace(
                        pinned.score,
                        explanation=pinned.score.explanation + " (session-affine)")
                    ranked.insert(0, pinned)
                    break
        return classification, ranked, relaxed

    def complete(
        self,
        messages,
        *,
        extra: dict[str, Any] | None = None,
        needs_tool_use: bool = False,
        needs_structured_output: bool = False,
    ) -> tuple[int, dict]:
        """Run the cascade. Returns (http_status, response_json)."""
        payload_extra = dict(extra or {})
        payload_extra.pop("model", None)
        stream = bool(payload_extra.pop("stream", False))
        session_id = payload_extra.pop("session_id", None)
        complexity = parse_complexity(payload_extra.pop("complexity", None))
        classification, ranked, relaxed = self.rank_for(
            messages,
            needs_tool_use=needs_tool_use,
            needs_structured_output=needs_structured_output,
            complexity=complexity,
            session_id=session_id if isinstance(session_id, str) else None,
        )
        if complexity is not None:
            # Surface the effective depth tier (override wins) in the envelope.
            classification = replace(classification, complexity=complexity)
        if relaxed:
            _log(
                f"capability filter relaxed to all-eligible for "
                f"task={classification.task_class.value}"
            )
        if not ranked:
            return 503, self._exhausted(
                [], classification, "no eligible candidates", relaxed=relaxed
            )

        attempts: list[AttemptRecord] = []
        tried_keys: set[str] = set()

        for cand in ranked:
            key = cand.health_key()
            if key in tried_keys:
                continue  # never retry the same upstream twice per request
            tried_keys.add(key)
            payload = dict(payload_extra)
            payload["messages"] = messages
            payload["model"] = cand.upstream_model
            api_key = self._env().get(cand.api_key_env, "")
            status, body, latency_ms, headers = self._transport()(
                cand.base_url, api_key, payload, self.timeout_s
            )
            if status is not None and 200 <= status < 300 and isinstance(body, dict):
                self.health.record_success(key, latency_ms=latency_ms)
                self._record_agentic_telemetry(key, payload, body)
                if isinstance(session_id, str) and session_id:
                    self.health.pin_session(session_id, key)
                self._remember(cand, classification, "success")
                _log(
                    f"selected {cand.entry.id} via {cand.gateway}/"
                    f"{cand.upstream_model} task={classification.task_class.value} "
                    f"attempts={len(attempts) + 1}"
                )
                return 200, self._ok_envelope(
                    body, cand, classification, attempts, stream, relaxed=relaxed
                )
            failure = classify_http_failure(
                status, json.dumps(body) if isinstance(body, dict) else str(body)
            )
            reset_at, retry_after = _parse_reset(headers or {}, time.time())
            self.health.record_failure(
                key, failure, reset_at=reset_at, retry_after_s=retry_after
            )
            attempts.append(AttemptRecord(
                candidate=cand.entry.id, gateway=cand.gateway,
                upstream_model=cand.upstream_model,
                outcome="failed", failure=failure.value,
            ))
            redacted_body = _redact(body if isinstance(body, dict) else {"raw": str(body)})
            snippet = json.dumps(redacted_body)[:300]
            _log(
                f"candidate {cand.entry.id} via {cand.gateway} failed: "
                f"{failure.value} (http={status}); trying next; body={snippet}"
            )
            if failure not in RETRYABLE:
                # AUTH / INVALID_REQUEST on this credential/shape: keep going
                # only if untried candidates with *different* credentials exist.
                remaining = [
                    c for c in ranked
                    if c.health_key() not in tried_keys
                    and c.api_key_env != cand.api_key_env
                ]
                if not remaining:
                    break
                continue
        self._remember(None, classification, "exhausted", attempts)
        return 503, self._exhausted(
            attempts, classification, "all candidates exhausted", relaxed=relaxed
        )

    # -- probes ----------------------------------------------------------
    def probe(self, candidate_id: str, gateway: str, upstream_model: str) -> dict:
        """Lightweight health probe: one tiny completion through one upstream."""
        entry = self.registry.by_id(candidate_id)
        if entry is None:
            return {"ok": False, "error": f"unknown candidate {candidate_id}"}
        base_url = ""
        api_key_env = ""
        for up in entry.upstreams:
            if up.gateway == gateway and up.model == upstream_model:
                base_url = self._env().get(up.base_url_env, "") or (up.base_url_default or "")
                api_key_env = up.api_key_env
                break
        if not base_url:
            return {"ok": False, "error": "upstream not configured (no base URL)"}
        key = HealthStore.key(candidate_id, gateway, upstream_model)
        status, body, latency_ms, _ = self._transport()(
            base_url.rstrip("/"),
            self._env().get(api_key_env, ""),
            {"model": upstream_model,
             "messages": [{"role": "user", "content": "ping"}],
             "max_tokens": 1},
            min(30.0, self.timeout_s),
        )
        if status is not None and 200 <= status < 300:
            self.health.record_success(key, latency_ms=latency_ms)
            return {"ok": True, "key": key, "latency_ms": latency_ms}
        failure = classify_http_failure(status, json.dumps(body) if isinstance(body, dict) else str(body))
        self.health.record_failure(key, failure)
        return {"ok": False, "key": key, "failure": failure.value, "http": status}

    # -- envelopes -------------------------------------------------------
    def _ok_envelope(self, body: dict, cand: RankedCandidate,
                     classification, attempts: list[AttemptRecord],
                     stream: bool, relaxed: bool = False) -> dict:
        out = dict(body)
        out["free_auto"] = {
            "virtual_model": VIRTUAL_MODEL,
            "candidate": cand.entry.id,
            "gateway": cand.gateway,
            "upstream_model": cand.upstream_model,
            "task_class": classification.task_class.value,
            "complexity": getattr(classification, "complexity", Complexity.T2).value,
            "reason": cand.score.explanation,
            "relaxed": relaxed,
            "prior_attempts": [a.__dict__ for a in attempts],
        }
        if stream:
            out["_free_auto_stream_replay"] = True
        return out

    def _exhausted(self, attempts, classification, message: str,
                   relaxed: bool = False) -> dict:
        return {
            "error": {
                "message": f"FREE-AUTO: {message}",
                "type": "free_auto_exhausted",
                "code": "all_candidates_exhausted",
            },
            "free_auto": {
                "virtual_model": VIRTUAL_MODEL,
                "task_class": classification.task_class.value
                if classification is not None else "unknown",
                "relaxed": relaxed,
                "attempts": [a.__dict__ if hasattr(a, "__dict__") else a for a in attempts],
            },
        }

    def _record_agentic_telemetry(self, key: str, payload: dict, body: dict) -> None:
        """Record capability-demonstration probes on a successful 200 response.

        Gated on the request explicitly asking for the capability, so a
        candidate is never marked down for a capability nobody tested. Framed
        as a demonstration probe: "did this model produce tool calls / valid
        structured output when asked?" A model that returns no tool_calls when
        asked is recorded not-ok, because from the client's perspective
        "declined" and "cannot" are indistinguishable.
        """
        message = ((body.get("choices") or [{}])[0].get("message") or {})
        tools = payload.get("tools")
        if tools:
            self.health.record_tool_call_result(
                key, ok=bool(message.get("tool_calls"))
            )
        rf = payload.get("response_format")
        if isinstance(rf, dict) and rf.get("type") in ("json_schema", "json_object"):
            content = ((body.get("choices") or [{}])[0].get("message") or {}).get("content")
            ok = False
            if isinstance(content, str) and content.strip():
                try:
                    json.loads(content)
                    ok = True
                except ValueError:
                    ok = False
            self.health.record_structured_output_result(key, ok=ok)

    def _remember(self, cand, classification, outcome, attempts=None) -> None:
        self._history.append({
            "at": time.time(),
            "candidate": cand.entry.id if cand else None,
            "gateway": cand.gateway if cand else None,
            "upstream_model": cand.upstream_model if cand else None,
            "task_class": classification.task_class.value,
            "reason": cand.score.explanation if cand else "exhausted",
            "outcome": outcome,
            "attempts": len(attempts or []),
        })
        self._history = self._history[-50:]

    def status_snapshot(self, top_n: int = 10) -> dict:
        classification, ranked, _ = self.rank_for("status")
        last = self._history[-1] if self._history else None
        cooldowns = []
        for key, h in self.health._entries.items():
            eligible, reason = self.health.is_eligible(key)
            if not eligible:
                cooldowns.append({
                    "key": key,
                    "reason": reason,
                    "reset_at": h.reset_at,
                    "quota_exhausted": h.quota_exhausted,
                    "rate_limited": h.rate_limited,
                })
        return {
            "virtual_model": VIRTUAL_MODEL,
            "selected_virtual_model": VIRTUAL_MODEL,
            "current_actual_model": last.get("candidate") if last else None,
            "provider": last.get("gateway") if last else None,
            "reason_for_selection": (last.get("reason") if last else None),
            "current_task_class": last.get("task_class") if last else None,
            "candidate_ranking": snapshot_for_status(ranked, top_n),
            "ranking_text": format_ranking(ranked, top_n),
            "cooldowns": cooldowns,
            "recent_failures": self.health.recent_failures(10),
            "history": self._history[-10:],
        }


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    router: FreeAutoRouter  # set by serve()

    def log_message(self, fmt, *args):  # keep logs redacted & quiet
        sys.stderr.write(f"[free-auto http] {self.command} {self.path}\n")
        sys.stderr.flush()

    def _send(self, status: int, obj: dict, sse: bool = False) -> None:
        if sse:
            raw = obj
        else:
            raw = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream" if sse else "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            return {}

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/v1/models":
            return self._send(200, {
                "object": "list",
                "data": [{
                    "id": VIRTUAL_MODEL,
                    "object": "model",
                    "owned_by": "free-auto",
                }],
            })
        if path in ("/health", "/v1/health", "/status", "/v1/status"):
            return self._send(200, self.router.status_snapshot())
        return self._send(404, {"error": {"message": f"unknown path {self.path}", "type": "not_found"}})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path != "/v1/chat/completions":
            return self._send(404, {"error": {"message": f"unknown path {self.path}", "type": "not_found"}})
        body = self._read_json()
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return self._send(400, {"error": {
                "message": "messages[] is required",
                "type": "invalid_request",
            }})
        # Auth header accepted but never stored or logged.
        extra = {k: v for k, v in body.items() if k != "messages"}
        status, resp = self.router.complete(messages, extra=extra)
        if extra.get("stream") and status == 200:
            return self._send_sse(resp)
        return self._send(status, resp)

    def _send_sse(self, resp: dict) -> None:
        """Replay a completed response as OpenAI SSE (failover-safe)."""
        try:
            choice = (resp.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            delta: dict[str, Any] = {"role": "assistant"}
            if message.get("content") is not None:
                delta["content"] = message["content"]
            if message.get("tool_calls") is not None:
                delta["tool_calls"] = message["tool_calls"]
            chunk = {
                "id": resp.get("id", "chatcmpl-free-auto"),
                "object": "chat.completion.chunk",
                "created": resp.get("created", 0),
                "model": VIRTUAL_MODEL,
                "choices": [{
                    "index": 0, "delta": delta,
                    "finish_reason": None,
                }],
            }
            # Surface routing transparency in streaming too: attach the same
            # free_auto block (candidate, gateway, reason, relaxed, attempts)
            # that non-streaming responses carry. Unknown top-level fields on a
            # chunk are ignored by OpenAI-compatible parsers, so this is safe.
            if resp.get("free_auto") is not None:
                chunk["free_auto"] = resp["free_auto"]
            if resp.get("_free_auto_stream_replay"):
                chunk["_free_auto_stream_replay"] = True
            final = {
                "id": resp.get("id", "chatcmpl-free-auto"),
                "object": "chat.completion.chunk",
                "created": resp.get("created", 0),
                "model": VIRTUAL_MODEL,
                "choices": [{
                    "index": 0, "delta": {},
                    "finish_reason": choice.get("finish_reason", "stop"),
                }],
            }
            payload = (
                f"data: {json.dumps(chunk)}\n\n"
                f"data: {json.dumps(final)}\n\n"
                "data: [DONE]\n\n"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (OSError, ValueError):
            pass


def build_router(env: dict[str, str] | None = None,
                 transport: Transport | None = None) -> FreeAutoRouter:
    registry = load_registry()
    store = HealthStore()
    store.load()
    return FreeAutoRouter(registry=registry, health=store,
                          transport=transport, env=env)


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
          router: FreeAutoRouter | None = None) -> ThreadingHTTPServer:
    router = router or build_router()
    handler = type("FreeAutoHandler", (_Handler,), {"router": router})
    server = ThreadingHTTPServer((host, port), handler)
    _log(f"FREE-AUTO gateway on http://{host}:{port}/v1 (virtual model: {VIRTUAL_MODEL})")
    return server


def probe_endpoint(base_url: str, timeout_s: float = 5.0) -> dict:
    """Health-check the gateway without raising (incident signature guard).

    Returns {"ok": True, ...} when GET <base>/models answers, else
    {"ok": False, "error": ...} — e.g. "connection_refused" when no
    gateway process is listening (the 2026-10-08 incident signature).
    Operators and tests use this instead of bare urlopen so a dead
    gateway is a structured finding, not a traceback.
    """
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
            models = [m.get("id") for m in body.get("data", [])]
            return {"ok": resp.status == 200 and VIRTUAL_MODEL in models,
                    "http": resp.status, "models": models}
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        name = type(reason).__name__
        text = str(reason) or str(e)
        if "refused" in text.lower():
            return {"ok": False, "error": "connection_refused",
                    "detail": f"{name}: {text}"}
        return {"ok": False, "error": "unreachable",
                "detail": f"{name}: {text}"}
    except Exception as e:  # timeout, bad JSON — still structured
        return {"ok": False, "error": "probe_failed",
                "detail": f"{type(e).__name__}: {e}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FREE-AUTO adaptive free-model gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    server = serve(args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
