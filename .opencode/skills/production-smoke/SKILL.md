---
name: production-smoke
description: Single safe smoke request against real local or provider endpoints
---
## What I do
- Prove end-to-end wiring with one trivial request.

## Procedure
1. Prefer loopback servers (allowed by the test network guard) with stub or
   mock upstreams for OpenAI/HTTP compatibility checks.
2. One trivial prompt only (e.g. "say ok"). Billable or external provider
   calls need explicit user approval first and must never publish, push, or
   mutate remote state.
3. Assert the response envelope plus the observable metadata (selected
   model, reason, ranking or status endpoint).
4. Record the smoke result (command, outcome, actual model/endpoint) in the
   final report. Never log secrets.
