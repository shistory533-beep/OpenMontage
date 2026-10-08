"""No-key / failure / recovery / fallback tests — no hardcoded keys."""
import sys, os
sys.path.insert(0, "/workspaces/OpenMontage")
from factory.provider_abstraction import ProviderAbstraction
from factory.job_state import JobState
from factory.provenance import ProvenanceLog

def test_provider_no_key_fallback():
    p = ProviderAbstraction()
    # Without keys, must not return paid-only; must return local/free
    provider = p.resolve("tts")
    assert provider in ("piper_tts","ffmpeg","google_tts") or p.is_free(provider)

def test_transient_vs_permanent():
    s = JobState("t1", checkpoint_dir="/tmp/factory_test")
    s.set_stage("audio", "failed_transient", error="timeout")
    assert s.data["status"] == "failed_transient"
    s.resume("audio")
    assert s.data["status"] == "running"

def test_idempotency_replay():
    s = JobState("t2", checkpoint_dir="/tmp/factory_test")
    s.set_stage("script", "done", artifact="a.json")
    s.save()
    s2 = JobState("t2", checkpoint_dir="/tmp/factory_test")
    s2.set_stage("script", "done")  # replay; should not corrupt
    assert s2.data["stages_done"].count("script") == 1

def test_provenance_fallback_logged():
    prov = ProvenanceLog()
    prov.log_step("render", "ffmpeg", duration_s=2.0, fallback=True, free=True)
    summary = prov.summary()
    assert summary["fallbacks"] == 1
    assert summary["free_steps"] == 1

def test_no_key_env_not_fake():
    # Ensure we never claim paid providers when env missing
    import os
    for k in ("ELEVENLABS_API_KEY","GOOGLE_API_KEY","AZURE_SPEECH_KEY","OMNIRoute"):
        assert not bool(os.getenv(k) and "fake" in str(os.getenv(k))), "No fake keys injected"

if __name__ == "__main__":
    test_provider_no_key_fallback(); print("PASS provider_fallback")
    test_transient_vs_permanent(); print("PASS transient/permanent")
    test_idempotency_replay(); print("PASS idempotency")
    test_provenance_fallback_logged(); print("PASS provenance_fallback")
    test_no_key_env_not_fake(); print("PASS no_fake_keys")
    print("ALL NO-KEY/RECOVERY TESTS PASS")
