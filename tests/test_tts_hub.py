"""TTS Hub tests. Real Kokoro synthesis in exactly one test (model cached);
everything else uses a deterministic fake sine-wave provider (real audio,
never silence) or pure validation. Silence bytes are constructed inline
here only, to prove the hub rejects them — production code cannot emit them.
"""
from __future__ import annotations

import math
import struct
import wave

import pytest

SHORT_TEXT = "Hello. This is a real voice test."


def _sine_wav(path, seconds=1.0, freq=220.0, rate=24000, amplitude=0.4):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    frames = struct.pack(f"<{n}h",
                         *[int(amplitude * 32767 * math.sin(2 * math.pi * freq * i / rate))
                           for i in range(n)])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(frames)


class _FakeProvider:
    name = "fake-sine"
    model = "sine-24000-mono"
    sample_rate = 24000
    channels = 1
    calls = 0

    def is_available(self): return True

    def voices(self): return [{"id": "sine", "language": "en"}]

    def synthesize(self, text, voice, out_path, language="en", **options):
        from lib.tts_hub.audio import assert_not_silence, probe_wav
        from lib.tts_hub.contracts import SpeechResult, TTSStatus
        type(self).calls += 1
        if not text.strip():
            from lib.tts_hub.interface import EmptyTextError
            raise EmptyTextError("empty")
        from pathlib import Path
        _sine_wav(Path(out_path))
        info = assert_not_silence(out_path)
        import hashlib
        with open(out_path, "rb") as f:
            checksum = "sha256:" + hashlib.sha256(f.read()).hexdigest()
        return SpeechResult(provider="fake-sine", voice=voice, language=language,
                            input_text=text, output_audio_path=str(out_path),
                            sample_rate=24000, channels=1,
                            duration=info["duration"], alignment=[],
                            generation_metadata={}, checksum=checksum,
                            status=TTSStatus.DONE)


# -- contract ---------------------------------------------------------------

def test_contract_has_all_required_fields():
    from lib.tts_hub.contracts import SpeechResult

    r = SpeechResult(provider="kokoro", voice="af_heart")
    for f in SpeechResult.required_fields():
        assert f in r.to_dict(), f
    assert SpeechResult.from_dict(r.to_dict()).voice == "af_heart"


# -- registry: discovery + deterministic selection ---------------------------

def test_capabilities_list_all_three_providers():
    from lib.tts_hub.registry import capabilities

    caps = {c["name"]: c for c in capabilities()}
    assert set(caps) == {"kokoro", "chatterbox-turbo", "qwen3-tts"}
    assert caps["kokoro"]["available"] is True  # installed in this env
    assert caps["chatterbox-turbo"]["available"] is False  # stub: honest


def test_deterministic_voice_selection_is_stable():
    from lib.tts_hub.registry import deterministic_voice

    a = deterministic_voice("en", "warm")
    assert deterministic_voice("en", "warm") == a
    assert deterministic_voice("en", "deep")  # different hint still resolves


def test_stubs_never_synthesize():
    from lib.tts_hub.interface import ProviderUnavailableError
    from lib.tts_hub.stubs import ChatterboxTurboStub, Qwen3TTSStub

    for stub in (ChatterboxTurboStub(), Qwen3TTSStub()):
        with pytest.raises(ProviderUnavailableError):
            stub.synthesize("hi", "default", "/tmp/x.wav")


# -- fast failures (no inference) --------------------------------------------

def test_invalid_voice_fails_fast():
    from lib.tts_hub.interface import InvalidVoiceError
    from lib.tts_hub.kokoro_provider import KokoroAdapter

    with pytest.raises(InvalidVoiceError):
        KokoroAdapter().synthesize(SHORT_TEXT, "not_a_voice", "/tmp/x.wav")


def test_empty_text_fails_fast():
    from lib.tts_hub.interface import EmptyTextError
    from lib.tts_hub.kokoro_provider import KokoroAdapter

    with pytest.raises(EmptyTextError):
        KokoroAdapter().synthesize("   ", "af_heart", "/tmp/x.wav")


def test_unknown_provider_is_key_error():
    from lib.tts_hub.registry import get_provider

    with pytest.raises(KeyError):
        get_provider("nope")


# -- silence rejection (test-only fixture) ------------------------------------

def test_silence_fixture_rejected(tmp_path):
    from lib.tts_hub.audio import assert_not_silence
    from lib.tts_hub.interface import SilenceRejectedError

    p = tmp_path / "silence.wav"
    _sine_wav(p, amplitude=0.0)  # digital silence, test-only
    with pytest.raises(SilenceRejectedError):
        assert_not_silence(p)


# -- cache hit (fake provider, no inference) -----------------------------------

def test_cache_hit_avoids_second_synthesis(tmp_path):
    from lib.tts_hub.cache import synthesize_cached

    _FakeProvider.calls = 0
    prov = _FakeProvider()
    r1 = synthesize_cached(prov, SHORT_TEXT, "sine", str(tmp_path / "a.wav"),
                           cache_dir=tmp_path / "cache")
    r2 = synthesize_cached(prov, SHORT_TEXT, "sine", str(tmp_path / "b.wav"),
                           cache_dir=tmp_path / "cache")
    assert _FakeProvider.calls == 1
    assert r1.status == "done" and r2.status == "cached"
    assert r1.checksum == r2.checksum


# -- real Kokoro synthesis (one test, model cached) ------------------------------

def test_kokoro_synthesis_is_real_audio(tmp_path, monkeypatch):
    from lib.tts_hub.audio import probe_wav
    from lib.tts_hub.kokoro_provider import KokoroAdapter

    # Weights are cached; force fully-offline init under the no-network guard.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    out = str(tmp_path / "kokoro.wav")
    res = KokoroAdapter().synthesize(SHORT_TEXT, "af_heart", out)
    assert res.status == "done"
    assert res.sample_rate == 24000 and res.channels == 1
    assert res.duration > 1.0
    assert res.checksum.startswith("sha256:") and len(res.checksum) == 71
    assert res.alignment and res.alignment[-1]["end_seconds"] <= res.duration + 0.05
    independent = probe_wav(out)  # independent re-measurement
    assert abs(independent["duration"] - res.duration) < 0.01
    assert independent["peak"] > 0.01 and independent["mean_abs"] > 0.0005


# -- narration/audio mapping onto existing contracts -----------------------------

def test_mapping_shapes_match_existing_contracts(tmp_path):
    from lib.tts_hub import mapper
    from lib.tts_hub.cache import synthesize_cached

    prov = _FakeProvider()
    res = synthesize_cached(prov, SHORT_TEXT, "sine", str(tmp_path / "n.wav"),
                            cache_dir=tmp_path / "cache")
    asset = mapper.to_manifest_asset(res, "narr_s1", "scene_1", "s1")
    assert asset["type"] == "narration"  # asset_manifest enum value
    assert asset["scene_id"] == "scene_1"
    assert asset["voice_performance"]["source_section_id"] == "s1"
    seg = mapper.to_edit_segment(res, "narr_s1", 10.0)
    assert seg["asset_id"] == "narr_s1"  # edit_decisions segment shape
    assert seg["end_seconds"] > seg["start_seconds"] == 10.0
    track = mapper.to_mixer_track(res, 10.0)
    assert track["role"] == "speech"  # audio_mixer track role
    segs, tracks = mapper.section_timeline([(res, "narr_s1", 10.0)])
    assert len(segs) == len(tracks) == 1


# -- tool wrapper ---------------------------------------------------------------

def test_tool_wrapper_ops():
    from tools.audio.tts_hub import TTSHub

    tool = TTSHub()
    assert tool.estimate_cost({}) == 0.0
    assert tool.fallback_tools == ["piper_tts", "google_tts"]
    out = tool.execute({"operation": "capabilities"})
    assert out.success and len(out.data["providers"]) == 3
    out = tool.execute({"operation": "voices", "provider": "kokoro"})
    assert out.success and any(v["id"] == "af_heart" for v in out.data["voices"])
    out = tool.execute({"operation": "synthesize", "text": "   ",
                        "output_path": "/tmp/x.wav"})
    assert out.success is False and "EmptyTextError" in out.error
    out = tool.execute({"operation": "synthesize", "text": SHORT_TEXT,
                        "provider": "chatterbox-turbo",
                        "output_path": "/tmp/x.wav"})
    assert out.success is False  # stub unavailable, explicit failure


# -- hardened contract: model / input_hash / error state ----------------------

def test_contract_exposes_model_and_input_hash():
    from lib.tts_hub.contracts import SpeechResult, input_hash_for

    r = SpeechResult(provider="kokoro", model="kokoro-82m-v1.0",
                     voice="af_heart", input_text=SHORT_TEXT,
                     input_hash=input_hash_for(SHORT_TEXT))
    d = r.to_dict()
    for f in ("provider", "model", "voice", "language", "sample_rate",
              "channels", "duration", "alignment", "output_audio_path",
              "checksum", "input_hash", "generation_metadata", "status"):
        assert f in d, f
    assert d["input_hash"].startswith("sha256:") and len(d["input_hash"]) == 71
    assert d["input_hash"] == input_hash_for("  " + SHORT_TEXT + "  ")  # normalized
    assert SpeechResult.from_dict(d).model == "kokoro-82m-v1.0"
    # old sidecars without the new fields still load (defaults, not crash)
    legacy = {"provider": "kokoro", "voice": "af_heart"}
    assert SpeechResult.from_dict(legacy).model == ""


def test_failed_result_is_error_state_without_audio():
    from lib.tts_hub.contracts import SpeechResult, TTSStatus

    r = SpeechResult.failed("kokoro", "kokoro-82m-v1.0", "af_heart", "en",
                            SHORT_TEXT, "inference crashed")
    assert r.status == TTSStatus.FAILED == "failed"
    assert r.output_audio_path == "" and r.checksum == "" and r.duration == 0.0
    assert r.input_hash.startswith("sha256:")
    assert "inference crashed" in r.generation_metadata["error"]


def test_kokoro_result_carries_model_and_input_hash(tmp_path, monkeypatch):
    from lib.tts_hub.kokoro_provider import KokoroAdapter

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    res = KokoroAdapter().synthesize(SHORT_TEXT, "af_heart",
                                     str(tmp_path / "m.wav"))
    assert res.model == "kokoro-82m-v1.0"
    assert res.input_hash.startswith("sha256:")


def test_capabilities_advertise_model():
    from tools.audio.tts_hub import TTSHub

    out = TTSHub().execute({"operation": "capabilities"})
    models = {p["name"]: p["model"] for p in out.data["providers"]}
    assert models["kokoro"] == "kokoro-82m-v1.0"
    assert models["chatterbox-turbo"] and models["qwen3-tts"]


# -- cache: corruption self-heal + verification ---------------------------------

def test_corrupt_cache_entry_heals_by_resynthesis(tmp_path):
    import json

    from lib.tts_hub.cache import cache_key, synthesize_cached

    _FakeProvider.calls = 0
    prov = _FakeProvider()
    cache = tmp_path / "cache"
    r1 = synthesize_cached(prov, SHORT_TEXT, "sine", str(tmp_path / "a.wav"),
                           cache_dir=cache)
    assert r1.status == "done"
    key = cache_key("fake-sine", "sine", "en", SHORT_TEXT, {})
    blob, sidecar = cache / f"{key}.wav", cache / f"{key}.json"
    assert blob.exists() and sidecar.exists()
    blob.write_bytes(b"not a wav file, corrupted")  # poison the cache
    r2 = synthesize_cached(prov, SHORT_TEXT, "sine", str(tmp_path / "b.wav"),
                           cache_dir=cache)
    assert _FakeProvider.calls == 2  # re-synthesized, not served corrupt
    assert r2.status == "done"
    assert r2.checksum == r1.checksum  # deterministic: same bytes again
    r3 = synthesize_cached(prov, SHORT_TEXT, "sine", str(tmp_path / "c.wav"),
                           cache_dir=cache)
    assert r3.status == "cached" and _FakeProvider.calls == 2


def test_lying_provider_fails_verification(tmp_path):
    from pathlib import Path

    from lib.tts_hub.cache import synthesize_cached
    from lib.tts_hub.contracts import SpeechResult, TTSStatus
    from lib.tts_hub.interface import ProviderFailureError

    class _LyingProvider:
        name = "lying"
        model = "lie-1"
        sample_rate = 24000
        channels = 1

        def is_available(self): return True

        def voices(self): return [{"id": "sine", "language": "en"}]

        def synthesize(self, text, voice, out_path, language="en", **options):
            _sine_wav(Path(out_path))  # real 24kHz mono bytes...
            return SpeechResult(provider="lying", model="lie-1", voice=voice,
                                language=language, input_text=text,
                                output_audio_path=str(out_path),
                                sample_rate=16000, channels=1,  # ...false claim
                                duration=1.0, checksum="sha256:fake",
                                status=TTSStatus.DONE)

    with pytest.raises(ProviderFailureError):
        synthesize_cached(_LyingProvider(), SHORT_TEXT, "sine",
                          str(tmp_path / "l.wav"), cache_dir=tmp_path / "cache")


# -- dry run ---------------------------------------------------------------------

def test_dry_run_plans_without_synthesis(tmp_path):
    from tools.audio.tts_hub import TTSHub

    out_path = str(tmp_path / "planned.wav")
    out = TTSHub().execute({"operation": "dry_run", "text": SHORT_TEXT,
                            "provider": "kokoro", "output_path": out_path})
    assert out.success
    plan = out.data
    assert plan["provider"] == "kokoro"
    assert plan["model"] == "kokoro-82m-v1.0"
    assert plan["voice"]  # deterministically resolved
    assert plan["input_hash"].startswith("sha256:")
    assert plan["cache_key"] and isinstance(plan["cache_hit"], bool)
    assert plan["available"] is True
    import os
    assert not os.path.exists(out_path)  # dry run writes nothing
    again = TTSHub().execute({"operation": "dry_run", "text": SHORT_TEXT,
                              "provider": "kokoro"})
    assert again.data["voice"] == plan["voice"]  # deterministic
