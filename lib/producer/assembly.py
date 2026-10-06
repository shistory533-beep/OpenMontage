"""Editorial assembly: requirements -> moments -> shots -> Timeline IR.

Uses the EXISTING Timeline IR (edit_decisions schema) as the single
source of truth. No second timeline format is created: this module only
constructs, validates, re-times, and surgically revises edit_decisions
documents.

- FootageMoment: one selected span of one asset bound to one requirement,
  with score, provenance, and repetition count.
- ShotDecision: the approved moment for a scene, with rationale + revision.
- assemble_timeline: deterministic requirements + picks + narration ->
  edit_decisions (validated against the canonical schema).
- replace_scene / revise_scene: surgical single-scene updates. Every
  other cut is byte-identical afterwards (asserted in tests).
- Deterministic replay: the timeline carries an assembly_input_hash;
  rebuilding from the same inputs yields identical cuts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from lib.producer.contracts import FootageMoment, ShotDecision


class AssemblyError(ValueError):
    """Base class: assembly refused (gap reported, never filled)."""


class AssemblyGapError(AssemblyError):
    """A requirement has no usable pick. The gap is named, not papered over."""


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str)


def input_hash(requirements: list[dict[str, Any]],
               picks: list[dict[str, Any]],
               narration_segments: list[dict[str, Any]]) -> str:
    payload = {"requirements": requirements, "picks": picks,
               "narration_segments": narration_segments}
    return "sha256:" + hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()


def select_moments(
    requirements: list[dict[str, Any]],
    scored: list[dict[str, Any]],
    assets_by_id: dict[str, dict[str, Any]],
    *,
    max_repeats: int = 1,
) -> list[FootageMoment]:
    """Pick the best usable scored asset per requirement.

    Only `pass`/`weak` decisions are usable. Gaps raise AssemblyGapError
    naming the requirement — missing footage stays missing.
    """
    by_req: dict[str, list[dict[str, Any]]] = {}
    for entry in scored:
        by_req.setdefault(entry.get("requirement_id", ""), []).append(entry)
    use_counts: dict[str, int] = {}
    moments: list[FootageMoment] = []
    gaps: list[str] = []
    for req in requirements:
        rid = req.get("id", "")
        options = sorted(by_req.get(rid, []),
                         key=lambda s: (-s.get("final_score", 0.0),
                                        s.get("asset_id", "")))
        chosen = None
        for opt in options:
            if opt.get("decision") not in ("pass", "weak"):
                continue
            asset = assets_by_id.get(opt.get("asset_id", ""))
            if asset is None:
                continue
            if use_counts.get(opt["asset_id"], 0) >= max_repeats:
                continue
            chosen = (opt, asset)
            break
        if chosen is None:
            gaps.append(rid or "(unnamed requirement)")
            continue
        opt, asset = chosen
        use_counts[opt["asset_id"]] = use_counts.get(opt["asset_id"], 0) + 1
        duration = float(asset.get("duration") or 0.0)
        want = float(req.get("desired_duration_seconds") or 0.0)
        span = min(want, duration) if duration > 0 else want
        if span <= 0:
            span = want or 2.0
        moment = FootageMoment(
            requirement_id=rid, asset_id=opt["asset_id"],
            asset_provider=str(asset.get("provider", "")),
            asset_path=str(asset.get("local_path")
                            or asset.get("download_url")
                            or opt["asset_id"]),
            in_seconds=0.0, out_seconds=round(span, 3),
            function=str(req.get("shot_function", "")),
            score=float(opt.get("final_score", 0.0)),
            decision=str(opt.get("decision", "")),
            provenance={"provider": asset.get("provider"),
                        "source_url": asset.get("source_url"),
                        "license": asset.get("license"),
                        "rights_status": asset.get("rights_status"),
                        "checksum": asset.get("checksum"),
                        "score_reason": opt.get("reason", "")},
            repetition_count=use_counts[opt["asset_id"]] - 1)
        moments.append(moment)
    if gaps:
        raise AssemblyGapError(
            f"No usable footage for requirements: {gaps}. "
            f"Re-acquire or narrow the storyboard; missing footage "
            f"stays missing, it is never filled synthetically.")
    return moments


def assemble_timeline(
    requirements: list[dict[str, Any]],
    picks: list[dict[str, Any]],
    narration_segments: list[dict[str, Any]],
    *,
    render_runtime: str = "remotion",
    renderer_family: str = "documentary-montage",
    assets_by_id: dict[str, dict[str, Any]] | None = None,
    max_repeats: int = 1,
) -> dict[str, Any]:
    """Build edit_decisions from moments + narration. Schema-validated.

    `picks` are scored-asset entries ({requirement_id, asset_id,
    final_score, decision, reason}); asset details resolve via
    `assets_by_id`, or from pick-embedded asset dicts under "asset".
    Cuts follow requirement order; narration segments ride in
    audio.narration.segments (existing contract, see tts_hub.mapper).
    """
    if assets_by_id is None:
        assets_by_id = {}
        for pick in picks:
            asset = pick.get("asset") or {}
            aid = pick.get("asset_id") or asset.get("asset_id")
            if aid:
                merged = dict(asset)
                merged.setdefault("asset_id", aid)
                assets_by_id[aid] = merged
    moments = select_moments(requirements, picks, assets_by_id,
                             max_repeats=max_repeats)
    decisions = [ShotDecision(scene_id=f"scene-{i + 1:02d}",
                              requirement_id=m.requirement_id,
                              moment=m.to_dict(),
                              rationale=m.provenance.get("score_reason", ""),
                              revision=1)
                 for i, m in enumerate(moments)]
    return _timeline_from_decisions(
        decisions, narration_segments, render_runtime, renderer_family,
        requirements, picks)


def _timeline_from_decisions(
    decisions: list[ShotDecision],
    narration_segments: list[dict[str, Any]],
    render_runtime: str,
    renderer_family: str,
    requirements: list[dict[str, Any]],
    picks: list[dict[str, Any]],
) -> dict[str, Any]:
    # Cuts stay schema-pure (id/source/in/out only). All assembly
    # bookkeeping — scene ids, requirement bindings, timeline positions,
    # shot decisions, input hash — lives under free-form metadata, so the
    # Timeline IR itself is never forked into a second format.
    cuts, layout = [], []
    cursor = 0.0
    for i, decision in enumerate(decisions):
        moment = FootageMoment.from_dict(decision.moment)
        duration = round(moment.out_seconds - moment.in_seconds, 3)
        cuts.append({"id": f"cut-{i + 1:02d}",
                     "source": moment.asset_path,
                     "in_seconds": moment.in_seconds,
                     "out_seconds": moment.out_seconds,
                     "layer": "primary",
                     "reason": (f"{decision.scene_id} <- "
                                f"{moment.requirement_id} "
                                f"({moment.function}, "
                                f"score {moment.score:.2f})")})
        layout.append({"cut_id": f"cut-{i + 1:02d}",
                       "scene_id": decision.scene_id,
                       "requirement_id": moment.requirement_id,
                       "asset_id": moment.asset_id,
                       "function": moment.function,
                       "start_seconds": round(cursor, 3),
                       "end_seconds": round(cursor + duration, 3)})
        cursor += duration
    timeline = {
        "version": "1.0",
        "cuts": cuts,
        "render_runtime": render_runtime,
        "renderer_family": renderer_family,
        "audio": {"narration": {"segments": list(narration_segments)}},
        "metadata": {
            "assembly_input_hash": input_hash(
                requirements, picks, narration_segments),
            "timeline_revision": 1,
            "cuts_layout": layout,
            "shot_decisions": [d.to_dict() for d in decisions],
        },
    }
    _validate_timeline(timeline)
    return timeline


def _layout(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    return list((timeline.get("metadata") or {}).get("cuts_layout") or [])


def _decisions(timeline: dict[str, Any]) -> list[ShotDecision]:
    return [ShotDecision.from_dict(d)
            for d in ((timeline.get("metadata") or {}).get(
                "shot_decisions") or [])]


def _validate_timeline(timeline: dict[str, Any]) -> None:
    from schemas.artifacts import validate_artifact

    validate_artifact("edit_decisions", timeline)
    cuts = timeline.get("cuts") or []
    if not cuts:
        raise AssemblyError("Timeline has no cuts.")
    for cut in cuts:
        if cut["out_seconds"] <= cut["in_seconds"]:
            raise AssemblyError(
                f"Cut {cut.get('id')!r} has non-positive span.")
    # narration segments must be covered by cuts (alignment, no gaps).
    segments = ((timeline.get("audio") or {}).get("narration") or {}).get(
        "segments") or []
    total_cut = sum(c["out_seconds"] - c["in_seconds"] for c in cuts)
    total_nar = sum(max(0.0, s.get("end_seconds", 0) - s.get(
        "start_seconds", 0)) for s in segments)
    if segments and total_nar > total_cut + 0.5:
        raise AssemblyError(
            f"Narration ({total_nar:.1f}s) overruns footage "
            f"({total_cut:.1f}s): re-time before locking the edit.")


def retime_timeline(timeline: dict[str, Any]) -> dict[str, Any]:
    """Refine without replacing: re-lay layout end-to-end, bump revision."""
    layout = [dict(entry) for entry in _layout(timeline)]
    if not layout and not (timeline.get("cuts") or []):
        raise AssemblyError("Timeline has no cuts to re-time.")
    if not layout:
        # Legacy IR without assembly layout: positions derive from order.
        cursor = 0.0
        for i, cut in enumerate(timeline.get("cuts") or []):
            span = round(cut["out_seconds"] - cut["in_seconds"], 3)
            layout.append({"cut_id": cut.get("id", f"cut-{i + 1:02d}"),
                           "scene_id": f"scene-{i + 1:02d}",
                           "requirement_id": "",
                           "asset_id": "", "function": "",
                           "start_seconds": round(cursor, 3),
                           "end_seconds": round(cursor + span, 3)})
            cursor += span
    for entry in layout:
        span = round(entry["end_seconds"] - entry["start_seconds"], 3)
        if span <= 0:
            raise AssemblyError(
                f"Scene {entry.get('scene_id')!r} has non-positive span.")
    out = dict(timeline)
    metadata = dict(timeline.get("metadata") or {})
    metadata["cuts_layout"] = layout
    metadata["timeline_revision"] = int(metadata.get("timeline_revision",
                                                     1)) + 1
    out["metadata"] = metadata
    _validate_timeline(out)
    return out


def replace_scene(timeline: dict[str, Any],
                  requirement_id: str,
                  new_moment: FootageMoment,
                  rationale: str = "") -> dict[str, Any]:
    """Swap exactly one scene's footage. All other cuts byte-identical."""
    decisions = _decisions(timeline)
    hit = [d for d in decisions if d.requirement_id == requirement_id]
    if not hit:
        raise AssemblyError(
            f"No scene bound to requirement {requirement_id!r}.")
    if len(hit) != 1:
        raise AssemblyError(
            f"Requirement {requirement_id!r} backs {len(hit)} scenes; "
            f"revise them individually.")
    target = hit[0]
    target.moment = new_moment.to_dict()
    target.rationale = rationale or target.rationale
    target.revision += 1
    return _rebuild_keep_timing(timeline, decisions,
                                f"replaced {target.scene_id}")


def revise_scene(timeline: dict[str, Any], scene_id: str, *,
                 in_seconds: float | None = None,
                 out_seconds: float | None = None,
                 rationale: str = "") -> dict[str, Any]:
    """Re-trim one scene in place. All other cuts byte-identical."""
    decisions = _decisions(timeline)
    hit = [d for d in decisions if d.scene_id == scene_id]
    if len(hit) != 1:
        raise AssemblyError(f"Scene {scene_id!r} not found exactly once.")
    target = hit[0]
    moment = FootageMoment.from_dict(target.moment)
    if in_seconds is not None:
        moment.in_seconds = float(in_seconds)
    if out_seconds is not None:
        moment.out_seconds = float(out_seconds)
    if moment.out_seconds <= moment.in_seconds:
        raise AssemblyError(
            f"Scene {scene_id!r} revision has non-positive span.")
    target.moment = moment.to_dict()
    target.rationale = rationale or target.rationale
    target.revision += 1
    return _rebuild_keep_timing(timeline, decisions,
                                f"revised {scene_id}")


def _rebuild_keep_timing(timeline: dict[str, Any],
                         decisions: list[ShotDecision],
                         note: str) -> dict[str, Any]:
    """Rebuild cuts from decisions, re-laid end-to-end (gap-free).

    Unrelated scenes keep their cut id, source, asset spans, and
    function — only timeline positions shift when an edit changes total
    duration. "Changing scene 12 must not rebuild unrelated scenes"
    means their content decisions are untouched, not their positions.
    """
    cuts, layout = [], []
    cursor = 0.0
    for i, decision in enumerate(decisions):
        moment = FootageMoment.from_dict(decision.moment)
        old_cuts = [c for c in (timeline.get("cuts") or [])
                    if c.get("id") == f"cut-{i + 1:02d}"]
        old = old_cuts[0] if old_cuts else {}
        duration = round(moment.out_seconds - moment.in_seconds, 3)
        cut_id = old.get("id", f"cut-{i + 1:02d}")
        cuts.append({"id": cut_id,
                     "source": moment.asset_path,
                     "in_seconds": moment.in_seconds,
                     "out_seconds": moment.out_seconds,
                     "layer": old.get("layer", "primary"),
                     "reason": (f"{decision.scene_id} <- "
                                f"{moment.requirement_id} "
                                f"({moment.function}, "
                                f"score {moment.score:.2f})")})
        layout.append({"cut_id": cut_id,
                       "scene_id": decision.scene_id,
                       "requirement_id": moment.requirement_id,
                       "asset_id": moment.asset_id,
                       "function": moment.function,
                       "start_seconds": round(cursor, 3),
                       "end_seconds": round(cursor + duration, 3)})
        cursor += duration
    out = dict(timeline)
    out["cuts"] = cuts
    metadata = dict(timeline.get("metadata") or {})
    metadata["cuts_layout"] = layout
    metadata["shot_decisions"] = [d.to_dict() for d in decisions]
    metadata["timeline_revision"] = int(metadata.get("timeline_revision",
                                                     1)) + 1
    log = list(metadata.get("revision_log") or [])
    log.append(note)
    metadata["revision_log"] = log
    out["metadata"] = metadata
    _validate_timeline(out)
    return out
