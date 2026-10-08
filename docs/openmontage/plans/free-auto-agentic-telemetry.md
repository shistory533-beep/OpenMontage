# Plan: FREE-AUTO agentic-reliability telemetry end-to-end

## Classification
T2. Multi-file (gateway + scoring + tests), bounded, production-relevant.
No architectural rewrite; no duplicate router/orchestration.

## Objective
Wire the existing but unused `HealthStore.record_tool_call_result` /
`record_structured_output_result` telemetry into the live cascade, and fold
that live signal into the `tool_use` / `structured_output` scoring components,
so FREE-AUTO can learn and demote candidates that actually fail on agentic
work instead of relying on static (all-None) priors.

## Evidence Pack
FILES: lib/free_auto/gateway.py, lib/free_auto/scoring.py,
lib/free_auto/health.py, lib/free_auto/registry.py,
lib/free_auto/model_registry.json, tests/test_free_auto_router.py
SYMBOLS: FreeAutoRouter.complete, score_candidate, HealthStore.{record_tool_call_result,record_structured_output_result,_entries}
FINDINGS:
1. record_tool_call_result / record_structured_output_result exist, persist,
   and are unit-tested (test_tool_call_and_so_failures_recorded) but have ZERO
   production callers (grep: only health.py + the test).
2. scoring.py reads only quota_health / historical_success / is_eligible from
   health; tool_use & structured_output components come solely from
   _cap(entry.tool_use) -> (0.5, False) for all 10 seed entries (capabilities
   all None). Verified: model_registry.json capabilities all null.
3. Consequence: agentic reliability is decorative. A candidate that fails
   every tool call is never demoted; the components contribute 0.5*w always.
4. FREE_AUTO_ROUTER.md advertises "tool-call/SO rates" in health but the
   ranking model section never mentions them feeding ranking -> doc/code gap.
CONSTRAINTS: reuse existing methods only; no new modules; must not break
deterministic ranking or existing 45 tests; mocked transports only.
GAPS: no end-to-end telemetry feed; scoring ignores live tool/SO rates;
no test exercises the feed path.
RECOMMENDATION:
1. gateway.complete: after a 200, record tool/SO telemetry when the request
   explicitly asked for it (payload["tools"] / payload["response_format"]).
2. scoring.score_candidate: when telemetry exists (attempts>0), override the
   static prior with the live success rate; mark known=True.
3. Add tests: telemetry recorded on success/failure; scoring folds it in;
   unmeasured path unchanged (regression guard).
4. Update FREE_AUTO_ROUTER.md ranking section to document the feed.

## Affected Files
- lib/free_auto/gateway.py (modify)
- lib/free_auto/scoring.py (modify)
- tests/test_free_auto_router.py (add)
- docs/openmontage/FREE_AUTO_ROUTER.md (modify)

## Reuse
Existing HealthStore methods and score_candidate; extend, do not replace.

## Steps
1. gateway.complete: after record_success, detect request requirements from
   payload and call record_tool_call_result / record_structured_output_result.
2. scoring.score_candidate: fold h.tool_call_attempts/failures into tool_use;
   h.so_attempts/failures into structured_output.
3. Add 4 tests.
4. Run focused tests, then broader suite.
5. Update router doc.

## Verification
- pytest tests/test_free_auto_router.py tests/test_autoplan_workflow.py -q
  (baseline 45; expected 49+). Re-run after review: 53 passed.
- Narrowest-first: new tests only, then the two suites.

## Review findings addressed
- SO probe now validates JSON content (was: ok=bool(choices), never failed).
- Added gate-off negative test + json_object test + SO scoring fold-in test.
- Plan + TODO refreshed to match the tree.

## Risks
- Over-recording (request had no tools but we record failure): mitigated by
  gating on payload["tools"] / response_format presence.
- Ranking determinism: telemetry is deterministic given the same history;
  tie-breaks unchanged.
