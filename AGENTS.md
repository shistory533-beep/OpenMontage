# OpenMontage

**MANDATORY: Read `AGENT_GUIDE.md` before responding to ANY user message.**

Do not act on the user's request until you have read AGENT_GUIDE.md.
It contains routing rules that determine your first action based on what the user asked.
Skipping it WILL cause you to take the wrong action.

Video-production instructions live in AGENT_GUIDE.md. The Build lifecycle
rule below also lives in this file so every session receives it.

## Build Lifecycle — Autoplan Before Implementation (BINDING)

For every non-trivial task (anything beyond a one-line or config-only fix),
Build MUST follow this lifecycle. Never begin editing immediately.

1. UNDERSTAND — Read the relevant repository files, tests, configs, and call
   sites first. Evidence before synthesis; reuse existing architecture.
2. EXPLORE — For unfamiliar or large areas, delegate to the `explore`
   subagent (read-only); use `general` only when a multi-step delegated task
   is justified. Do not duplicate existing functionality.
3. PLAN — Before any implementation, write a concrete plan containing:
   objective, discovered constraints, affected files/modules, existing
   abstractions to reuse, ordered implementation steps, verification
   strategy, risks/blockers.
4. TODO — Convert the plan into `todowrite` items and keep their state
   synchronized with actual progress.
5. BUILD — Only after planning, modify files. Work incrementally and verify
   after each meaningful step.
6. VERIFY — Focused tests first, then broader tests/typecheck/lint. Use a
   real smoke test when the feature touches real providers, FFmpeg, TTS,
   HTTP, or other billable/external endpoints.
7. REVIEW — Compare the implementation against the plan. Check for
   regressions, duplicated abstractions, and missing tests. Fix issues
   before finishing.
8. REPORT — Finish with: plan completed, files changed, tests/verification,
   remaining risks, next recommended task.

Rules: repository archaeology and planning come first; TODO items are
required for multi-step work; verification and review are required before
completion. Trivial one-line/config-only fixes may plan lightweight (one or
two sentences), but never skip reading the affected file first. When
repository reality conflicts with an assumption, stop and report the exact
conflict instead of guessing.
