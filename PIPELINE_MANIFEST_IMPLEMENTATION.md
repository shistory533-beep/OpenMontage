# PIPELINE_MANIFEST_IMPLEMENTATION — youtube-documentary

> Pipeline type `youtube-documentary` (declared as a constant by the episode
> layer) now has an explicit, schema-validated definition. No Producer Agent
> (per task scope). No render-core / Timeline-IR changes.

## 1. Files added / changed

| File | Change |
|---|---|
| `pipeline_defs/youtube-documentary.yaml` | **Added.** 15 stages in fixed order: topic, research, script, fact_check, storyboard, narration, footage, editorial, timeline, audio, render, qa, packaging, human_review, publish. Category `documentary`, stability `beta`, guided policy. Each stage declares: id (`name`), prerequisites (`required_artifacts_in` chaining the previous stage's output), input artifacts (`required_artifacts_in`), output artifacts (`produces` — canonical names where payloads conform: brief, research_brief, script, scene_plan, asset_manifest, edit_decisions, render_report, final_review, publish_log; new descriptive names otherwise: factcheck_report, narration_manifest, audio_mix, package_bundle, review_decision), required state / failure / retry / checkpoint-boundary behavior (in `success_criteria`, schema-legal strings — stage-level custom keys are forbidden by the manifest schema), tool menus (existing registry names only; footage stage excludes all generative tools), `checkpoint_required: true` everywhere, binding gates on topic/script/storyboard/footage/human_review/publish. Topic stage points at the new topic-director skill (runtime lock documented). |
| `lib/pipeline_guard.py` | **Added.** Pure validation reusing `pipeline_loader` + `checkpoint` readers — no state-machine duplication. `assert_stage_ready` (predecessors completed + gated predecessors approved + `required_artifacts_in` present across predecessor artifacts; fail closed via `PrerequisiteError`), publish special-case (`PublishBlockedError` unless human_review completed AND approved), `validate_sequence` (order/unknown-stage rejection), `next_pending` + `read_checkpoints` (resume helpers). |
| `skills/pipelines/youtube-documentary/topic-director.md` | **Added.** Planning skill carrying the repo's runtime-selection governance (remotion lock, HyperFrames named, present-both + `render_runtime_selection` decision). Required so the new pipeline passes the repo-wide planning contract instead of dodging it. |
| `tests/contracts/test_runtime_presentation_contract.py` | **Changed (1 hunk).** `_planning_stages` also recognizes `topic` — extends governance coverage to the new pipeline, weakens nothing (all previously passing pipelines unaffected). |
| `tests/test_youtube_documentary_pipeline.py` (8 tests) | **Added.** Manifest loads/schema-valid; exact deterministic 15-stage order; binding gates; footage tool-menu closed set; guard happy path; missing predecessor; missing artifact; unapproved gate; invalid order (incl. unknown stage, Producer explicitly out of scope); publish blocked pre-approval (3 sub-cases); resume pointer. |
| `tests/test_youtube_documentary_integration.py` (3 tests) | **Added.** Real on-disk checkpoints: ordered run + `get_next_stage` resume; `failed` render halts then retry continues; publish blocked → human_review APPROVED → publish completes, run ends (`get_next_stage is None`). |
| `PIPELINE_MANIFEST_IMPLEMENTATION.md` | This file. |

## 2. Requirement mapping

- Existing abstractions: manifest schema (`pipeline_manifest.schema.json`), loader (`get_stage_order`), checkpoint gates/prerequisite enforcement/resume (`write/read/get_next_stage`), canonical artifact schemas for payload validation. Guard only adds the artifact-presence + publish-approval checks the checkpoint layer does not perform.
- No state-machine duplication: guard holds no state; order/gates authoritative in YAML.
- No render-core / Timeline-IR modification: `render` consumes `edit_decisions`; `timeline` refines (not replaces) the same IR; runtime lock inherited.
- Fail closed: guard raises before any tool runs; checkpoint prerequisite enforcement independently rejects out-of-order writes (both covered by tests).
- Schema validation: manifest loads via `load_pipeline` (jsonschema) — enforced by `test_pipeline_catalog` iteration automatically.
- Deterministic order: single YAML list; `get_stage_order` returns declaration order (catalog test pins this).
- Resume: `get_next_stage` + `read_checkpoints`/`next_pending`; failed status is non-terminal by design.
- Publish gating: manifest `human_approval_default: true` on human_review + publish, plus guard's approval check (defense in depth; tested at both layers).

## 3. Tests

- New: **15/15 pass** (12 unit + 3 integration).
- Related: pipeline catalog (all manifests), manifest categories, runtime presentation contract (incl. new youtube-documentary param) — all pass.
- mypy on `lib/pipeline_guard.py`: clean.
- Full suite (`--ignore=tests/qa`): **1915 passed**, 25 skipped, 3 xfailed; **6 failed — all pre-existing/environmental** (2× seedance_ark expect ffprobe-present strings absent in this container; 4× hyperframes_compose assume npm runtime), identical set to the pre-change baseline.

## 4. Known risks

1. **Stage skills mostly unwritten** — only `topic-director.md` exists; the other 14 stages have no `skill:` ref (schema-optional, so valid). Agents running those stages lack director guidance until skills land; Producer Agent explicitly deferred.
2. **`timeline` re-emits `edit_decisions`** — refinement-by-overwrite relies on checkpoint `history/` for versioning rather than distinct artifact names; acceptable per existing archival guarantees, but downstream consumers must read the latest checkpoint, not assume single-write.
3. **New artifact names unvalidated at checkpoint** (`factcheck_report`, `narration_manifest`, `audio_mix`, `package_bundle`, `review_decision` pass through checkpoint validation unchecked — existing fail-open for unknown names). Dedicated schemas should be added with the corresponding stage implementations.
4. **Episode-store (19 stages) vs manifest (15 stages) divergence** — `sources/facts/claims/thumbnail/metadata/analytics` live in the episode FSM but have no manifest stages yet; unification (or explicit mapping) is future work.
5. **Contract-test edit** — one hunk in `test_runtime_presentation_contract.py`; it strengthens coverage but touches a governance test — flag for reviewer attention.
6. **Pre-existing suite failures** (seedance/ffprobe, hyperframes/npm) untouched; verify in CI with the real toolchain.
