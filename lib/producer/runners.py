"""Default stage runners: thin coordination over existing services.

Content stages (topic/research/evidence/script/storyboard/thumbnail)
record caller-supplied payloads — authorship stays with the directing
agent, the Producer only persists and checkpoints. Mechanical stages
run the real service named in the manifest:

- narration            -> TTS Hub, one asset per script section
- footage              -> FootageHub search + VisualScorer picks + download
- footage_intelligence -> per-asset verdicts (pass/weak/wrong/missing)
- editorial            -> lib.producer.assembly Timeline IR
- timeline             -> re-validation + re-time (no replacement)
- audio                -> audio_mixer full_mix via audio_build plan
- render               -> video_compose
- qa                   -> lib.producer.qa
- packaging            -> lib.producer.packaging
- human_review         -> supplied review decision via lib.producer.review
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.producer.producer import (
    MissingStageInput,
    StageContext,
    StageHandler,
)


def build(producer: Any) -> dict[str, StageHandler]:
    """Bind default handlers to one ProducerAgent instance."""
    cfg = producer.config
    supplied = producer.stage_inputs

    def _supplied(stage: str, artifact: str) -> StageHandler:
        def run(ctx: StageContext) -> dict[str, Any]:
            payload = supplied.get(stage)
            if payload is None:
                supplied_flat = supplied.get(artifact)
                payload = supplied_flat
            if payload is None:
                raise MissingStageInput(
                    f"Stage {stage!r} needs a supplied payload "
                    f"(stage_inputs[{stage!r}] or [{artifact!r}]). The "
                    f"Producer records content, it never authors it.")
            if not isinstance(payload, dict):
                raise MissingStageInput(
                    f"Stage {stage!r} payload must be a dict.")
            return {artifact: payload}
        return run

    handlers: dict[str, StageHandler] = {
        "topic": _supplied("topic", "brief"),
        "research": _supplied("research", "research_brief"),
        "evidence": _supplied("evidence", "evidence_bundle"),
        "script": _supplied("script", "script"),
        "storyboard": _supplied("storyboard", "scene_plan"),
        "thumbnail": _supplied("thumbnail", "thumbnail_set"),
        "narration": lambda ctx: run_narration(ctx, cfg),
        "footage": lambda ctx: run_footage(ctx, cfg),
        "footage_intelligence": lambda ctx: run_footage_intelligence(ctx,
                                                                     cfg),
        "editorial": lambda ctx: run_editorial(ctx, cfg),
        "timeline": lambda ctx: run_timeline(ctx, cfg),
        "audio": lambda ctx: run_audio(ctx, cfg),
        "render": lambda ctx: run_render(ctx, cfg),
        "qa": lambda ctx: run_qa(ctx, cfg),
        "packaging": lambda ctx: run_packaging(ctx, cfg),
        "human_review": lambda ctx: run_human_review(ctx, cfg, supplied),
    }
    # fact_check must verify, not just record: gate on the real agent.
    handlers["fact_check"] = lambda ctx: run_fact_check(ctx, cfg, supplied)
    return handlers


def run_narration(ctx: StageContext, cfg: dict[str, Any]) -> dict[str, Any]:
    """Synthesize one narration asset per script section via TTS Hub.

    Error taxonomy (L5/L6): only transient ProviderFailureError is
    retryable (re-run the stage). Deterministic errors — unknown voice,
    empty text, unsupported language, silence rejection, missing
    path/config — fail fast with a clear cause and are never retried
    blindly. Silence is never a fallback (fail closed).
    """
    from tools.audio.tts_hub import TTSHub

    script = ctx.inputs.get("script") or {}
    sections = script.get("sections") or []
    if not sections:
        raise MissingStageInput(
            "Narration needs script.sections (one asset per section).")
    voice = cfg.get("tts_voice")
    provider = cfg.get("tts_provider", "kokoro")
    if not provider or not isinstance(provider, str):
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(
            "Narration misconfigured: tts_provider must be a non-empty "
            "string (deterministic config error, not retried).")
    audio_dir = ctx.workdir / "assets" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    tool = TTSHub()
    tracks = []
    for i, section in enumerate(sections):
        text = (section.get("text") or "").strip()
        if not text:
            raise MissingStageInput(
                f"Script section {section.get('id', i)!r} has empty text: "
                f"refusing to pad narration with silence.")
        out_path = audio_dir / f"narration_{section.get('id', i)}.wav"
        params: dict[str, Any] = {"operation": "synthesize", "text": text,
                                  "provider": provider,
                                  "output_path": str(out_path)}
        if voice:
            params["voice"] = voice
        if cfg.get("tts_language"):
            params["language"] = cfg["tts_language"]
        try:
            result = tool.execute(params)
        except Exception as exc:
            from lib.producer.producer import CriticalStageError
            raise CriticalStageError(
                f"Narration synthesis crashed for section "
                f"{section.get('id', i)!r}: {type(exc).__name__}: {exc} "
                f"(transient backend failures may retry; deterministic "
                f"voice/text/config errors must be fixed, not retried).") from exc
        if not result.success:
            from lib.producer.producer import CriticalStageError
            err = str(result.error or "")
            lower = err.lower()
            if any(marker in lower for marker in (
                    "unknown voice", "invalid voice", "empty text",
                    "unsupported language", "silence rejected", "silence")):
                raise CriticalStageError(
                    f"Narration synthesis refused for section "
                    f"{section.get('id', i)!r}: {result.error} "
                    f"(deterministic: fix voice/text/config, do not retry).")
            raise CriticalStageError(
                f"Narration synthesis failed for section "
                f"{section.get('id', i)!r}: {result.error} "
                f"(transient backend failure: retry the stage).")
        data = result.data.get("result", {}) if result.data else {}
        tracks.append({"section_id": section.get("id"),
                       "asset_id": f"narr_{section.get('id', i)}",
                       "path": str(out_path),
                       "duration_seconds": data.get("duration", 0.0),
                       "checksum": data.get("checksum", ""),
                       "voice": data.get("voice", voice or ""),
                       "provider": data.get("provider", provider),
                       "source_tool": f"tts_hub:{data.get('provider',
                                                           provider)}",
                       # Synthesis record: what the engine reported speaking.
                       # render turns this into the narration_transcript for
                       # video_compose's transcript-vs-script check.
                       "text": text,
                       "alignment": data.get("alignment", [])})
    for track in tracks:
        if not track["duration_seconds"] or not track["checksum"]:
            from lib.producer.producer import CriticalStageError
            raise CriticalStageError(
                f"Narration asset {track['asset_id']!r} has no verified "
                f"audio (refusing silent placeholder).")
    manifest = {"version": "1.0", "tracks": len(tracks),
                "sections": tracks,
                "voice": tracks[0]["voice"] if tracks else voice,
                "provider": provider}
    try:
        from schemas.artifacts import validate_artifact
        validate_artifact("narration_manifest", manifest)
    except Exception as exc:
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(
            f"Narration manifest invalid: {exc}") from exc
    return {"narration_manifest": manifest}


def run_footage(ctx: StageContext, cfg: dict[str, Any]) -> dict[str, Any]:
    """Acquire one rights-tracked clip per storyboard requirement."""
    from lib.editorial.visual_scoring import VisualScorer
    from lib.footage_hub import hub as footage_hub
    from lib.footage_hub.registry import get_adapter

    requirements = _requirements_from(ctx)
    if not requirements:
        raise MissingStageInput(
            "Footage needs storyboard requirements (stage_inputs "
            "['footage_requirements'] or scene_plan slots with queries).")
    vault = ctx.workdir / "assets" / "video"
    vault.mkdir(parents=True, exist_ok=True)
    mgr = footage_hub.DownloadManager(vault)
    scorer = VisualScorer()
    assets: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {}
    visual: dict[str, Any] = {}
    gaps = []
    for req in requirements:
        query = " ".join(req.get("positive_search_terms", [])
                         or [req.get("subject", "")]).strip()
        try:
            found = footage_hub.search(
                query, kind=req.get("preferred_media_type", "video"),
                per_provider=int(cfg.get("footage_per_provider", 3)),
                rights_mode="strict")
        except Exception as exc:
            gaps.append({"requirement_id": req.get("id"),
                         "reason": f"search failed: {exc}"})
            continue
        cands = []
        for a in found.assets:
            d = (a.to_dict() if hasattr(a, "to_dict") else dict(a))  # type: ignore[call-overload]
            d["asset_id"] = (d.get("asset_id") or d.get("id")
                             or f"{d.get('provider', '')}_"
                                f"{d.get('source_id', '')}")
            cands.append(d)
        board = scorer.score_requirement(req, cands)
        if board["decision"] == "missing" or not board["scores"]:
            gaps.append({"requirement_id": req.get("id"),
                         "reason": "no candidates retrieved"})
            continue
        best = board["scores"][0]
        if best["decision"] not in ("pass", "weak"):
            gaps.append({"requirement_id": req.get("id"),
                         "reason": f"best pick scored "
                                   f"{best['decision']}; no fillers used"})
            continue
        asset = next(a for a in cands
                     if (a.get("asset_id") or a.get("id"))
                     == best["asset_id"])
        try:
            adapter = get_adapter(asset.get("provider", ""))
            from lib.footage_hub.contracts import NormalizedAsset
            dl_asset, _ = mgr.download(NormalizedAsset.from_dict(asset),
                                       adapter)
            record = dl_asset.to_dict()
        except Exception as exc:
            gaps.append({"requirement_id": req.get("id"),
                         "reason": f"download failed: {exc}"})
            continue
        aid = (record.get("asset_id") or asset.get("asset_id")
               or f"{record.get('provider', '')}_"
                  f"{record.get('source_id', '')}")
        record["asset_id"] = aid
        # Vault-relative blob paths ("blobs/<sha>.webm") are only
        # resolvable against the vault dir. Production artifacts must
        # carry absolute paths so render/QA resolve them regardless of
        # the caller's CWD (the manifest schema does not enforce
        # relativity, so absolute is schema-legal).
        blob = record.get("local_path", "")
        if blob and not Path(blob).is_absolute():
            record["local_path"] = str(vault / blob)
        # Canonical asset_manifest closes asset items, so the item stays
        # schema-pure (id/type/path/source_tool/scene_id + declared
        # provenance fields) while the full FootageHub record + visual
        # pick ride in open metadata.provenance / metadata.visual.
        # Downstream readers merge them back via manifest_assets().
        item = {
            "id": aid,
            "type": record.get("kind", "video"),
            "path": record.get("local_path", ""),
            "source_tool": (
                f"footage_hub:{record.get('provider', 'unknown')}"),
            "scene_id": req.get("id", ""),
            "provider": record.get("provider", ""),
            "license": record.get("license", ""),
            "original_url": record.get("source_url", ""),
            "duration_seconds": float(record.get("duration") or 0.0),
            "resolution": (f"{record.get('width', 0)}x"
                           f"{record.get('height', 0)}"),
            "format": record.get("format", ""),
            "quality_score": float(best["final_score"]),
            "subtype": "stock",
            "generation_summary": (
                f"requirement {req.get('id')}: visual "
                f"{best['decision']} ({best.get('reason', '')})"),
        }
        assets.append(item)
        provenance[aid] = record
        visual[aid] = {"requirement_id": req.get("id"),
                       "visual_score": best["final_score"],
                       "visual_decision": best["decision"],
                       "visual_reason": best.get("reason", "")}
    if gaps:
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(
            f"Footage gaps remain ({len(gaps)}): "
            + "; ".join(f"{g['requirement_id']}: {g['reason']}"
                        for g in gaps)
            + ". Gaps are reported, never filled synthetically.")
    return {"asset_manifest": {"version": "1.0", "assets": assets,
                                     "metadata": {"provenance": provenance,
                                                  "visual": visual}}}


def run_footage_intelligence(ctx: StageContext,
                             cfg: dict[str, Any]) -> dict[str, Any]:
    """Per-asset verdicts over the acquired manifest."""
    from lib.footage_hub import hub as footage_hub

    manifest = ctx.inputs.get("asset_manifest") or {}
    from lib.producer.contracts import manifest_assets
    assets = manifest_assets(manifest)
    if not assets:
        raise MissingStageInput("Footage intelligence needs asset_manifest.")
    verdicts = []
    for asset in assets:
        decision = asset.get("visual_decision") or "weak"
        rights = (asset.get("rights_status")
                  or asset.get("license") or "unknown")
        if decision in ("wrong", "missing"):
            verdict = "wrong"
        elif "rights" in str(rights).lower() and "unknown" in str(rights).lower():
            verdict = "weak"
        else:
            verdict = {"pass": "pass", "weak": "weak"}.get(decision, "weak")
        verdicts.append({"asset_id": asset.get("id", asset.get("asset_id")),
                         "requirement_id": asset.get("requirement_id"),
                         "verdict": verdict,
                         "score": asset.get("visual_score", 0.0),
                         "rights": rights})
    bad = [v for v in verdicts if v["verdict"] in ("wrong", "missing")]
    if bad and str(cfg.get("footage_intelligence_mode",
                           "fail_closed")) == "fail_closed":
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(
            f"Footage intelligence rejected picks: "
            + ", ".join(v["asset_id"] for v in bad))
    report = {"version": "1.0", "verdicts": verdicts}
    try:
        from schemas.artifacts import validate_artifact
        validate_artifact("footage_report", report)
    except Exception as exc:
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(
            f"Footage report invalid: {exc}") from exc
    return {"footage_report": report}


def run_fact_check(ctx: StageContext, cfg: dict[str, Any],
                   supplied: dict[str, Any]) -> dict[str, Any]:
    """Verify the script with the real FactCheckAgent, then record."""
    from lib.editorial.contracts import ResearchPackage
    from lib.editorial.factcheck import FactCheckAgent

    script = ctx.inputs.get("script") or {}
    package_dict = (supplied.get("evidence_package")
                    or ctx.inputs.get("evidence_bundle")
                    or ctx.inputs.get("research_package"))
    if package_dict is None:
        raise MissingStageInput(
            "Fact check needs the research package (stage_inputs "
            "['evidence_package']).")
    package = (package_dict if isinstance(package_dict, ResearchPackage)
               else ResearchPackage.from_dict(package_dict))
    sections = script.get("sections") or []
    if not sections:
        raise MissingStageInput("Fact check needs script.sections.")
    from lib.producer.contracts import script_claims
    claims_by_section = script_claims(script)
    blocks = [{"id": s.get("id"),
               "claim_ids": claims_by_section.get(str(s.get("id")), [])}
              for s in sections]
    report = FactCheckAgent().check(blocks, package)
    if not report.passed:
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(
            f"Fact check blocked approval: "
            f"{report.blocking_claim_ids}. Quarantined claims must be cut "
            f"before storyboard (fail closed).")
    return {"factcheck_report": report.to_dict()}


def run_editorial(ctx: StageContext, cfg: dict[str, Any]) -> dict[str, Any]:
    """Assemble Timeline IR from requirements + picks + narration."""
    from lib.producer.assembly import assemble_timeline

    requirements = _requirements_from(ctx)
    manifest = ctx.inputs.get("asset_manifest") or {}
    narration = ctx.inputs.get("narration_manifest") or {}
    # Manifest records carry visual_score/visual_decision + the full
    # asset; assembly needs scored picks (final_score/decision/reason
    # + embedded asset). Adapt here — assembly never reads the
    # manifest shape directly.
    from lib.producer.contracts import manifest_assets
    picks = []
    for record in manifest_assets(manifest):
        aid = record.get("asset_id") or record.get("id", "")
        picks.append({
            "requirement_id": record.get("requirement_id", ""),
            "asset_id": aid,
            "final_score": float(record.get("visual_score", 0.0) or 0.0),
            "decision": record.get("visual_decision", ""),
            "reason": record.get("visual_reason", ""),
            "asset": dict(record),
        })
    segments = []
    cursor = 0.0
    for stem in narration.get("sections") or []:
        duration = float(stem.get("duration_seconds", 0) or 0)
        # edit_decisions narration segments are closed
        # (asset_id/start/end only); section linkage lives in the
        # assembly layout, not the segment.
        segments.append({"asset_id": stem.get("asset_id", ""),
                         "start_seconds": round(cursor, 3),
                         "end_seconds": round(cursor + duration, 3)})
        cursor += duration
    decisions = assemble_timeline(
        requirements, picks, segments,
        render_runtime=cfg.get("render_runtime", "remotion"),
        renderer_family=cfg.get("renderer_family",
                                "documentary-montage"))
    return {"edit_decisions": decisions}


def run_timeline(ctx: StageContext, cfg: dict[str, Any]) -> dict[str, Any]:
    """Refine (never replace) the Timeline IR: re-time + re-validate."""
    from lib.producer.assembly import retime_timeline

    prior = ctx.inputs.get("edit_decisions") or {}
    if not prior.get("cuts"):
        raise MissingStageInput(
            "Timeline needs edit_decisions with cuts from editorial.")
    return {"edit_decisions": retime_timeline(prior)}


def run_audio(ctx: StageContext, cfg: dict[str, Any]) -> dict[str, Any]:
    """Build the mix plan, execute it, verify the mix."""
    from lib.producer.audio_build import build_mix_plan, verify_mix
    from tools.audio.audio_mixer import AudioMixer

    narration = ctx.inputs.get("narration_manifest") or {}
    script = ctx.inputs.get("script") or {}
    plan = build_mix_plan(narration, script, ctx.workdir, cfg)
    out_path = Path(plan["output_path"])
    result = AudioMixer().execute({**plan["mixer_inputs"],
                                   "output_path": str(out_path)})
    if not result.success:
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(f"Audio mix failed: {result.error}")
    attestation = verify_mix(out_path, plan)
    return {"audio_mix": attestation}


def run_render(ctx: StageContext, cfg: dict[str, Any]) -> dict[str, Any]:
    """Render via video_compose. No silent runtime swaps."""
    from tools.video.video_compose import VideoCompose

    decisions = ctx.inputs.get("edit_decisions") or {}
    locked = decisions.get("render_runtime")
    if not locked:
        raise MissingStageInput(
            "Render needs edit_decisions.render_runtime (locked at edit).")
    requested = cfg.get("render_runtime")
    if requested and requested != locked:
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(
            f"Render runtime swap refused: locked={locked!r} "
            f"requested={requested!r}.")
    # M4: renderer_family is locked alongside render_runtime (manifest
    # editorial review_focus). Refuse silent family swaps; the legacy
    # documentary-montage pipeline keeps working because it sets the same
    # family explicitly at proposal.
    locked_family = decisions.get("renderer_family")
    requested_family = cfg.get("renderer_family")
    if (locked_family and requested_family
            and requested_family != locked_family):
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(
            f"Renderer family swap refused: locked={locked_family!r} "
            f"requested={requested_family!r}.")
    out_path = ctx.workdir / "renders" / "final.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    params: dict[str, Any] = {"operation": cfg.get("render_operation",
                                                   "render"),
                              "edit_decisions": decisions,
                              "output_path": str(out_path)}
    if ctx.inputs.get("asset_manifest"):
        params["asset_manifest"] = ctx.inputs["asset_manifest"]
    if ctx.inputs.get("audio_mix", {}).get("mix_path"):
        params["audio_path"] = ctx.inputs["audio_mix"]["mix_path"]
    script_text = " ".join(
        str(s.get("text", "")) for s in
        (ctx.inputs.get("script") or {}).get("sections") or [])
    if script_text.strip():
        params["script_text"] = script_text
    transcript_path = _narration_transcript_path(ctx)
    if transcript_path is not None:
        params["narration_transcript_path"] = str(transcript_path)
    result = VideoCompose().execute(params)
    if not result.success:
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(f"Render failed: {result.error}")
    data = result.data or {}
    return {"render_report": {
        "version": "1.0",
        "outputs": [{"path": str(out_path),
                     "format": "mp4",
                     "resolution": data.get("resolution", ""),
                     "duration_seconds": data.get("duration_seconds", 0.0),
                     "file_size_bytes": (out_path.stat().st_size
                                         if out_path.exists() else 0)}],
        "metadata": {"render_runtime": locked,
                     "composition": data}}}


def run_qa(ctx: StageContext, cfg: dict[str, Any]) -> dict[str, Any]:
    """Independent QA; result must be a valid final_review."""
    from lib.producer.qa import QAAgent

    agent = QAAgent(config=cfg)
    report = agent.run(_qa_inputs(ctx, cfg))
    return {"final_review": agent.to_final_review(report)}


def run_packaging(ctx: StageContext, cfg: dict[str, Any]) -> dict[str, Any]:
    """Upload-ready bundle + thumbnail concept (no publish)."""
    from lib.producer.packaging import PackageAgent

    bundle = PackageAgent().build(_packaging_inputs(ctx, cfg))
    return {"package_bundle": bundle}


def run_human_review(ctx: StageContext, cfg: dict[str, Any],
                     supplied: dict[str, Any]) -> dict[str, Any]:
    """Record an explicit human decision (never auto-approved)."""
    from lib.producer.review import mark_ready_for_review, record_decision

    payload = supplied.get("human_review") or supplied.get(
        "review_decision")
    if payload is None:
        raise MissingStageInput(
            "Human review needs an explicit decision payload "
            "(stage_inputs['human_review']). The Producer never "
            "auto-approves.")
    # L4: validate the review_decision on the production path before
    # recording, so a malformed decision fails the stage (retryable)
    # instead of persisting.
    try:
        from schemas.artifacts import validate_artifact
        validate_artifact("review_decision", {
            "decision": payload.get("decision", ""),
            "approver": payload.get("approver", ""),
            "rationale": payload.get("rationale", ""),
            "timestamp": payload.get(
                "timestamp", "2026-01-01T00:00:00+00:00"),
            "episode_id": ctx.episode_id,
        })
    except Exception as exc:
        from lib.producer.producer import CriticalStageError
        raise CriticalStageError(
            f"Human review decision invalid: {exc}") from exc
    # The Producer opens review (package assembled → READY_FOR_REVIEW)
    # before the explicit human verdict is recorded. Approval stays
    # human: payload carries approver identity + rationale, and the
    # Producer never invents them.
    mark_ready_for_review(ctx.workdir, ctx.episode_id,
                          video_path=payload.get("video_path", ""))
    decision = record_decision(
        ctx.workdir, episode_id=ctx.episode_id,
        decision=payload.get("decision", ""),
        approver=payload.get("approver", ""),
        rationale=payload.get("rationale", ""),
        video_path=payload.get("video_path", ""))
    return {"review_decision": decision.to_dict()}


# -- shared input plumbing -------------------------------------------------


def _narration_transcript_path(ctx: StageContext) -> Path | None:
    """Write video_compose's narration_transcript from TTS alignment.

    Tokens come from what the TTS engine reported speaking (alignment
    entries, falling back to the synthesized section text). Per-word
    timings are section-level approximations and labeled as such; the
    consumer only compares tokens against the script (punctuation-leak
    and word-accuracy checks). Returns None when there is nothing to
    say — the render then runs with the check visibly skipped.
    """
    import json as _json

    stems = (ctx.inputs.get("narration_manifest") or {}).get("sections") or []
    words: list[dict[str, Any]] = []
    for stem in stems:
        duration = float(stem.get("duration_seconds", 0) or 0)
        chunks = stem.get("alignment") or []
        if not chunks and stem.get("text"):
            chunks = [{"text": stem["text"], "start_seconds": 0.0,
                       "end_seconds": duration}]
        for chunk in chunks:
            tokens = str(chunk.get("text", "")).split()
            if not tokens:
                continue
            span = (float(chunk.get("end_seconds", 0) or 0)
                    - float(chunk.get("start_seconds", 0) or 0))
            per_word = span / len(tokens) if span > 0 else 0.0
            base = float(chunk.get("start_seconds", 0) or 0)
            for i, token in enumerate(tokens):
                words.append({"word": token,
                              "start": round(base + i * per_word, 3),
                              "end": round(base + (i + 1) * per_word, 3)})
    if not words:
        return None
    out = ctx.workdir / "assets" / "audio" / "narration_transcript.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps({
        "source": "tts_alignment",
        "timing_note": "section-level approximation from TTS chunk "
                       "alignment; tokens are exact",
        "word_timestamps": words,
    }), encoding="utf-8")
    return out


def _requirements_from(ctx: StageContext) -> list[dict[str, Any]]:
    reqs = (ctx.config.get("footage_requirements")
            or (ctx.inputs.get("storyboard") or {}).get("requirements")
            or [])
    scenes = (ctx.inputs.get("scene_plan") or {}).get("scenes") or []
    if not reqs and scenes:
        reqs = [{"id": s.get("id", f"slot-{i}"),
                 "narration_block_id": s.get("script_section_id", ""),
                 "subject": s.get("description", ""),
                 "positive_search_terms": (s.get("description", "")).split(),
                 "preferred_media_type": "video",
                 "minimum_duration_seconds": 2.0,
                 "desired_duration_seconds": max(
                     2.0, float(s.get("end_seconds", 0) or 0)
                     - float(s.get("start_seconds", 0) or 0)),
                 "rights_requirement": "verified"}
                for i, s in enumerate(scenes)]
    return reqs


def _qa_inputs(ctx: StageContext, cfg: dict[str, Any]) -> dict[str, Any]:
    render = ctx.inputs.get("render_report") or {}
    outputs = render.get("outputs") or [{}]
    return {"episode_id": ctx.episode_id,
            "video_path": (outputs[0].get("path") or ""),
            "script": ctx.inputs.get("script") or {},
            "factcheck_report": ctx.inputs.get("factcheck_report") or {},
            "research_package": (ctx.inputs.get("evidence_bundle")
                                 or ctx.inputs.get("research_package") or {}),
            "storyboard": ctx.inputs.get("storyboard") or {},
            "asset_manifest": ctx.inputs.get("asset_manifest") or {},
            "narration_manifest": ctx.inputs.get("narration_manifest") or {},
            "edit_decisions": ctx.inputs.get("edit_decisions") or {},
            "render_report": ctx.inputs.get("render_report") or {},
            "rights_mode": cfg.get("rights_mode", "strict"),
            "prober": cfg.get("prober")}


def _packaging_inputs(ctx: StageContext,
                      cfg: dict[str, Any]) -> dict[str, Any]:
    factcheck = ctx.inputs.get("factcheck_report") or {}
    verified = [v.get("statement", v.get("claim_id", ""))
                for v in factcheck.get("verdicts") or []
                if v.get("verdict") in ("verified", "opinion")
                and not v.get("blocks_approval")]
    verified = [v for v in verified if v]
    topic = (cfg.get("topic", "")
             or (ctx.inputs.get("brief") or {}).get("topic", "")
             or (ctx.inputs.get("brief") or {}).get("title", ""))
    seeds = list(cfg.get("title_seeds") or [])
    if not seeds and topic and verified:
        first = verified[0].rstrip(".")
        seeds = [first,
                 f"{topic}: {first[:60]}".rstrip(),
                 f"How {topic} took shape",
                 f"{topic}, explained with evidence",
                 f"What the evidence shows about {topic}"]
    return {"episode_id": ctx.episode_id,
            "topic": topic,
            "brief": ctx.inputs.get("brief") or {},
            "script": ctx.inputs.get("script") or {},
            "storyboard": ctx.inputs.get("storyboard") or {},
            "factcheck_report": factcheck,
            "verified_claims": verified,
            "title_seeds": seeds[:5],
            "narration_manifest": ctx.inputs.get("narration_manifest") or {},
            "render_report": ctx.inputs.get("render_report") or {},
            "final_review": ctx.inputs.get("final_review") or {}}
