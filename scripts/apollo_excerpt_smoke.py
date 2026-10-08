"""Phase 2 excerpt smoke: Apollo 11 TOPIC -> RENDER (2-minute draft).

Real evidence (Wikipedia article + REST summary + NSSDC, retrieved
2026-10-08), real Kokoro narration (pre-synthesized for timings + misaki
canary), real FootageHub footage (strict rights), real assembly + audio +
ffmpeg render. Run: python3 scripts/apollo_excerpt_smoke.py
Halts loudly on fact-check blockers or footage gaps (fail closed).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.chdir(REPO)

S1 = "https://en.wikipedia.org/wiki/Apollo_11"
S2 = "https://en.wikipedia.org/api/rest_v1/page/summary/Apollo_11"
S3 = ("https://nssdc.gsfc.nasa.gov/nmc/spacecraft/"
      "display.action?id=1969-059A")
S4 = ("https://nssdc.gsfc.nasa.gov/nmc/spacecraft/"
      "display.action?id=1969-059C")
S5 = "https://en.wikipedia.org/api/rest_v1/page/summary/Moon_landing"
RETRIEVED = "2026-10-08T00:00:00+00:00"

SECTIONS = [
    ("s1", "In July of nineteen sixty nine, a Saturn Five rocket lifted "
     "three astronauts away from Earth. Their destination was the Moon, "
     "a quarter of a million miles out."),
    ("s2", "The crew were the mission commander, the lunar module pilot, "
     "and the command module pilot waiting in orbit. Their ship was "
     "Columbia. Their landing craft was Eagle."),
    ("s3", "On July twentieth, Eagle dropped toward the Sea of Tranquility. "
     "Alarms sounded in the guidance computer, but flight controllers "
     "called it safe, and Eagle settled into the dust."),
    ("s4", "Hours later the hatch opened. The commander climbed down the "
     "ladder and stepped onto the surface, ahead of his fellow explorer."),
    ("s5", "Minutes later the lunar module pilot joined him. Together they "
     "walked for two and a half hours in the pale dust."),
    ("s6", "They planted a flag, spoke with the president by radio, set out "
     "science instruments, and gathered twenty one and a half kilos of "
     "moon rock."),
    ("s7", "After more than twenty one hours on the surface, Eagle lifted "
     "off to rejoin Columbia. Eight days after launch, the crew splashed "
     "down in the Pacific."),
    ("s8", "Six hundred million people had watched. Apollo Eleven had "
     "culminated the race to the Moon, and Tranquility Base would stand "
     "quiet ever after."),
]

SLOT_DESC = {
    "s1": "saturn rocket launch",
    "s2": "earth moon space",
    "s3": "lunar module descent",
    "s4": "astronaut ladder hatch",
    "s5": "astronaut moonwalk dust",
    "s6": "moon flag science",
    "s7": "ocean splashdown capsule",
    "s8": "mission control celebration",
}

SECTION_CLAIMS = {
    "s1": ["c1", "c2"], "s2": ["c1"], "s3": ["c3"], "s4": ["c4"],
    "s5": ["c4", "c5"], "s6": ["c5"], "s7": ["c6"], "s8": ["c7"],
}

FACTS = [
    ("f1", "Apollo 11 was crewed by a commander, a lunar module pilot, "
     "and a command module pilot.", ["S1", "S2", "S3"]),
    ("f2", "Apollo 11 launched on July 16 1969 aboard a Saturn V rocket "
     "from Launch Complex 39A.", ["S1"]),
    ("f3", "The lunar module Eagle landed in the Sea of Tranquility on "
     "July 20 1969.", ["S1", "S3", "S4"]),
    ("f4", "The commander stepped onto the lunar surface first, and the "
     "lunar module pilot followed minutes later.", ["S1"]),
    ("f5", "The two surface walkers spent about 2.5 hours outside, planted "
     "a flag, spoke with the president by radio, deployed science "
     "instruments, and collected 21.5 kilos of lunar material.", ["S1"]),
    ("f6", "After more than 21 hours on the surface the crew returned to "
     "orbit and splashed down in the Pacific Ocean on July 24 1969, where "
     "the recovery ship Hornet waited.", ["S1"]),
    ("f7", "An estimated 600 million people watched, and Apollo 11 "
     "culminated the Space Race.", ["S1"]),
]

CLAIMS = [
    ("c1", "factual", "Apollo 11 was crewed by a commander, a lunar module "
     "pilot, and a command module pilot.", ["f1"], ["S1", "S2", "S3"],
     False),
    ("c2", "factual", "Apollo 11 launched on July 16 1969 aboard a Saturn V "
     "rocket from Launch Complex 39A.", ["f2"], ["S1"], True),
    ("c3", "factual", "The lunar module Eagle landed in the Sea of "
     "Tranquility on July 20 1969.", ["f3"], ["S1", "S3", "S4"], True),
    ("c4", "factual", "The commander stepped onto the lunar surface first, "
     "and the lunar module pilot followed minutes later.", ["f4"], ["S1"],
     True),
    ("c5", "factual", "The two surface walkers spent about 2.5 hours "
     "outside, planted a flag, spoke with the president by radio, deployed "
     "science instruments, and collected 21.5 kilos of lunar material.",
     ["f5"], ["S1"], True),
    ("c6", "factual", "After more than 21 hours on the surface the crew "
     "returned to orbit and splashed down in the Pacific Ocean on July 24 "
     "1969, where the recovery ship Hornet waited.", ["f6"], ["S1"], True),
    ("c7", "factual", "An estimated 600 million people watched, and "
     "Apollo 11 culminated the Space Race.", ["f7"], ["S1"], False),
]


def _ffmpeg_shim() -> None:
    from imageio_ffmpeg import get_ffmpeg_exe
    bindir = Path(tempfile.mkdtemp(prefix="apollo-ffmpeg-"))
    link = bindir / "ffmpeg"
    link.symlink_to(get_ffmpeg_exe())
    if shutil.which("ffprobe") is None:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    probe = shutil.which("ffprobe")
    assert probe, "need ffprobe (static-ffmpeg fallback failed)"
    plink = bindir / "ffprobe"
    if Path(probe) != plink:
        plink.symlink_to(probe)
    os.environ["PATH"] = str(bindir) + os.pathsep + os.environ["PATH"]


def main() -> int:
    _ffmpeg_shim()
    from lib.editorial.contracts import Claim, Fact, SourceRecord
    from lib.editorial.research import ResearchAgent
    from lib.producer.contracts import PRODUCER_STAGES
    from lib.producer.producer import ProducerAgent

    # -- evidence: real fetched sources ---------------------------------
    agent = ResearchAgent("Apollo 11 Moon landing", audience="general",
                          target_duration_seconds=120.0)
    agent.ingest_sources([
        SourceRecord(title="Apollo 11 (Wikipedia article)",
                     url=S1, publisher="Wikipedia",
                     date="2026-10-08", source_type="other_secondary",
                     retrieved_at=RETRIEVED),
        SourceRecord(title="Apollo 11 summary (Wikipedia REST)",
                     url=S2, publisher="Wikipedia",
                     date="2026-10-08", source_type="other_secondary",
                     retrieved_at=RETRIEVED),
        SourceRecord(title="Apollo 11 CSM (NSSDC)", url=S3,
                     publisher="NASA NSSDC", date="2026-10-07",
                     source_type="government",
                     retrieved_at=RETRIEVED),
        SourceRecord(title="Apollo 11 LM Eagle (NSSDC)", url=S4,
                     publisher="NASA NSSDC", date="2026-10-07",
                     source_type="government",
                     retrieved_at=RETRIEVED),
        SourceRecord(title="Moon landing (Wikipedia REST)", url=S5,
                     publisher="Wikipedia", date="2026-10-08",
                     source_type="other_secondary",
                     retrieved_at=RETRIEVED),
    ])
    urlkey = {"S1": S1, "S2": S2, "S3": S3, "S4": S4, "S5": S5}
    agent.add_facts([
        Fact(id=fid, statement=st, statement_type="fact",
             source_ids=[urlkey[k] for k in keys],
             subject_key="apollo 11", confidence=0.95)
        for fid, st, keys in FACTS])
    agent.add_claims([
        Claim(id=cid, statement=st, claim_type=ct, fact_ids=fids,
              source_ids=[urlkey[k] for k in keys], critical=crit)
        for cid, ct, st, fids, keys, crit in CLAIMS])
    package = agent.build_package()

    # -- narration timings ----------------------------------------------
    # Cheap dry-run path: estimated timings, fully offline (no TTS, no
    # network). Schema/contract shape is identical; values are estimates,
    # labeled as such. The real path below uses measured Kokoro audio.
    if "--dry-run" in sys.argv:
        durations = [max(1.0, round(len(text.split()) / 3.0, 2))
                     for _, text in SECTIONS]
        timing_source = "estimated-dry-run"
    else:
        # REAL Kokoro timings (also the misaki canary). Persistent
        # content-keyed cache (re-validated on hit) so repeat runs and the
        # producer narration stage reuse verified audio instead of
        # re-synthesizing. speed=1.0 matches the TTSHub tool default so the
        # canary warms the exact cache keys the producer will read.
        from lib.tts_hub.cache import default_cache_dir, synthesize_cached
        from lib.tts_hub.registry import get_provider
        prov = get_provider("kokoro")
        predir = Path(tempfile.mkdtemp(prefix="apollo-pre-"))
        durations = []
        for sid, text in SECTIONS:
            try:
                res = synthesize_cached(
                    prov, text, "af_heart", str(predir / f"{sid}.wav"),
                    cache_dir=default_cache_dir(), speed=1.0)
            except Exception as exc:
                print(f"TTS CANARY FAILED on {sid}: "
                      f"{type(exc).__name__}: {exc}", flush=True)
                return 2
            assert res.duration > 0, f"silence/empty for {sid}"
            durations.append(res.duration)
            print(f"canary {sid}: {res.duration:.1f}s "
                  f"({res.generation_metadata.get('cache', '?')})",
                  flush=True)
        timing_source = "kokoro-af_heart"
    total = round(sum(durations) + 0.5 * len(durations), 2)

    sections, blocks, cursor = [], [], 0.0
    for (sid, text), dur in zip(SECTIONS, durations):
        end = round(cursor + dur + 0.5, 2)
        sections.append({"id": sid, "text": text,
                         "start_seconds": round(cursor, 2),
                         "end_seconds": end})
        blocks.append({"id": sid, "chapter_id": f"ch-{sid}",
                       "beat": "hook" if sid == "s1" else (
                           "payoff" if sid == "s8" else "rising"),
                       "claim_ids": SECTION_CLAIMS[sid]})
        cursor = end
    script = {
        "version": "1.0", "title": "Apollo 11 excerpt",
        "total_duration_seconds": round(cursor, 2), "sections": sections,
        "metadata": {"documentary": {
            "beats": ["hook", "rising", "payoff"], "blocks": blocks,
            "claim_mapping": dict(SECTION_CLAIMS)},
            "timing_source": timing_source}}
    scene_plan = {"version": "1.0", "scenes": [
        {"id": f"slot-{sid}", "type": "broll",
         "description": SLOT_DESC[sid],
         "start_seconds": s["start_seconds"], "end_seconds": s["end_seconds"],
         "script_section_id": sid}
        for sid, s in zip([x[0] for x in SECTIONS], sections)]}

    research_brief = {
        "version": "1.0", "topic": "Apollo 11 Moon landing",
        "research_date": "2026-10-08",
        "landscape": {"existing_content": [
            {"title": "Apollo 11 (2019, Todd Douglas Miller)",
             "source": "theatrical",
             "angle": "all-archival 70mm immersion",
             "what_it_covers": "launch to splashdown from restored footage",
             "what_it_misses": "engineering decision detail (1202 alarms)",
             "engagement_signal": "wide 2019 theatrical release"},
            {"title": "Chasing the Moon (2019, PBS American Experience)",
             "source": "broadcast",
             "angle": "three-part political and human history",
             "what_it_covers": "space race context, crew, mission control",
             "what_it_misses": "surface-science granularity",
             "engagement_signal": "flagship PBS anniversary slot"},
            {"title": "For All Mankind (1989, Al Reinert)",
             "source": "theatrical",
             "angle": "astronaut-voiceover meditation",
             "what_it_covers": "Apollo program arc through crew voices",
             "what_it_misses": "Apollo 11 specific deep dive",
             "engagement_signal": "criterion-catalogue classic"}],
            "saturated_angles": ["one small step quote montages"],
            "underserved_gaps": ["1202 alarm engineering decision"]},
        "data_points": [
            {"claim": "Eagle landed July 20 1969, Sea of Tranquility",
             "source_url": S1, "credibility": "secondary_source"},
            {"claim": "21.5 kilos of lunar material collected",
             "source_url": S1, "credibility": "secondary_source"},
            {"claim": "600 million viewers; July 24 Pacific splashdown",
             "source_url": S1, "credibility": "secondary_source"}],
        "audience_insights": {"common_questions": [
            "who flew Apollo 11", "what did they bring back",
            "did they leave anything on the Moon"],
            "misconceptions": [], "knowledge_level": "general"},
        "angles_discovered": [
            {"name": "engineering under alarm", "hook": "the 1202 call",
             "type": "evergreen",
             "why_now": "autonomy-era parallels to onboard judgment calls",
             "grounded_in": [
                 "Eagle landed July 20 1969, Sea of Tranquility"]},
            {"name": "two hours that changed exploration",
             "hook": "a full field program in one moonwalk",
             "type": "evergreen",
             "why_now": "Artemis surface-science planning reuses the playbook",
             "grounded_in": [
                 "21.5 kilos of lunar material collected"]},
            {"name": "six hundred million witnesses",
             "hook": "the broadcast as shared memory",
             "type": "evergreen",
             "why_now": "moon-base era audiences rewatch the origin",
             "grounded_in": [
                 "600 million viewers; July 24 Pacific splashdown",
                 "who flew Apollo 11"]}],
        "sources": [
            {"url": S1, "title": "Apollo 11 (Wikipedia)",
             "used_for": "mission facts", "reliability": "secondary"},
            {"url": S2, "title": "Apollo 11 summary",
             "used_for": "crew facts", "reliability": "secondary"},
            {"url": S3, "title": "Apollo 11 CSM (NSSDC)",
             "used_for": "landing facts", "reliability": "primary"},
            {"url": S4, "title": "Apollo 11 LM Eagle (NSSDC)",
             "used_for": "lander facts", "reliability": "primary"},
            {"url": S5, "title": "Moon landing overview",
             "used_for": "program context", "reliability": "secondary"}]}

    stage_inputs = {
        "brief": {"version": "1.0", "title": "Apollo 11 excerpt",
                  "hook": "Eight days to the Moon and back.",
                  "key_points": ["crew", "landing", "return"],
                  "tone": "documentary", "style": "archival",
                  "target_platform": "youtube",
                  "target_duration_seconds": round(cursor, 2)},
        "research_brief": research_brief,
        "evidence_bundle": package.to_dict(),
        "evidence_package": package,
        "script": script,
        "scene_plan": scene_plan,
    }
    config = {"title": "Apollo 11 excerpt",
              "footage_per_provider": 2,
              "render_runtime": "ffmpeg",
              "tts_provider": "kokoro",
              # Pinned to the canary voice so producer narration reads the
              # exact persistent-cache keys the canary warmed (af_heart,
              # en, speed 1.0). Deterministic, not a fallback.
              "tts_voice": "af_heart",
              "rights_mode": "strict"}
    if "--dry-run" in sys.argv:
        from schemas.artifacts import validate_artifact
        validate_artifact("brief", stage_inputs["brief"])
        validate_artifact("research_brief", stage_inputs["research_brief"])
        validate_artifact("evidence_bundle",
                          stage_inputs["evidence_bundle"])
        validate_artifact("script", stage_inputs["script"])
        validate_artifact("scene_plan", stage_inputs["scene_plan"])
        print(f"DRY-RUN OK: script {script['total_duration_seconds']}s, "
              f"{len(sections)} sections, {len(scene_plan['scenes'])} slots",
              flush=True)
        return 0
    producer = ProducerAgent(
        "apollo-excerpt-001", projects_dir=REPO / "projects",
        stage_inputs=stage_inputs,
        approvals={s: True for s in PRODUCER_STAGES},
        # Extended via APOLLO_STOP_AFTER (default "render") so QA/packaging
        # can run against the same real artifacts. human_review is never
        # auto-reached: it needs an explicit human decision payload.
        stop_after=os.environ.get("APOLLO_STOP_AFTER", "render"),
        config=config)
    report = producer.run()
    print("REPORT:", report, flush=True)
    assert report["failed"] is None, report
    assert report["awaiting_human"] in (None, "human_review"), report

    doc = producer.store.load()
    ed = doc["stages"]["timeline"]["artifact"]
    assert ed.get("cuts"), "timeline has no cuts"
    final = REPO / "projects" / "apollo-excerpt-001" / "renders" / "final.mp4"
    assert final.exists(), "render MP4 missing"
    from lib.producer.qa import probe_streams
    streams = probe_streams(final)
    assert streams.get("readable") is True, streams
    assert "video" in streams.get("streams", []), streams
    assert "audio" in streams.get("streams", []), streams
    if "qa" in report.get("completed", []):
        # Independent QA verdict on the real render: must actually pass.
        # The qa artifact IS the canonical final_review (status/checks at
        # top level). READY_FOR_REVIEW is NOT claimed here — that needs a
        # recorded human decision, which no smoke may invent.
        final_review = doc["stages"]["qa"]["artifact"] or {}
        assert final_review.get("status") == "pass", final_review
        print(f"QA PASS: status={final_review.get('status')}", flush=True)
    print(f"EXCERPT OK: {len(ed['cuts'])} cuts, "
          f"{script['total_duration_seconds']}s script, MP4 verified",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
