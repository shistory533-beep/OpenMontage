"""Backlot integration + free footage search tests — real sources, no paid keys."""
import sys, os
sys.path.insert(0, "/workspaces/OpenMontage")
from pathlib import Path
from backlot.state import summarize_project, list_projects
from tools.video.stock_sources.archive_org import ArchiveOrgSource
from tools.video.stock_sources.base import SearchFilters

def test_backlot_sees_project():
    p = summarize_project(Path("projects/youtube_documentary_real"))
    assert p["project_id"] == "youtube_documentary_real"
    assert p["render_count"] >= 1
    ids = [x["project_id"] for x in list_projects()]
    assert "youtube_documentary_real" in ids

def test_archive_org_free_search():
    src = ArchiveOrgSource()
    assert src.is_available()
    res = src.search("documentary", filters=SearchFilters(kind="video"))
    assert len(res) > 0
    c = res[0]
    assert c.source == "archive_org"
    assert c.download_url.startswith("http")
    assert c.license and "public" in (c.license or "").lower() or "CC" in c.license

def test_footage_artifact_exists():
    assert os.path.exists("projects/youtube_documentary_real/assets/archive_clip.mp4")
    assert os.path.getsize("projects/youtube_documentary_real/assets/archive_clip.mp4") > 0

def test_final_video_real():
    v = "projects/youtube_documentary_real/final_documentary_30s.mp4"
    assert os.path.exists(v)
    import subprocess
    p = subprocess.run(["ffprobe","-v","error","-show_entries","stream=codec_name","-of","csv=p=0",v], capture_output=True, text=True)
    assert "h264" in p.stdout

if __name__ == "__main__":
    test_backlot_sees_project(); print("PASS backlot")
    test_archive_org_free_search(); print("PASS archive_org")
    test_footage_artifact_exists(); print("PASS footage_artifact")
    test_final_video_real(); print("PASS final_video")
    print("ALL INTEGRATION TESTS PASS")
