# FACTORY_STATE_IMPLEMENTATION — YouTube Factory Episode Layer

> Branch: `main` @ `9327439` + 6 untracked additive files (zero modified tracked files).
> Audit basis: `FACTORY_ARCHITECTURE_AUDIT.md` (§4–§7: additive-only map, handoff contracts, step ordering).
> Scope built here: **state/episode layer only** — durable Episode Package, deterministic
> stage machine, versioned artifacts, resumability. No render/Timeline/footage/narration/QA changes.

## 1. What was added (6 new files, no edits to existing code)

| File | Purpose |
|---|---|
| `schemas/factory/episode_package.schema.json` | Envelope schema v1.0: `episode_id`, `title`, `pipeline_type: "youtube-documentary"`, `created_at/updated_at`, `stages` closed to exactly the 19 domains (via `propertyNames` enum — `additionalProperties: false` alone does not close `patternProperties` keys; caught by test). Each stage: `state` (6-value enum), `artifact_version`, `artifact`, `failure_reason`, `provider` (label only), `started_at/updated_at/reviewed_at/approved_at/done_at`. |
| `lib/factory_stages.py` | Pure FSM, no I/O: `FACTORY_STAGES` (19, factory order), `STAGE_STATES` (PENDING/RUNNING/REVIEW/APPROVED/DONE/FAILED), transition table + `validate_transition` / `allowed_targets`. `DONE` terminal per version; reopen is explicit `DONE → RUNNING`. |
| `lib/episode_store.py` | `EpisodeStore`: `init` (idempotent) / `load` / `validate` / `transition` / `set_artifact` / `fail` / `status`. Atomic tmp-write + `os.replace`, pre-mutation copy into `history/` (never deletes), artifact-version bump on payload write, mandatory `failure_reason` on `FAILED`, known-payload re-validation via `schemas/artifacts` (`ARTIFACT_SCHEMA_MAP`: research→`research_brief`, script→`script`, storyboard→`scene_plan`, footage→`asset_manifest`, editorial/timeline→`edit_decisions`, render→`render_report`, qa→`final_review`, publish→`publish_log`; unmapped stages stay free-form/provider-agnostic). |
| `tests/test_factory_state.py` | 13 unit tests: stage coverage, lifecycle states, legal/illegal edges, determinism, init/idempotence, timestamps, FAILED-reason mandatory + cleared-on-retry, artifact versioning, known-schema accept/reject, provider-agnostic payload, append-only history, envelope closedness. |
| `tests/test_factory_state_integration.py` | 3 integration tests: full 19-stage `PENDING→RUNNING→REVIEW→APPROVED→DONE` lifecycle with envelope validation; crash-resume via fresh handle (interrupted `RUNNING` resumes, completed stages intact); failure→retry with failure preserved in history. |
| `FACTORY_STATE_IMPLEMENTATION.md` | This file. |

## 2. What was reused (not rewritten)

- `lib/paths.py:PROJECTS_DIR` — episode root (`projects/<episode_id>/episode.json`); honors `OPENMONTAGE_PROJECTS_DIR` override, so Backlot board convention and test isolation both hold.
- `lib/checkpoint.py` patterns — atomic write, `history/` archival, UTC timestamps, gate-style hard errors — reimplemented against the new file, not by editing the module.
- `schemas/artifacts/*` + `validate_artifact` — payload validation for the 9 mapped stages; envelope schema deliberately does **not** duplicate them.
- `tests/conftest.py` network guard — new tests are fully offline (`tmp_path` projects dir, no sockets); they pass under the guard unmodified.
- Untouched per constraints: render pipeline (`tools/video/video_compose.py`), Timeline IR (`edit_decisions` schema), footage intelligence (`lib/corpus.py`, `corpus_builder`/`clip_search`), narration (`tts_selector`/providers), QA architecture (validators exist, unwired — wiring is a later step per audit §7-step 5).

## 3. Test results

- New tests: **17/17 pass** (`tests/test_factory_state.py` + `tests/test_factory_state_integration.py`).
- Typecheck: `mypy lib/factory_stages.py lib/episode_store.py --ignore-missing-imports` → **no issues** (mypy 2.4.0, installed ad-hoc for this run).
- Compile: `py_compile` on all 4 new Python files → OK.
- Full suite (`tests/ --ignore=tests/qa`): **1880 passed**, 24 skipped, 3 xfailed, 6 failed — **all 6 failures reproduced on the clean tree** (`git stash -u` + rerun) and are pre-existing/environmental, unrelated to this change:
  - `test_seedance_ark_video.py` (2): expects ffprobe-present error strings; this container lacks ffprobe (`'ffprobe is required...'` vs `'2 to 15 seconds'`).
  - `test_hyperframes_compose.py` (4): npm-package/runtime environment assumptions.
- Two defects caught by the new tests during development and fixed: envelope accepted undeclared stage keys (fixed with `propertyNames` enum); integration crash test used a schema-mapped stage with a free-form payload (fixed fixture).

## 4. Remaining risks / non-goals (explicitly out of scope)

1. **No pipeline manifest yet** — `pipeline_type: "youtube-documentary"` is a declared constant, but `pipeline_defs/youtube-documentary.yaml` does not exist (audit §7-step 1). The store does not enforce cross-stage prerequisites (e.g. storyboard DONE before footage RUNNING); that belongs to the manifest + checkpoint layer, not this FSM.
2. **No concurrency control** — two writers to one `episode.json` last-write-wins (atomic per write, no locking). Single-agent operation assumed; add file locking if parallel workers appear.
3. **History growth unbounded** — one copy per mutation, never pruned. Correct for now (audit: append-only); add retention policy once episode volumes grow.
4. **`storyboard → scene_plan` mapping is provisional** — closest canonical contract today; a dedicated `storyboard.schema.json` (audit §4) should replace it when the storyboard assembler lands.
5. **Pre-existing suite failures** (seedance/ffprobe, hyperframes/npm) untouched — environmental, verify in CI with real toolchain before release.
