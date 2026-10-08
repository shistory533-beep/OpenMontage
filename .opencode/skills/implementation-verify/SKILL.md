---
name: implementation-verify
description: Verify code changes with focused tests first, then broader suites
---
## What I do
- Prove a change works without weakening the suite.

## Procedure
1. Run the focused tests for the touched area first
   (e.g. `python3 -m pytest tests/test_<area>.py -q`).
2. Then run neighboring suites (routing, contracts) and `py_compile` on
   touched modules. See `Makefile` targets (`test`, `test-contracts`).
3. Respect `tests/conftest.py`: no non-loopback network in tests. Live
   endpoint tests must be marked `@pytest.mark.live_api` and run only with
   `OPENMONTAGE_ALLOW_NETWORK=1`.
4. Never weaken or delete tests to make them pass. New behavior needs new
   tests. Compare failures against the pre-change baseline; any new failure
   blocks completion.

## Token-efficient verification
- Run the narrowest relevant verification first; expand only when justified.
  Do not repeat unchanged suites.
- On failure, debug by root cause: reproduce -> localize -> identify root
  cause -> fix -> regression test. Never patch symptoms repeatedly.
- Filter noisy output; report fresh evidence only — never claim done
  without it.
