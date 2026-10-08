---
name: repository-archaeology
description: Read-first repository investigation before non-trivial changes
---
## What I do
- Establish ground truth from the repo before proposing any change.
- Route large or unfamiliar areas to the `explore` subagent (read-only).

## Procedure
1. Read `PROJECT_CONTEXT.md`, then the files, tests, configs, and call
   sites relevant to the task. For video work, also read the matching
   section of `AGENT_GUIDE.md`.
2. For unfamiliar or large areas, delegate a scoped question to the
   `explore` subagent; use `general` only for justified multi-step analysis.
3. Check for an existing abstraction that already covers the need
   (registry, selectors, `lib/scoring.py`, `lib/free_auto/`, pipeline
   manifests). Reuse it; never duplicate it. Search order for anything
   new: reuse -> extend -> adapt -> build new.
4. Record: objective, constraints, affected files, reuse candidates,
   risks. Evidence before synthesis — no claim without a file path.

## Iterative retrieval (unfamiliar tasks)
- Cycle: dispatch a scoped query -> evaluate relevance -> refine -> repeat.
- Maximum 3 cycles. Stop as soon as evidence is sufficient.

## Output: EVIDENCE PACK (compact, structured — no long narratives)
- FILES: paths with line ranges that matter.
- SYMBOLS: function/class/schema names and where defined.
- FINDINGS: what the code actually does (with paths).
- CONSTRAINTS: contracts, gates, frozen modules, test guards.
- GAPS: what could not be found or verified.
- RECOMMENDATION: reuse target or minimal new surface.

## Orientation
- `PROJECT_CONTEXT.md` is the maintained architecture map — start there,
  not with a full-tree walk. No separate index artifact or MCP is used;
  per-task evidence packs replace a persistent map, so nothing goes stale.
- Read the smallest useful ranges; search before opening large files;
  batch independent searches; never pass large parent context to subagents.
