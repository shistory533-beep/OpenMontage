# TODO — FREE-AUTO agentic-reliability telemetry end-to-end

- [x] 1. gateway.complete: record tool/SO telemetry on 200 when requested
- [x] 2. scoring.score_candidate: fold live tool/SO rates into components
- [x] 3. Add tests: telemetry recorded; scoring folds it in; regression guard
- [x] 4. Update FREE_AUTO_ROUTER.md ranking section
- [x] 5. Run focused verification (new tests + existing suites)
- [x] 6. Invoke independent reviewer
- [x] 7. Address reviewer findings
- [x] 8. Re-run verification + final report

Progress log:
- Baseline: 45 tests passed (test_free_auto_router.py + test_autoplan_workflow.py)
- Plan artifact created: free-auto-agentic-telemetry.md
- After implementation: 50 passed
- Review: 1 CRITICAL (none), 5 SUGGESTION, 4 NITPICK
- Addressed: SO probe now validates JSON content; added gate-off + json_object +
  SO scoring fold-in tests; refreshed plan + this TODO.
- After review fixes: 53 passed (test_free_auto_router.py + test_autoplan_workflow.py)
- NOTE: seed registry concurrently expanded 10 -> 20 with measured capabilities;
  re-verified, all green, ranking deterministic.
