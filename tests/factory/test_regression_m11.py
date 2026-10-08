"""Regression tests: Piper installed + real model, manifest detection, multi-source footage."""
import sys, os, subprocess
sys.path.insert(0,"/workspaces/OpenMontage")

def test_piper_installed_and_models_present():
    assert os.path.exists("/tmp/piper_dl/en_US-lessac-medium.onnx"), "Piper model .onnx missing"
    assert os.path.exists("/tmp/piper_dl/en_US-lessac-medium.onnx.json"), "Piper config missing"
    assert os.path.exists("/tmp/piper_real.wav") or os.path.exists("/tmp/piper_narration_long.wav"), "Real Piper audio missing"
    # Binary available
    out = subprocess.run(["piper","--help"], capture_output=True)
    assert out.returncode == 0 or b"usage:" in out.stdout or b"usage:" in out.stderr

def test_manifest_detected_by_backlot():
    from backlot.state import load_board_state
    from pathlib import Path
    state = load_board_state(Path("projects/youtube_documentary_real"))
    assert state["pipeline"]["pipeline_type"] == "youtube-documentary"
    assert state["pipeline"]["known"] is True

def test_multi_source_footage():
    assert os.path.exists("projects/youtube_documentary_real/assets/archive_clip.mp4")
    assert os.path.exists("projects/youtube_documentary_real/assets/nasa_clip.mp4")
    assert os.path.getsize("projects/youtube_documentary_real/assets/nasa_clip.mp4") > 100000

def test_final_60s_mp4_audio_video():
    v = "projects/youtube_documentary_real/final_60s_documentary.mp4"
    assert os.path.exists(v)
    p = subprocess.run(["ffprobe","-v","error","-show_entries","stream=codec_name,sample_rate,channels","-of","csv=p=0",v], capture_output=True, text=True)
    out = p.stdout.strip()
    assert "h264" in out
    assert "aac" in out
    # Check duration ~60
    d = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",v], capture_output=True, text=True)
    dur = float(d.stdout.strip())
    assert 55 <= dur <= 65, f"Duration {dur} not ~60s"

if __name__ == "__main__":
    test_piper_installed_and_models_present(); print("PASS piper")
    test_manifest_detected_by_backlot(); print("PASS manifest")
    test_multi_source_footage(); print("PASS multi_footage")
    test_final_60s_mp4_audio_video(); print("PASS final_60s")
    print("ALL REGRESSION PASS")
