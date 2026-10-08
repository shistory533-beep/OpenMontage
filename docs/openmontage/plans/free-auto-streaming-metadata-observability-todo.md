# TODO — FREE-AUTO streaming SSE metadata + relaxed-signal observability

Tracking state (todowrite tool not in this session's catalog; mirrored here).

- [ ] 1. Modify `_ok_envelope`: add `relaxed` param + field in `free_auto` block
- [ ] 2. Modify `_exhausted`: add `relaxed` param + field in `free_auto` block
- [ ] 3. Modify `complete`: pass `relaxed` to both; log when `relaxed=True`
- [ ] 4. Modify `_send_sse`: attach `free_auto` metadata to first SSE chunk
- [ ] 5. Add test: streaming SSE includes routing metadata
- [ ] 6. Add test: `relaxed` signal surfaced in response
- [ ] 7. Run focused verification (new tests + existing suites)
- [ ] 8. Invoke independent reviewer
- [ ] 9. Address reviewer findings
- [ ] 10. Re-run verification + final report

Progress log:
- Baseline: 42 tests passed (test_free_auto_router.py + test_autoplan_workflow.py)
- Steps 1-4 (gateway.py impl): DONE
- Steps 5-6 (tests added): DONE
- Step 7 (verification): IN PROGRESS
