# Build — Autoplan enforcement

The binding Build lifecycle is defined in `AGENTS.md` ("Build Lifecycle —
Autoplan Before Implementation"). Follow it for every non-trivial task:
Understand → Explore → Plan → TODO → Build → Verify → Review → Report.
Never edit before planning.

- Start from repository reality: read `PROJECT_CONTEXT.md`, the relevant
  files, tests, and configs before changing anything. Reuse existing
  architecture; do not create a second router, planner, or orchestrator.
- Unfamiliar or large area? Delegate read-only archaeology to the `explore`
  subagent; use `general` only for justified multi-step analysis. Load the
  `repository-archaeology` skill for the procedure.
- Write the plan (objective, constraints, affected files, reuse, steps,
  verification, risks) and track it with `todowrite`.
- Verify with the `implementation-verify` skill; smoke real endpoints with
  `production-smoke`. When risk or size justifies it, send the diff to the
  `reviewer` subagent before finishing and fix findings.
- Before compaction, summarize state: plan progress, files changed, test
  results, open risks.
- When repository reality conflicts with an assumption, stop and report
  instead of guessing.

## Adaptive depth (never use T3 ceremony for T0 work)

- T0 trivial: direct edit + minimal verification.
- T1 local: targeted read -> edit -> focused test.
- T2 multi-file: targeted Explore -> compact evidence -> plan ->
  TODO -> build -> verify.
- T3 architectural/high-risk: parallel independent research only where
  justified -> plan artifact at `docs/openmontage/plans/<task>.md` ->
  TODO -> Build -> independent `reviewer` -> verify -> fix.
- If implementation contradicts the plan, record finding / ruling /
  reason / plan adjustment in the plan artifact. Never continue silently
  on an invalid plan.
- Compact context at logical boundaries (after exploration, milestones,
  debugging, before unrelated work), preserving objective, decisions,
  changed files, TODO state, tests, blockers, next action.
- Route by role through FREE-AUTO task classes: Explore -> fast/cheap,
  T0/T1 -> efficient coding, T2 -> stronger coding/reasoning,
  T3/review -> strongest eligible. Never spend a strong model on trivial work.
- Promote repeated successful patterns into Skills/commands only after
  evidence and review; never rewrite `AGENTS.md` automatically per session.
