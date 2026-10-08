# Plan: FREE-AUTO streaming SSE metadata + relaxed-signal observability

## Objective
Close the observability gap between FREE-AUTO's non-streaming and streaming
response paths, and surface the `relaxed` capability-filter-fallback signal
that is currently computed but discarded.

## Classification
T2 — multi-file (implementation + tests), bounded scope, production-relevant.
No architectural rewrite; reuses the existing `free_auto` envelope + SSE replay
machinery in `lib/free_auto/gateway.py`.

## Evidence Pack

### FILES
- `lib/free_auto/gateway.py` — `FreeAutoRouter` (rank_for, complete, _ok_envelope,
  _exhausted, _send_sse, status_snapshot), `urllib_transport`, `_redact`, `_Handler`
- `lib/free_auto/health.py` — `HealthStore`, `classify_http_failure`, `RETRYABLE`
- `lib/free_auto/scoring.py` — `rank_candidates`, `RankedCandidate`, `CandidateScore`
- `lib/free_auto/task_classify.py` — `classify_task`, `TaskClass`
- `lib/free_auto/registry.py` — `Registry.filter_for_task`, `Registry.eligible`
- `lib/free_auto/model_registry.json` — 10 seed entries (all capabilities `None`)
- `tests/test_free_auto_router.py` — router cascade + HTTP tests (42 passed)
- `tests/test_autoplan_workflow.py` — FREE-AUTO config guard (8 passed)
- `.opencode/prompts/build-autoplan.md` — build prompt referencing todowrite/reviewer/etc.
- `docs/openmontage/FREE_AUTO_ROUTER.md` — router architecture doc

### SYMBOLS
- `FreeAutoRouter.rank_for()` — returns `(classification, ranked, relaxed)`;
  `relaxed=True` when `filter_for_task` is empty and falls back to `eligible()`
- `FreeAutoRouter.complete()` — cascade: rank → try candidates → fail over
- `FreeAutoRouter._ok_envelope()` — builds `free_auto` response block
- `FreeAutoRouter._send_sse()` — replays a completed response as OpenAI SSE
- `HealthStore.is_eligible()` — cooldown / reset gating
- `Registry.filter_for_task()` — capability gate (None=unknown/eligible, only False filtered)

### FINDINGS (empirically confirmed)
1. **Streaming SSE drops routing metadata.** `do_POST` calls `_send_sse(resp)` when
   `stream=true`. `resp` contains a full `free_auto` block (candidate, gateway,
   reason, prior_attempts, `_free_auto_stream_replay`). `_send_sse` extracts only
   `choices[0].message.content` + `tool_calls` and emits 2 chunks + `[DONE]`.
   The `free_auto` block is **completely discarded**. Verified empirically:
   streaming response body contains NO `free_auto` field. Non-streaming responses
   DO include it. Streaming clients (OpenCode `@ai-sdk/openai-compatible`) have
   zero routing transparency — cannot audit which upstream model was selected,
   cannot debug failover, cannot attribute cost.
2. **`relaxed` flag is dead state.** `rank_for` returns `relaxed` (True when the
   capability filter was too strict and fell back to all eligible candidates),
   but `complete` assigns it (`classification, ranked, relaxed = ...`) and never
   reads it again. It is absent from every response envelope and log line.
3. **`_redact` is defined but never called** (dead security code). Docstring
   claims "Authorization headers are redacted"; the function exists but is unused.
   Out of scope for THIS change — noted as a separate finding.
4. With the current registry (all capabilities `None`/unknown), `filter_for_task`
   never filters anything, so `relaxed` is currently always False. The signal is
   forward-looking: as capabilities get measured, `relaxed` will activate. We add
   the surface now so it's testable and observable when it does.

### CONSTRAINTS
- Must not break OpenAI-compatible SSE parsing. Adding a top-level `free_auto`
  field to a `chat.completion.chunk` is safe: OpenAI clients ignore unknown
  top-level fields on chunks (already done for non-streaming responses).
- Must not change the non-streaming envelope shape (only ADD `relaxed`).
- Tests must use mocked transports (conftest blocks non-loopback network).

### GAPS
- No test for the streaming SSE path (`stream=true`).
- No test for the `relaxed` fallback signal.
- `relaxed` not in any response envelope or log.

### RECOMMENDATION
1. `gateway.py`: thread `relaxed` through `_ok_envelope` + `_exhausted`; add
   `relaxed` to the `free_auto` block; log when `relaxed=True`.
2. `gateway.py`: in `_send_sse`, attach `resp.get("free_auto")` as a top-level
   field on the FIRST SSE chunk so streaming clients get routing transparency.
3. `tests/test_free_auto_router.py`: add streaming SSE test (format + metadata)
   and a `relaxed`-signal test using a mock registry entry with a capability set
   to `False`.

## Affected Files
- `lib/free_auto/gateway.py` (modify)
- `tests/test_free_auto_router.py` (add)

## Reuse
- Existing `FreeAutoRouter._ok_envelope`, `_exhausted`, `_send_sse`, `rank_for`
  — extend, do not replace.
- Existing test helpers (`_router`, `_ok_transport`, `FULL_ENV`, `_ok_response`).
- No new modules, no new routers.

## Steps
1. Modify `_ok_envelope`: add `relaxed: bool = False` param; add `"relaxed": relaxed`
   to `free_auto` block.
2. Modify `_exhausted`: add `relaxed: bool = False` param; add `"relaxed": relaxed`
   to `free_auto` block.
3. Modify `complete`: pass `relaxed=relaxed` to both `_ok_envelope` and `_exhausted`;
   add a `_log` line when `relaxed=True`.
4. Modify `_send_sse`: attach `resp.get("free_auto")` to the first SSE chunk as a
   top-level field.
5. Add tests: `test_streaming_sse_includes_routing_metadata`,
   `test_relaxed_signal_surfaced_in_response`.
6. Run focused tests, then broader suite.

## Verification
- `python3 -m pytest tests/test_free_auto_router.py tests/test_autoplan_workflow.py -q`
  — all pass (baseline 50, expected 52+).
- Empirical streaming check (mock transport): SSE response now contains `free_auto`.
- Narrowest-first: run only the two new tests, then the two existing suites.

## Risks / Blockers
- **Risk**: OpenAI-compatible client breaks on extra top-level SSE field.
  **Mitigation verified**: non-streaming path already returns `free_auto` as a
  top-level field and OpenCode consumes it; streaming consistency is strictly
  better. Unknown top-level fields are ignored by `ai-sdk` OpenAI-compatible
  streaming parsers.
- **Risk**: `relaxed` threading changes envelope shape.
  **Mitigation**: only ADDS a field; existing assertions (`resp["free_auto"]["candidate"]`)
  are unaffected.
- No external/network/billable endpoints involved (mocked transport).
