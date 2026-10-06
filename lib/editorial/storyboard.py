"""Storyboard Agent: narration blocks -> visual requirements.

Input: approved DocumentaryScript blocks + a passing FactCheckReport +
research evidence context. Output: storyboard.json (VisualRequirements +
chapter plan + coverage) plus a scene_plan-compatible adapter for the
pipeline's storyboard stage.

Hard rules, enforced in code:
- every narration block gets >= 1 VisualRequirement (coverage fails otherwise),
- the board never assumes footage exists: storyboard assigns UNCERTAIN by
  default, MISSING when a block depends on blocked/quarantined claims, and
  NEVER assigns AVAILABLE (only a retrieval pass may promote to AVAILABLE),
- no fake documentary visuals: requirements describe what to FIND
  (search terms, exclusions, rights), never generated stand-ins.
"""

from __future__ import annotations

import re
from typing import Any

from lib.editorial.contracts import SHOT_FUNCTIONS, FactCheckReport
from lib.editorial.script_agent import STOPWORDS, _WORD_RE

BEAT_SHOT_FUNCTION = {
    "hook": "establishing",
    "question": "context",
    "setup": "context",
    "discovery": "evidence",
    "escalation": "human_impact",
    "mechanism": "mechanism",
    "consequence": "consequence",
    "transformation": "comparison",
    "payoff": "payoff",
}

BEAT_PRIORITY = {
    "hook": "hero",
    "payoff": "high",
    "mechanism": "high",
}

CHART_KEYWORDS = ("chart", "graph", "data", "statistics", "percent",
                   "growth", "decline", "trend")
MAP_KEYWORDS = ("map", "country", "city", "region", "border", "river",
                 "ocean", "continent", "location")
ARCHIVAL_KEYWORDS = ("archive", "archival", "historical", "history",
                      "decade", "century", "vintage", "footage from")

EXCLUSIONS_BY_FUNCTION = {
    "archival": ["reenactment", "cgi", "illustration", "dramatization"],
    "evidence": ["reenactment", "stock metaphor", "illustration"],
    "chart": ["photograph", "broll", "talking head"],
    "map": ["photograph", "illustration"],
    "establishing": ["close-up", "interview", "text overlay"],
}

SHOT_TYPE_BY_FUNCTION = {
    "establishing": "wide",
    "context": "wide",
    "evidence": "close_up",
    "mechanism": "detail",
    "human_impact": "medium",
    "detail": "close_up",
    "transition": "aerial",
    "comparison": "split",
    "map": "graphic",
    "chart": "graphic",
    "archival": "archival",
    "consequence": "wide",
    "payoff": "wide",
}


class StoryboardError(ValueError):
    """Raised when storyboard preconditions fail (fail closed)."""


def extract_keywords(text: str, limit: int = 8) -> list[str]:
    """Deterministic keyword extraction: frequency, then alphabetical."""
    counts: dict[str, int] = {}
    for word in _WORD_RE.findall(text.lower()):
        if len(word) > 3 and word not in STOPWORDS:
            counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:limit]]


class StoryboardAgent:
    """Derives visual requirements from approved narration."""

    def build(self, title: str, blocks: list[dict[str, Any]],
              report: FactCheckReport,
              evidence_source_urls: list[str] | None = None
              ) -> dict[str, Any]:
        if not report.passed:
            raise StoryboardError(
                f"storyboard blocked: fact-check has open quarantines "
                f"{report.blocking_claim_ids} — cut or re-source first")
        if not blocks:
            raise StoryboardError("storyboard requires narration blocks")
        blocked_claims = set(report.blocking_claim_ids)
        evidence_urls = list(evidence_source_urls or [])
        requirements: list[dict[str, Any]] = []
        for block in blocks:
            requirements.extend(self._requirements_for_block(
                block, blocked_claims, evidence_urls))
        # coverage: every block has >= 1 requirement
        covered = {r["narration_block_id"] for r in requirements}
        missing = [b["id"] for b in blocks if b["id"] not in covered]
        if missing:
            raise StoryboardError(
                f"storyboard coverage gap: blocks without requirements: "
                f"{missing}")
        chapter_plan = self._chapter_plan(blocks, requirements)
        coverage = self._coverage(blocks, requirements)
        return {"version": "1.0", "title": title,
                "script_title": "",
                "factcheck_passed": True,
                "requirements": requirements,
                "chapter_plan": chapter_plan,
                "coverage": coverage}

    # -- per-block derivation ------------------------------------------

    def _requirements_for_block(self, block: dict[str, Any],
                                blocked_claims: set[str],
                                evidence_urls: list[str]
                                ) -> list[dict[str, Any]]:
        duration = float(block.get("estimated_duration_seconds") or 0.0)
        n = max(1, min(4, -(-int(duration) // 10)))  # ceil(dur/10), cap 4
        per = round(duration / n, 2) if n else 0.0
        text = block.get("text", "")
        low = text.lower()
        if any(k in low for k in CHART_KEYWORDS):
            function = "chart"
        elif any(k in low for k in MAP_KEYWORDS):
            function = "map"
        elif any(k in low for k in ARCHIVAL_KEYWORDS):
            function = "archival"
        else:
            function = BEAT_SHOT_FUNCTION.get(block.get("beat", ""),
                                              "context")
        if function not in SHOT_FUNCTIONS:  # pragma: no cover - defensive
            function = "context"
        claim_ids = list(block.get("claim_ids", []))
        availability = ("missing" if any(c in blocked_claims
                                         for c in claim_ids)
                        else "uncertain")
        keywords = extract_keywords(text)
        subject = block.get("visual_intent", "") or " ".join(keywords[:3])
        out = []
        for i in range(n):
            rid = f"{block['id']}-vis-{i + 1}" if n > 1 else f"{block['id']}-vis"
            out.append({
                "id": rid,
                "narration_block_id": block["id"],
                "visual_objective": (
                    f"Show {subject} ({function}) for narration "
                    f"{block['id']} part {i + 1}/{n}" if n > 1 else
                    f"Show {subject} ({function}) for narration "
                    f"{block['id']}"),
                "subject": subject,
                "location": "",
                "period": "",
                "preferred_media_type": "image" if function in ("chart", "map")
                else "video",
                "shot_type": SHOT_TYPE_BY_FUNCTION[function],
                "shot_function": function,
                "minimum_duration_seconds": round(per * 0.6, 2),
                "desired_duration_seconds": per,
                "evidence_relationship": (
                    "proves" if function in ("evidence", "chart", "map")
                    else "context"),
                "claim_ids": claim_ids,
                "evidence_source_ids": evidence_urls,
                "positive_search_terms": keywords,
                "exclusion_terms": list(
                    EXCLUSIONS_BY_FUNCTION.get(function, [])),
                "rights_requirement": "verified",
                "priority": BEAT_PRIORITY.get(block.get("beat", ""),
                                              "normal"),
                "fallback_policy": ("flag_missing"
                                    if availability == "missing"
                                    else "widen_terms"),
                "availability": availability,
            })
        return out

    # -- plan + coverage -------------------------------------------------

    def _chapter_plan(self, blocks: list[dict[str, Any]],
                      requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_block: dict[str, list[str]] = {}
        for r in requirements:
            by_block.setdefault(r["narration_block_id"], []).append(r["id"])
        chapters: dict[str, dict[str, Any]] = {}
        for b in blocks:
            ch = chapters.setdefault(b.get("chapter_id", ""), {
                "chapter_id": b.get("chapter_id", ""), "block_ids": [],
                "requirement_ids": [], "narration_seconds": 0.0})
            ch["block_ids"].append(b["id"])
            ch["requirement_ids"].extend(by_block.get(b["id"], []))
            ch["narration_seconds"] = round(
                ch["narration_seconds"] +
                float(b.get("estimated_duration_seconds") or 0.0), 2)
        return list(chapters.values())

    def _coverage(self, blocks: list[dict[str, Any]],
                  requirements: list[dict[str, Any]]) -> dict[str, Any]:
        narration = round(sum(float(b.get("estimated_duration_seconds")
                                    or 0.0) for b in blocks), 2)
        desired = round(sum(r["desired_duration_seconds"]
                            for r in requirements), 2)
        missing = [r["id"] for r in requirements
                   if r["availability"] == "missing"]
        return {"block_count": len(blocks),
                "requirement_count": len(requirements),
                "narration_seconds": narration,
                "desired_visual_seconds": desired,
                "covers_narration": desired >= narration,
                "missing_requirement_ids": missing}

    # -- pipeline adapter --------------------------------------------------

    def to_scene_plan(self, storyboard: dict[str, Any],
                      style_playbook: str = "") -> dict[str, Any]:
        """Map visual requirements onto the scene_plan artifact shape."""
        scenes = []
        cursor = 0.0
        for req in storyboard.get("requirements", []):
            dur = float(req.get("desired_duration_seconds") or 0.0)
            kind = ("animation" if req.get("preferred_media_type") == "image"
                    and req.get("shot_function") in ("chart", "map")
                    else "broll")
            scenes.append({
                "id": req["id"],
                "type": kind,
                "description": req.get("visual_objective", ""),
                "start_seconds": round(cursor, 2),
                "end_seconds": round(cursor + dur, 2),
                "script_section_id": req.get("narration_block_id", ""),
                "shot_intent": req.get("shot_function", ""),
                "narrative_role": ("evidence"
                                   if req.get("evidence_relationship")
                                   == "proves" else "establish_context"),
            })
            cursor += dur
        doc: dict[str, Any] = {"version": "1.0", "scenes": scenes}
        if style_playbook:
            doc["style_playbook"] = style_playbook
        return doc
