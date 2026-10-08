---
name: free-auto
description: Route LLM work through the FREE-AUTO gateway and maintain its model catalog
---

## What I do

- Route tasks to the cheapest capable free model via the local gateway; keep
  the catalog honest and the ranking evidence-based.

## Procedure

1. Gateway is the only router. Ensure it is up (idempotent — safe to run
   every session start, and wired to container start via
   `.devcontainer/devcontainer.json`): `bash scripts/free_auto_gateway.sh
   start` (or `make free-auto-up`). Never run the gateway any other way;
   never build a second router; extend `lib/free_auto/` (classify → filter
   → rank → cascade → failover).
2. Per request you may set `complexity` (`t0`–`t3`, or `[T0]`–`[T3]` tag in
   text) and `session_id` (winner sticks while eligible). Read the
   `free_auto{}` block (candidate, gateway, task_class, complexity, reason,
   relaxed, prior_attempts) — never assume which upstream served.
3. Catalog changes go in `lib/free_auto/model_registry.json` only: verified
   capabilities from provider metadata, `free_tier` per upstream (`free` only
   with an observed `:free`/`-free` marker), `benchmark.source` stays null
   until a citable measured score exists. Routers and safety-classifiers are
   rejected by `registry.py` — never add them as leaves.
4. Ranking is computed (`scoring.py` + live `health.py` telemetry), never
   hardcoded. Refresh the lineup with public `GET /v1/models`-style listings;
   record source + date in `docs/openmontage/FREE_AUTO_CATALOG.md`.
5. Verify with mocked transports + loopback E2E (see `production-smoke`);
   never spend billable calls. No keys → record AUTH_REQUIRED, don't guess.

## Token-efficient routing (roles)

- Explore → fast/cheap (FAST_SIMPLE) · T0 → fastest capable · T1 → efficient
  coding · T2 → strong coding/reasoning (default) · T3/review → strongest
  eligible (review: independent family) · Research → strong long-context.
