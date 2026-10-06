# TTS_HUB_IMPLEMENTATION — OpenMontage TTS Hub

> Local-first narration layer. Kokoro fully implemented; Chatterbox-Turbo
> and Qwen3-TTS ship as honest capability stubs (same interface, explicit
> unavailability, never synthetic audio). No Producer Agent (per scope).

## 1. Files added / changed

| File | Change |
|---|---|
| `lib/tts_hub/contracts.py` | **Added.** `SpeechResult` with all 11 required fields (provider, voice, language, input_text, output_audio_path, sample_rate, channels, duration, alignment, generation_metadata, checksum, status) + JSON round-trip; `WordAlignment`, `TTSStatus` (done/cached/failed). |
| `lib/tts_hub/interface.py` | **Added.** `TTSProvider` Protocol + typed errors: `EmptyTextError`, `InvalidVoiceError`, `UnsupportedLanguageError` (fail fast), `ProviderFailureError` (retryable), `ProviderUnavailableError`, `SilenceRejectedError`. |
| `lib/tts_hub/kokoro_provider.py` | **Added.** `KokoroAdapter`: 11-voice catalog, lazy singleton `KPipeline` (lang `a`), 24 kHz mono WAV via stdlib `wave`, measured duration/energy, chunk-level measured alignment, sha256 checksum. Retry policy: normal attempt, then hermetic offline retry (`_forced_offline` covers HF's import-frozen offline flag) for init AND voice download; silence raises, file kept for debug but never returned usable. |
| `lib/tts_hub/stubs.py` | **Added.** `ChatterboxTurboStub` / `Qwen3TTSStub`: real `voices()` catalogs, `synthesize()` always raises `ProviderUnavailableError` with install path. A stub can never emit audio of any kind. |
| `lib/tts_hub/registry.py` | **Added.** Fixed fallback order kokoro → chatterbox-turbo → qwen3-tts; `capabilities()`; `select_provider()` (raises instead of degrading to silence); `deterministic_voice()` (sha256 of language+hint into sorted catalog). |
| `lib/tts_hub/cache.py` | **Added.** Content-hash cache (`provider\|voice\|language\|text\|options` → WAV + sidecar); hits re-validate bytes and return status `CACHED`; failures never cached. |
| `lib/tts_hub/audio.py` | **Added.** stdlib-only `probe_wav()` (measured sr/channels/duration/peak/mean) + `assert_not_silence()` (peak<0.01 or mean<0.0005 → reject). |
| `lib/tts_hub/mapper.py` | **Added.** Pure mapping onto untouched contracts: `to_manifest_asset` (asset_manifest `narration` + voice_performance receipt), `to_edit_segment` (edit_decisions segment), `to_mixer_track` (role `speech`), `section_timeline`. |
| `tools/audio/tts_hub.py` | **Added.** `TTSHub` BaseTool, capability `tts` (auto-routed by `tts_selector`; replaceable), LOCAL, $0, retry ≤2 on transients only, typed failures return `success=False`. |
| `tests/test_tts_hub.py` (12 tests) | **Added.** Contract fields; 3-provider capabilities; deterministic selection; stub refusal; invalid voice; empty text; unknown provider; test-only silence rejection; cache hit (1 synthesis for 2 requests); REAL Kokoro synthesis (sr/channels/duration/energy/alignment/checksum + independent re-measurement); mapping shapes; tool ops. |
| `tests/contracts/test_phase3_contracts.py` | **Changed (1 line).** Closed tts-provider set gains `"tts_hub"` — the set enumerates all providers, so a new provider must register (same pattern as any future provider). |

## 2. Reused, not changed

`tts_selector` routing, `piper_tts`/`google_tts` fallbacks (declared, untouched),
`audio_mixer` track shape, `edit_decisions`/`asset_manifest`/`script` schemas,
`tests/conftest.py` network guard (real synthesis runs hermetically from cache),
existing production QA (nothing modified to hide failures).

## 3. Real-generation proof (independent verification, fresh process, stdlib only)

Via hub (`select_provider` → kokoro, deterministic voice `af_heart`,
`synthesize_cached`): "Rivers carved the valley over ten thousand years. This
is their story." → `/tmp/opencode/tts_hub_real/narration_s1.wav` (kept out of
git; 229,244 B). Independent check: valid 16-bit WAV, sr=24000, ch=1,
dur=4.78 s, peak=0.3772, mean=0.02659 → **REAL AUDIO** (speech energy ~50×
above silence floor). Cache retry: byte-identical, status `cached`.

## 4. Tests / typecheck

- New: **12/12 pass** (includes the real-synthesis test, ~18 s CPU inference).
- mypy on `lib/tts_hub/` + tool: clean (10 files).
- Full suite (`--ignore=tests/qa`): **1928 passed**, only the **6 pre-existing
  environmental failures** (seedance/ffprobe ×2, hyperframes/npm ×4), same set
  as the pre-change baseline.

## 5. Known risks / follow-ups

1. **Env-only dependencies**: torch/kokoro/scipy/transformers/spacy+`en_core_web_sm`
   installed in this container, NOT added to `requirements.txt` (deliberate:
   avoids burdening existing installs; hub degrades to `UNAVAILABLE` without
   them). A `requirements-tts.txt` or docs entry should formalize this.
2. **misaki OOV fragility**: capitalized out-of-vocabulary words (e.g. "Kokoro")
   crash misaki G2P when the espeak fallback lacks native bindings — surfaced
   as `ProviderFailureError`, never silence, but producers should prefer the
   adapter's error text over retrying identical text. `espeak-ng` system
   package would harden this.
3. **English-only**: Kokoro adapter serves `en`; other languages route to stubs
   (unavailable) — multilingual narration still needs existing cloud providers.
4. **No test-audio in repo**: silence exists only as inline test bytes; no WAV
   fixtures committed; real outputs live in `/tmp/opencode` (approved scratch).
5. **First run needs network** (weights + voice download ~400 MB); thereafter
   fully hermetic via cache + offline retry.
