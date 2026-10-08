# Factory Phase 1 Closeout + Phase 2 M1-Prep — Execution Plan (T2)

Date: 2026-10-08. Owner: Build. Status: PLAN → BUILD.

## Objective
Close Phase 1-unblock working set (review + local commit, no push), then run
Phase 2 Apollo/NASA 2-minute excerpt smoke TOPIC→TIMELINE per
`YOUTUBE_FACTORY_MASTER_PLAN.md` §§6/12.

## Constraints (repo reality)
- Frozen F1–F12: extend/add only. `episode_store.py` diff is additive
  fail-closed validation (no interface removal) — acceptable.
- AGENTS.md working-tree addition = Build-lifecycle rule (matches session
  contract; pre-existing, keep; do not expand scope).
- No push/publish/deploy. Local commit only (protects against drift/loss,
  master-plan risk #3). No `checkout/reset/stash` on the working set.
- Env: no system ffmpeg/ffprobe (shim via imageio-ffmpeg/static-ffmpeg);
  Kokoro weights download on first run; misaki OOV gaps known; network-gated
  providers flaky (Wikimedia/Archive.org preferred).
- Tests never weakened; new failures block.

## Steps
1. [x] Audit: master plan + phase reports read; gate suites green
   (49 factory-state, 72 producer, 58 integration/hubs; 74 free-auto).
2. [ ] Review unblock diff (17 files): frozen-module check, mypy on changed
   files, `git diff --check`, full factory gate re-run.
3. [ ] Local commit (no push) with Phase-1-closeout message.
4. [ ] Phase 2 excerpt smoke: Apollo/NASA topic TOPIC→TIMELINE via
   ProducerAgent (2-min excerpt); assert research≥3 sources, evidence
   grounding, factcheck zero blockers, narration silence-free, rights
   classified, edit_decisions valid.
5. [ ] Record smoke evidence in `docs/openmontage/plans/factory-phase2.md`
   (this file) + report. If excerpt blocked (network/weights), record exact
   blocker, fall back to deterministic offline excerpt (fixtures) without
   claiming real-media proof.

## Verification
Focused → gate suites → mypy changed-files → real smoke → report.
Pre-existing fails must stay byte-identical (2× seedance ffprobe, 4×
hyperframes npm).

## Milestone evidence (2026-10-08)
- M1 (closeout): `7ceaf0f` + `de10bfc`, tree clean, no push. mypy 0 new
  errors. Gate suites: 49 + 72 + 58 green.
- M2 (live E2E): `tests/test_producer_live_e2e.py` (real Kokoro narration +
  real Wikimedia footage + real ffmpeg render + full QA + review to
  READY_FOR_REVIEW/APPROVED, publish not performed) — **1 passed in 148 s**
  with `OPENMONTAGE_ALLOW_NETWORK=1`. Real-media path proven end to end.
- FREE-AUTO calibration top-up committed as `4c1d56c` (10/20 sourced).

## Risks
- R1 smoke network flakiness → retry + Wikimedia/Archive-first queries.
- R2 Kokoro first-run download slow → allow extended timeout, cache reuse.
- R3 footage coverage gaps → PERMISSIVE only with flags; gap detector halting
  is a PASS of the safety contract, not a failure to hide.
