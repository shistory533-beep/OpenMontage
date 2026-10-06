"""Live producer E2E: topic -> human_review with real services.

Real Kokoro narration, real Wikimedia footage (strict rights), real
assembly, real audio mix, real render, full QA, review to
READY_FOR_REVIEW + APPROVED. Publishing is NOT performed (out of scope);
the test asserts the publish gate would allow it.

Run deliberately: OPENMONTAGE_ALLOW_NETWORK=1 pytest -m live_api
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_api

from lib.editorial.contracts import Claim, Fact, SourceRecord
from lib.editorial.research import ResearchAgent
from lib.producer.producer import ProducerAgent
from lib.producer.contracts import PRODUCER_STAGES

S1 = "https://www.usgs.gov/yakima-river"
S2 = "https://www.blm.gov/oregon-canyon"

TEXTS = [
    "The Yakima River winds through a basalt canyon carved over ages.",
    "Cliffs of dark stone shelter the water below the open sky.",
]


def _ffmpeg_shim(tmp_path, monkeypatch):
    import shutil

    from imageio_ffmpeg import get_ffmpeg_exe
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    link = bindir / "ffmpeg"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(get_ffmpeg_exe())
    # video_compose's post-render self-review shells out to ffprobe for
    # container validation (no ffprobe => valid_container False => fail).
    # Prefer a system ffprobe; otherwise fetch the static-ffmpeg build
    # (live_api tests already assume network + a real toolchain).
    if shutil.which("ffprobe") is None:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    probe = shutil.which("ffprobe")
    assert probe, "live E2E needs ffprobe on PATH (or static-ffmpeg)"
    plink = bindir / "ffprobe"
    if plink.exists() or plink.is_symlink():
        plink.unlink()
    if Path(probe) != plink:
        plink.symlink_to(probe)
    monkeypatch.setenv("PATH",
                       str(bindir) + os.pathsep + os.environ["PATH"])


def _research_package():
    agent = ResearchAgent("Yakima River canyon", audience="general",
                          target_duration_seconds=30.0)
    agent.ingest_sources([
        SourceRecord(title="Yakima River gauge data", url=S1,
                     publisher="USGS", date="2024-05-01",
                     source_type="government",
                     retrieved_at="2026-01-01T00:00:00+00:00"),
        SourceRecord(title="Canyon geology overview", url=S2,
                     publisher="Bureau of Land Management",
                     date="2023-08-01", source_type="government",
                     retrieved_at="2026-01-01T00:00:00+00:00")])
    agent.add_facts([
        Fact(id="f1",
             statement="The Yakima River flows through a basalt canyon.",
             statement_type="fact", source_ids=[S1, S2],
             subject_key="river canyon"),
        Fact(id="f2",
             statement="Dark cliffs shelter the water below the open sky.",
             statement_type="fact", source_ids=[S1, S2],
             subject_key="cliffs")])
    agent.add_claims([
        Claim(id="c1",
              statement="The Yakima River flows through a basalt canyon.",
              claim_type="factual", fact_ids=["f1"], source_ids=[S1, S2],
              critical=True),
        Claim(id="c2",
              statement="Dark cliffs shelter the water below the open sky.",
              claim_type="factual", fact_ids=["f2"], source_ids=[S1, S2])])
    return agent.build_package()


def _durations():
    from lib.tts_hub.cache import synthesize_cached
    from lib.tts_hub.registry import get_provider
    import tempfile
    prov = get_provider("kokoro")
    tmp = Path(tempfile.mkdtemp())
    out = []
    for i, text in enumerate(TEXTS):
        res = synthesize_cached(prov, text, "af_heart",
                                str(tmp / f"pre_{i}.wav"),
                                cache_dir=tmp / "cache")
        assert res.duration > 0, "real Kokoro narration required"
        out.append(res.duration)
    return out


def test_live_producer_run_to_approved(tmp_path, monkeypatch):
    _ffmpeg_shim(tmp_path, monkeypatch)
    d1, d2 = _durations()
    total = round(d1 + d2 + 1.0, 2)
    mid = round(d1 + 0.5, 2)
    script = {
        "version": "1.0", "title": "Yakima River canyon",
        "total_duration_seconds": total,
        "sections": [
            {"id": "s1", "text": TEXTS[0],
             "start_seconds": 0.0, "end_seconds": mid},
            {"id": "s2", "text": TEXTS[1],
             "start_seconds": mid, "end_seconds": total}],
        "metadata": {"documentary": {
            "beats": ["hook", "payoff"],
            "blocks": [
                {"id": "s1", "chapter_id": "ch1", "beat": "hook",
                 "claim_ids": ["c1"]},
                {"id": "s2", "chapter_id": "ch2", "beat": "payoff",
                 "claim_ids": ["c2"]}],
            "claim_mapping": {"s1": ["c1"], "s2": ["c2"]}}},
    }
    package = _research_package()
    scene_plan = {
        "version": "1.0",
        "scenes": [
            {"id": "slot-1", "type": "broll",
             "description": "aerial river canyon Yakima",
             "start_seconds": 0.0, "end_seconds": mid,
             "script_section_id": "s1"},
            {"id": "slot-2", "type": "broll",
             "description": "basalt cliffs river gorge",
             "start_seconds": mid, "end_seconds": total,
             "script_section_id": "s2"}]}

    from tests.test_youtube_documentary_integration import RESEARCH as _RESEARCH

    research_brief = dict(_RESEARCH)
    research_brief["topic"] = "Yakima River canyon"
    stage_inputs = {
        "brief": {"version": "1.0", "title": "Yakima River canyon",
                  "hook": "A river through basalt.",
                  "key_points": ["river"], "tone": "calm", "style": "doc",
                  "target_platform": "youtube",
                  "target_duration_seconds": total},
        "research_brief": research_brief,
        "evidence_bundle": package.to_dict(),
        "evidence_package": package,
        "script": script,
        "scene_plan": scene_plan,
        "thumbnail_set": {"concept": "river bend at dawn",
                          "source_frame": "slot-1"},
        "human_review": {"decision": "APPROVED", "approver": "e2e-operator",
                         "rationale": "Live E2E: QA passed, footage "
                                      "licensed, narration real.",
                         "video_path": ""},
    }
    approvals = {s: True for s in PRODUCER_STAGES}
    config = {"title": "Yakima River canyon",
              "footage_per_provider": 4,
              "render_runtime": "ffmpeg",
              "rights_mode": "strict"}
    producer = ProducerAgent("ep-live-001", projects_dir=tmp_path,
                             stage_inputs=stage_inputs,
                             approvals=approvals, config=config)
    report = producer.run()
    assert report["failed"] is None, report
    assert report["awaiting_human"] is None, report
    assert report["completed"] == list(PRODUCER_STAGES)

    doc = producer.store.load()
    narration = doc["stages"]["narration"]["artifact"]
    assert narration["tracks"] == 2
    assert narration["provider"] == "kokoro"
    manifest = doc["stages"]["footage"]["artifact"]
    from lib.producer.contracts import manifest_assets
    enriched = manifest_assets(manifest)
    assert len(enriched) == 2
    assert all(a.get("rights_status", "").startswith("verified")
               for a in enriched), enriched
    qa_stage = doc["stages"]["qa"]["artifact"]
    failing = {area: found for area, found in
               (qa_stage.get("metadata", {}).get("qa_issues_by_area")
                or {}).items() if found}
    assert qa_stage["status"] == "pass", failing
    assert qa_stage["metadata"]["qa_verdict"] == "PASS", qa_stage
    assert qa_stage["metadata"]["qa_readiness"] == "READY", qa_stage
    review = doc["stages"]["human_review"]["artifact"]
    assert review["decision"] == "APPROVED"

    # The publish gate would allow it (publish itself stays unexecuted).
    from lib.pipeline_guard import assert_stage_ready
    from lib.pipeline_loader import load_pipeline
    from lib.pipeline_guard import read_checkpoints
    manifest_doc = load_pipeline("youtube-documentary")
    cps = read_checkpoints(producer.checkpoint_dir, "ep-live-001",
                           manifest_doc)
    assert_stage_ready(manifest_doc, "publish", cps)

    # Final MP4 exists with real streams.
    final = tmp_path / "ep-live-001" / "renders" / "final.mp4"
    assert final.exists()
    from lib.producer.qa import probe_streams
    streams = probe_streams(final)
    assert streams.get("readable") is True
    assert "video" in streams.get("streams", [])
    assert "audio" in streams.get("streams", [])
