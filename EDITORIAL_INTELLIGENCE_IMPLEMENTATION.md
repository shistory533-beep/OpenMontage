# Editorial Intelligence Implementation

Branch: `documentary-factory`. Additive layer under `lib/editorial/` —
no changes to existing production infrastructure except registering three
new artifact schemas and upgrading two placeholder payloads in the
youtube-documentary integration test to satisfy them.

## Architecture

```
ResearchAgent (research.py)
  -> ResearchPackage (contracts.py) + evidence_bundle.schema.json
ScriptAgent (script_agent.py)
  -> DocumentaryScript + script.json (canonical script schema)
     + readable script + pacing report + claim mapping
FactCheckAgent (factcheck.py)
  -> FactCheckReport + factcheck_report.schema.json
StoryboardAgent (storyboard.py)
  -> storyboard.json + storyboard.schema.json
     + to_scene_plan() adapter (canonical scene_plan schema)
VisualScorer (visual_scoring.py)
  -> per-candidate breakdowns embedded via attach_scores()
```

Deterministic, offline, no network, no LLM calls. The directing agent
supplies material; this layer structures, validates, and enforces.
It never invents evidence, never rewrites claims, never assumes footage.

## Part 1 — Research Agent (`lib/editorial/research.py`)

- Input: topic/audience/language/duration/niche + SourceRecords, Facts,
  Claims, open questions supplied by the directing agent.
- Source policy: `PRIMARY_SOURCE_TYPES` (government, official_statistics,
  company_filing, academic, court_document, dataset, original_report)
  outrank secondary; `quality_weight()` is rule-based (type + date
  presence) — publisher reputation is never guessed.
- Every source validated: title, URL (http/https), publisher, source
  type, retrieval time. Missing/invalid -> `ResearchError`.
- Separation enforced: FACT / INFERENCE / OPINION / UNRESOLVED statement
  types; opinions cannot carry numeric values; factual claims must link
  fact ids that exist; quotes require attribution.
- Contradictions: numeric conflicts (>5% relative, same subject+unit)
  and date conflicts across facts sharing a `subject_key`.
- Confidence: mean source weight, capped at 0.7 for single-source facts.
- `SourceCache`: disk-backed, content-addressed, resume-safe;
  dedupe by normalized URL (tracking params stripped) + title/publisher.
- `save_state` / `resume`: interrupted runs continue without re-retrieval.
- `build_package()`: validates all linkage, computes confidence,
  builds the evidence graph (claim->fact->source edges), pins a
  deterministic `package_hash` (canonical JSON sha256, excludes hash and
  timestamp so rebuilds match).

## Part 2 — Script Agent (`lib/editorial/script_agent.py`)

- 9-beat structure enforced in order, must open HOOK / close PAYOFF.
- Each block requires id, chapter, beat, text, claim links, pacing /
  emotional / visual intent.
- Duration: per-language WPM table (default 150), target enforced ±10%.
- Grounding: every numeric token must appear in linked evidence
  (fabricated statistics fail); quoted strings need attributed,
  evidence-linked quote claims; causal/superlative language needs ≥2
  independent sources; weasel attributions flagged; 4-gram filler
  repetition flagged; unresolved-linked blocks must keep hedge language.
- Outputs: `script_json()` (validates against canonical `script` schema;
  extension fields under `metadata.documentary`), `readable_script()`
  (markdown), pacing report (per-beat seconds), `claim_mapping_json()`.
  Unsupported blocks are listed explicitly, never silently passed.

## Part 3 — Fact Check Agent (`lib/editorial/factcheck.py`)

- Independent: reads script blocks + package only; pins `package_hash`
  on the report so it cannot be applied to different research.
- Verdicts: verified / partially_verified / contradicted / unsupported /
  opinion / requires_research, each with claim id, statement, source
  ids, evidence summary, confidence, problem code, recommendation
  (cut | re-source | hedge | research | none).
- Detectors: numeric discrepancy (year-shaped tokens routed to the date
  detector), date discrepancy, attribution error (named source published
  none of the cited evidence), fake quote risk, causal overclaim,
  unsupported superlative, source mismatch, contradiction via package
  graph.
- Blocking: contradicted always blocks; unsupported / requires_research
  block when critical; structural breaks (unknown claim ids) always
  block. `report.passed` is false while any blocker remains.
- Never rewrites: recommendations are actions only; tests assert no
  corrective prose appears in verdicts.

## Part 4 — Storyboard Agent (`lib/editorial/storyboard.py`)

- Requires a passing fact-check report, else `StoryboardError`
  (fail closed — quarantined claims never reach the board).
- Every narration block gets ≥1 VisualRequirement (long blocks split,
  max 4); full field contract per requirement (objective, subject,
  location, period, media type, shot type/function from the 12-function
  vocabulary, min/desired duration, evidence relationship, claim links,
  positive/exclusion terms, verified rights, priority, fallback).
- Shot function derived deterministically: chart/map/archival keyword
  rules, else beat table (hook->establishing ... payoff->payoff).
- Availability is UNCERTAIN by default, MISSING only for blocked-claim
  dependencies; the board NEVER assigns AVAILABLE (only a retrieval
  pass may promote). No generated stand-ins anywhere.
- Outputs chapter plan + coverage proof (desired seconds ≥ narration),
  and `to_scene_plan()` maps requirements onto the canonical
  `scene_plan` schema for the pipeline storyboard stage.

## Part 5 — Visual Scoring (`lib/editorial/visual_scoring.py`)

- 12 weighted components summing to 1.0 (semantic 0.18, evidence 0.14,
  subject 0.12, geographic/temporal/shot-function/rights 0.08,
  duration/resolution 0.07, quality 0.05, continuity 0.03,
  reliability 0.02) plus explicit negative penalties (repetition
  −0.05/use capped −0.25, prior-episode −0.15).
- Explainable decision gates on top of the score: zero subject overlap
  caps at WRONG; verified-rights requirement with unverified media caps
  at WRONG; restricted media caps at WEAK; location mismatch caps at
  WEAK. Every gate is named in the reason string.
- Thresholds: pass ≥ 0.6, weak ≥ 0.4, else wrong; MISSING when no
  candidates. Ordering stable by (−score, asset_id). Provider
  reliability defaults to a uniform constant (no-bias); an explicit
  table is the only way to vary it.
- `attach_scores()` embeds full breakdowns into the storyboard artifact
  for audit; scored boards still validate against `storyboard` schema.

## Tests

| File | Covers |
|---|---|
| `test_editorial_research.py` (17) | success/failure, dedupe, contradictions, confidence cap, cache+resume |
| `test_editorial_script.py` (14) | structure, duration ±10%, grounding, quotes, causal/superlative, filler, uncertainty, schema compat |
| `test_editorial_factcheck.py` (14) | all six verdicts, critical/non-critical blocking, 7 adversarials, no-rewrite, hash pinning |
| `test_editorial_storyboard.py` (7) | gating, coverage, no-AVAILABLE, chart/map, scene_plan adapter |
| `test_editorial_scoring.py` (12) | pass/weak/wrong/missing, rights, duration, duplicates, determinism, no-bias, penalties, audit attach |
| `test_editorial_smoke.py` (1) | realistic research→script→factcheck→storyboard→scoring chain with all artifact schema validations |
| Fixtures | `tests/fixtures/editorial/{sources,facts,claims,questions,blocks}.json` |

Part 6 matrix coverage: research success/failure ✓, duplicate sources ✓,
conflicting evidence ✓, unsupported claims ✓, script duration ✓, missing
evidence ✓, fact-check blocking ✓, storyboard coverage ✓, missing visual
requirement (coverage gap raises; missing availability on blocked claims)
✓, good/bad footage ✓, duplicate footage ✓, insufficient duration ✓,
rights failure ✓.

## Validation

- `mypy lib/editorial/`: clean (8 files).
- Editorial suites: 65 passed.
- Full relevant run (editorial + factory + footage + TTS + narration +
  contracts): 1393 passed, 10 skipped; only failures are 2 pre-existing
  `test_seedance_ark_video.py` contract failures, confirmed present on
  the clean tree before these changes.
- Smoke: full chain runs offline in ~2 s; every emitted artifact
  (evidence_bundle, script, factcheck_report, storyboard, scene_plan)
  validates against its registered schema.

## Changed files

- New: `lib/editorial/{__init__,contracts,hashing,research,script_agent,
  factcheck,storyboard,visual_scoring}.py`
- New: `schemas/artifacts/{evidence_bundle,factcheck_report,
  storyboard}.schema.json`; registered in `schemas/artifacts/__init__.py`
- New tests + fixtures listed above.
- Edited: `tests/test_youtube_documentary_integration.py` only — the
  evidence/factcheck placeholder payloads upgraded to minimal-valid
  shapes now that their schemas are registered (fail-closed checkpoint
  validation applies).

## Out of scope (not implemented)

YouTube upload, Shorts, Analytics agents, UI, autonomous mode. Director
skills (`skills/pipelines/youtube-documentary/*-director.md`) for the new
agents, producer agent, and live retrieval wiring are future work; the
pipeline manifest stage names and artifact contracts already match this
layer's outputs.
