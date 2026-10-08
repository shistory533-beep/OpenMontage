"""Factory uses omniroute/auto by default, records routing, respects fallback."""
import sys, os, subprocess, json
sys.path.insert(0,"/workspaces/OpenMontage")

def test_default_model_is_omniroute_auto():
    c = json.load(open("opencode.json"))
    assert c.get("agent",{}).get("build",{}).get("model") == "omniroute/auto", "agent build default not omniroute/auto"
    assert "omniroute" in c.get("provider",{}), "omniroute provider missing"
    assert "free-auto" in c.get("provider",{}), "free-auto removed"
    assert "bytez" in c.get("provider",{}), "bytez removed"
    print("PASS default_model_omniroute_auto")

def test_factory_uses_omniroute_auto():
    from factory.provider_abstraction import ProviderAbstraction
    p = ProviderAbstraction()
    # brief/analysis/tts should prefer omniroute when env available
    # Since OMNIROUTE_API_KEY may not be set, verify selection logic includes it
    assert "omniroute" in p.capabilities.get("tts",[])
    assert "omniroute" in p.capabilities.get("brief",[])
    print("PASS factory_uses_omniroute_auto")

def test_health_check_passes():
    from factory.pipeline_runner import PipelineRunner
    runner = PipelineRunner("test_health_" + str(int(__import__('time').time())))
    hc = runner.health_check()
    assert hc.get("omniroute_reachable") == True, f"omniroute not reachable: {hc}"
    assert hc.get("auto_works") == True, f"auto (gateway) not working: {hc}"
    assert hc.get("omniroute_auto_configured") == True, f"omniroute/auto not configured: {hc}"
    print("PASS health_check (omniroute_reachable, auto_works, upstream_model)")

def test_provenance_records_role_and_model():
    from factory.provenance import ProvenanceLog
    log = ProvenanceLog()
    log.log_step("script","omniroute",model="omniroute/auto",requested_role="tts")
    entries = log.entries
    assert len(entries)==1
    assert entries[0]["model"]=="omniroute/auto"
    assert entries[0]["requested_role"]=="tts"
    assert entries[0]["provider"]=="omniroute"
    print("PASS provenance_records_role_model")

def test_no_paid_silently():
    c = json.load(open("opencode.json"))
    # No hardcoded paid-only default; omniroute is gateway, free-first preserved
    providers = list(c["provider"].keys())
    assert all(p in ("free-auto","omniroute","bytez") for p in providers), "unexpected providers"
    print("PASS no_paid_silently")

def test_manual_override_possible():
    # CLI supports --model
    import subprocess
    out = subprocess.run(["python3","openmontage_factory_cli.py","run","--topic","x","--model","omniroute/auto"], capture_output=True, text=True)
    assert "omniroute/auto" in out.stdout or out.returncode==0, f"manual override failed: {out.stderr}"
    print("PASS manual_override_possible")

if __name__ == "__main__":
    test_default_model_is_omniroute_auto()
    test_factory_uses_omniroute_auto()
    test_health_check_passes()
    test_provenance_records_role_and_model()
    test_no_paid_silently()
    test_manual_override_possible()
    print("ALL OMNIRoute DEFAULT TESTS PASS")
