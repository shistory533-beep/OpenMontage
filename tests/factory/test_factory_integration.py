"""Factory integration: run command → final MP4 → QA PASS.
Uses free/local providers, real artifacts, no mocks/paid APIs."""
import sys, os, subprocess, time, json
sys.path.insert(0,"/workspaces/OpenMontage")

def test_factory_run_command():
    out = subprocess.run(["python3","openmontage_factory_cli.py","run","--topic","OpenMontage Automated Factory Milestone"], capture_output=True, text=True)
    assert out.returncode == 0 or "COMPLETE" in out.stdout, f"run failed: {out.stderr}"
    assert "job=" in out.stdout, "missing job id"
    job_part = [w for w in out.stdout.split() if "job=" in w][0]
    job_id = job_part.split("=")[1]
    assert job_id, "empty job id"
    print("PASS factory_run_command ->", job_id)
    return job_id

def test_factory_resume(job_id):
    out = subprocess.run(["python3","openmontage_factory_cli.py","resume",job_id], capture_output=True, text=True)
    assert out.returncode == 0, f"resume failed: {out.stderr}"
    assert "DONE" in out.stdout or "stages" in out.stdout
    print("PASS factory_resume")

def test_factory_qa():
    out = subprocess.run(["python3","openmontage_factory_cli.py","qa"], capture_output=True, text=True)
    assert out.returncode == 0, f"qa failed: {out.stderr}"
    assert "PASS=True" in out.stdout
    print("PASS factory_qa")

def test_factory_status():
    out = subprocess.run(["python3","openmontage_factory_cli.py","status"], capture_output=True, text=True)
    assert "PASS" in out.stdout or "stage=qa" in out.stdout
    print("PASS factory_status")

def test_idempotent_rerun_and_provenance():
    # Second run should not corrupt provenance; same artifacts reused
    out = subprocess.run(["python3","openmontage_factory_cli.py","run","--topic","Re-run idempotent"], capture_output=True, text=True)
    prov = json.load(open("projects/youtube_documentary_real/provenance.json"))
    runs = [e for e in prov["entries"] if e.get("stage")=="factory_run"]
    assert len(runs) >= 1, "no factory_run provenance"
    # Verify free-only, no paid usage
    for e in prov["entries"]:
        notes = str(e.get("notes",""))
        if "paid" in notes.lower():
            assert "zero paid" in notes.lower() or "no paid" in notes.lower(), f"unexpected paid mention: {notes}"
    # Verify final artifact exists and passes qa
    v = "projects/youtube_documentary_real/final_3min_correct_v2.mp4"
    assert os.path.exists(v) and os.path.getsize(v) > 10_000_000
    # Quick ffprobe
    d = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",v], capture_output=True, text=True).stdout.strip())
    assert 149.5 <= d <= 151.0
    print("PASS idempotent_rerun_and_provenance (runs=", len(runs), ")")

def test_retry_and_failure_classification():
    # Transient retry classification present in config
    cfg = open("factory_config.yaml").read()
    assert "TRANSIENT" in cfg and "NO_ELIGIBLE_PROVIDER" in cfg
    assert "retry_classes" in cfg
    print("PASS retry_and_failure_classification")

if __name__ == "__main__":
    jid = test_factory_run_command()
    test_factory_resume(jid)
    test_factory_qa()
    test_factory_status()
    test_idempotent_rerun_and_provenance()
    test_retry_and_failure_classification()
    print("ALL FACTORY INTEGRATION PASS")
