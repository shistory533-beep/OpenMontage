# FOOTAGE_HUB_IMPLEMENTATION — OpenMontage FootageHub

> Additive provider layer only. No existing Vault/Retrieval file modified
> (one additive block appended to `.env.example` documents the optional key).

## 1. What was added

| File | Role |
|---|---|
| `tools/video/stock_sources/openverse.py` | New `OpenverseSource` (StockSource protocol). Free anonymous access → `is_available()` True, no key. `kind="image"` searches `/v1/images/`; `kind="video"` returns `[]` honestly (Openverse has no video catalog) and reports it via `supports`. License slug preserved per record. |
| `tools/video/stock_sources/dvids.py` | New `DvidsSource` (StockSource protocol). Free-key path: `is_available()` = `DVIDS_API_KEY` present, else skipped — never mandatory. Records without a direct file URL fail per-candidate at download, never the pipeline. |
| `lib/footage_hub/contracts.py` | `NormalizedAsset` (all 16 required fields: provider, source_id, title, source_url, download_url, duration, width, height, fps, format, creator, license, rights_status, attribution, retrieved_at, checksum — plus kind/local_path/extra) with JSON round-trip; `ProviderCapability`. Extends `Candidate`, does not duplicate it. |
| `lib/footage_hub/rights.py` | `classify()` (license string → RightsStatus) + `validate(asset, require_verified)` → `(ok, reason)` verdicts, never exceptions. Verified policy rejects `unknown`/`restricted`; provenance strings kept verbatim. No generative path exists in this module. |
| `lib/footage_hub/registry.py` | Wraps existing `stock_sources` discovery (`all_sources`/`get_source`). `capabilities()` advertises all 8 factory providers (archive_org, wikimedia, nasa, openverse, loc, dvids, pexels, pixabay_video) + any extra installed adapter. Broken `is_available()` degrades to unavailable, not a crash. |
| `lib/footage_hub/hub.py` | `search()` (fan-out, per-provider try/except → `ProviderFailure`, rights filter, deterministic `rank_assets`: token-overlap → resolution → provider → source_id), `DownloadManager` (sha256 content-address `blobs/`, checksum index with alias list, per-alias manifest rows, ClipCache ingest best-effort), `manifest_rows()` audit reader. |
| `tools/video/footage_hub.py` | Thin `FootageHub` BaseTool (`capability="clip_acquisition"`, DETERMINISTIC, HYBRID, $0, `fallback_tools=[direct_clip_search, corpus_builder]`): ops `capabilities` / `search` / `download`. `supports.generative_fallback=False` by contract. |
| `tests/test_footage_hub.py` (12 tests) + `tests/fixtures/footage_hub/` (openverse_images, dvids_search, provider_failure, rights_matrix JSON) | Success + failure fixtures; offline (monkeypatched transport). |
| `.env.example` (+4 lines) | Documents optional `OPENVERSE_API_KEY` / `DVIDS_API_KEY`. |

## 2. What was reused (not redesigned)

- **Adapter protocol**: `StockSource`/`Candidate`/`SearchFilters` (`stock_sources/base.py`) unchanged; new adapters live in the same package so `pkgutil` auto-discovery, `corpus_builder` fan-out, and preflight see Openverse/DVIDS with zero edits (verified: 18 sources discovered, up from 16).
- **Footage Vault**: `ClipCache.ingest()` for byte-level reuse; vault manifest is a sidecar (`footage_hub_manifest.jsonl`) — corpus `index.jsonl`/embeddings remain `corpus_builder`'s exclusive write path.
- **Retrieval/rerank**: hub ranking is a deterministic pre-rank only; semantic rerank stays `Corpus.rank_by_text` / `clip_search` (untouched, tests green).
- **Registry/tool contract**: `BaseTool` + `tool_registry.discover()` — `footage_hub` appears as `clip_acquisition` with no registration edit.

## 3. Requirement coverage

- Provenance/license preserved: `Candidate` → `NormalizedAsset` copies verbatim; manifest rows keep provider/license/creator/source_url per alias.
- Unknown rights rejected under verified policy: `validate(require_verified=True)` → `(False, reason)`; covered by rights-matrix fixture test.
- Checksum content-address + dedupe: `sha256:<hex>` blob store; identical bytes from pexels+pixabay collapse to one blob, two provenance rows (tested).
- No AI substitution: no generation imports/capability in hub or adapters (asserted by `test_no_generative_fallback_anywhere`); download failure raises, manifest stays empty (tested).
- Capabilities exposed: `capabilities` op + `ProviderCapability` (tested for all 8).
- Failure isolation: per-provider try/except in `search()`; all-fail returns failures list, not an exception (fixture-driven test).
- Deterministic ranking: pure sort key, input-order independent (tested incl. reversed input).
- Vault integration: ClipCache ingest + manifest sidecar; corpus-builder/corpus tests unaffected.

## 4. Test + typecheck results

- New: **12/12 pass** (`tests/test_footage_hub.py`).
- Related: factory-state (17), clip_cache, corpus-builder-failure, documentary-governance — **67/67 pass** combined.
- Full suite (`--ignore=tests/qa`): **1896 passed**, 24 skipped, 3 xfailed; **6 failed — all pre-existing/environmental**, reproduced on the clean tree via `git stash -u` in the prior task's run and unchanged here (2× `test_seedance_ark_video` expect ffprobe-present strings, absent in this container; 4× `test_hyperframes_compose` assume npm runtime).
- mypy on all 7 new Python files: **clean** (single reported error is pre-existing `tools/base_tool.py:252` method-assign instrumentation, untouched).
- One defect caught during development: `validate()` preferred the dataclass default `rights_status="unknown"` over license classification — fixed so `unknown`/empty status falls through to `classify(license)`.

## 5. Remaining risks

1. **Openverse has no video** — video-kind searches rely on the other 7 providers; the hub reports this honestly but factory recall for CC-image-needy topics should prefer image-kind explicitly.
2. **DVIDS schema drift** — DVIDS v2 responses parsed defensively (`.get` chains, `None` on unparseable); a breaking API change degrades to per-provider failure, but monitor fixture freshness.
3. **License strings are advisory** — `classify()` is heuristic over provider text (e.g. Wikimedia "verify per-file" → unknown → rejected under verified policy, which is safe but conservative; per-file review UI is future work).
4. **No embedding rerank in hub** — by design; semantic quality still depends on downstream `corpus_builder` + `clip_search`.
5. **Checksum index is per-vault** (no cross-vault/global checksum DB); ClipCache provides the cross-project byte sharing instead.
