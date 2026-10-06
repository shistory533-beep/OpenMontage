"""Visual relevance scoring above existing retrieval.

Explainable, deterministic scoring of retrieval candidates
(NormalizedAsset dicts from FootageHub / clip_search) against one
VisualRequirement. Every score decomposes into named components with
fixed weights (summing to 1.0); penalties are explicit negative
components, never hidden. Ordering is fully stable
(sort by (-final_score, asset_id)) — no randomness, no provider bias:
provider_reliability defaults to a uniform constant for every provider
and only varies when the caller passes an explicit reliability table.

Decisions: pass (>= 0.6) | weak (>= 0.4) | wrong (< 0.4) | missing
(no candidates at all — decided by score_requirement, never invented).

Scoring details are stored back into editorial artifacts via
attach_scores(), so the storyboard/footage stages carry the full
breakdown for audit.
"""

from __future__ import annotations

import re
from typing import Any

COMPONENT_WEIGHTS = {
    "semantic_relevance": 0.18,
    "evidence_relevance": 0.14,
    "visual_subject_relevance": 0.12,
    "geographic_relevance": 0.08,
    "temporal_relevance": 0.08,
    "shot_function_relevance": 0.08,
    "duration_suitability": 0.07,
    "resolution": 0.07,
    "quality": 0.05,
    "rights_confidence": 0.08,
    "continuity": 0.03,
    "provider_reliability": 0.02,
}

PASS_THRESHOLD = 0.6
WEAK_THRESHOLD = 0.4

REPETITION_PENALTY = 0.05   # per prior use of this asset in-episode (cap 0.25)
PRIOR_USAGE_PENALTY = 0.15  # asset already used in another episode
DEFAULT_RELIABILITY = 0.7   # uniform for all providers (no-bias default)

_VERIFIED_RIGHTS = ("verified_public_domain", "verified_cc",
                    "verified_licensed")


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def _overlap_ratio(needles: set[str], haystack: set[str]) -> float:
    if not needles:
        return 0.5  # no constraint stated: neutral, not penalized
    return round(len(needles & haystack) / len(needles), 3)


def _asset_text(asset: dict[str, Any]) -> str:
    extra = asset.get("extra") or {}
    bits = [asset.get("title", ""), asset.get("description", ""),
            extra.get("source_tags", ""), extra.get("tags", ""),
            asset.get("creator", "")]
    if isinstance(bits[3], list):
        bits[3] = " ".join(str(t) for t in bits[3])
    return " ".join(str(b) for b in bits if b)


class VisualScorer:
    """Stateless scorer. All episode/global state arrives via arguments."""

    def __init__(self,
                 reliability_table: dict[str, float] | None = None) -> None:
        self.reliability_table = dict(reliability_table or {})

    # -- components --------------------------------------------------------

    def components(self, requirement: dict[str, Any],
                   asset: dict[str, Any],
                   context: dict[str, Any] | None = None
                   ) -> dict[str, float]:
        ctx = context or {}
        text = _asset_text(asset)
        tokens = _tokens(text)
        terms = set(requirement.get("positive_search_terms", []))
        subject_tokens = _tokens(requirement.get("subject", ""))
        comps: dict[str, float] = {}

        comps["semantic_relevance"] = _overlap_ratio(terms, tokens)

        evidence_urls = set(requirement.get("evidence_source_ids", []))
        asset_urls = {asset.get("source_url", ""),
                      asset.get("download_url", "")} - {""}
        if evidence_urls and asset_urls & evidence_urls:
            comps["evidence_relevance"] = 1.0
        elif terms and _overlap_ratio(terms, tokens) >= 0.5:
            comps["evidence_relevance"] = 0.6
        else:
            comps["evidence_relevance"] = 0.3

        comps["visual_subject_relevance"] = _overlap_ratio(
            subject_tokens, tokens)

        location = (requirement.get("location") or "").strip()
        if not location:
            comps["geographic_relevance"] = 0.7  # no constraint: neutral-high
        else:
            loc_tokens = _tokens(location)
            hit = _overlap_ratio(loc_tokens, tokens)
            comps["geographic_relevance"] = 1.0 if hit >= 1.0 else (
                0.5 if hit > 0 else 0.0)

        period = (requirement.get("period") or "").strip()
        extra = asset.get("extra") or {}
        asset_year = str(extra.get("year", "") or extra.get("date", "") or "")
        if not period:
            comps["temporal_relevance"] = 0.7
        elif asset_year and period in asset_year:
            comps["temporal_relevance"] = 1.0
        elif asset_year:
            comps["temporal_relevance"] = 0.3
        else:
            comps["temporal_relevance"] = 0.5  # undated asset, dated need

        want = (requirement.get("preferred_media_type") or "any").lower()
        kind = (asset.get("kind") or asset.get("media_type") or "").lower()
        if want in ("any", "") or want == kind:
            comps["shot_function_relevance"] = 1.0
        else:
            comps["shot_function_relevance"] = 0.4

        dur = float(asset.get("duration") or 0.0)
        want_min = float(requirement.get("minimum_duration_seconds") or 0.0)
        want_desired = float(requirement.get("desired_duration_seconds")
                             or 0.0)
        if kind == "image" or (dur <= 0 and want == "image"):
            comps["duration_suitability"] = 1.0 if want in (
                "image", "any") else 0.4
        elif dur <= 0:
            comps["duration_suitability"] = 0.3  # unknown duration
        elif dur < want_min:
            comps["duration_suitability"] = 0.2  # insufficient duration
        elif want_desired and dur > 2 * want_desired:
            comps["duration_suitability"] = 0.5
        else:
            comps["duration_suitability"] = 1.0

        w, h = int(asset.get("width") or 0), int(asset.get("height") or 0)
        mp = w * h / 1e6
        comps["resolution"] = round(min(1.0, mp / 2.0), 3) if mp > 0 else 0.3

        comps["quality"] = 1.0 if (w > 0 and h > 0
                                   and asset.get("format")) else 0.4

        rights = asset.get("rights_status", "unknown")
        if rights in _VERIFIED_RIGHTS:
            comps["rights_confidence"] = 1.0
        elif rights == "restricted":
            comps["rights_confidence"] = 0.0
        else:
            comps["rights_confidence"] = 0.4

        prev_provider = (ctx.get("previous_pick") or {}).get("provider", "")
        if not prev_provider:
            comps["continuity"] = 0.5
        else:
            comps["continuity"] = (0.8 if asset.get("provider") ==
                                   prev_provider else 0.5)

        provider = asset.get("provider", "")
        comps["provider_reliability"] = self.reliability_table.get(
            provider, DEFAULT_RELIABILITY)

        uses = int((ctx.get("episode_usage_counts") or {}).get(
            asset.get("asset_id", ""), 0))
        comps["repetition_penalty"] = -round(
            min(0.25, REPETITION_PENALTY * uses), 3)
        history = set(ctx.get("global_usage_history") or [])
        comps["prior_usage_penalty"] = (
            -PRIOR_USAGE_PENALTY
            if asset.get("asset_id") in history else 0.0)
        return comps

    # -- final score + decision --------------------------------------------

    def final_score(self, comps: dict[str, float]) -> float:
        total = sum(comps.get(k, 0.0) * w
                    for k, w in COMPONENT_WEIGHTS.items())
        total += comps.get("repetition_penalty", 0.0)
        total += comps.get("prior_usage_penalty", 0.0)
        return round(max(0.0, min(1.0, total)), 3)

    @staticmethod
    def decide(final: float) -> str:
        if final >= PASS_THRESHOLD:
            return "pass"
        if final >= WEAK_THRESHOLD:
            return "weak"
        return "wrong"

    def reason(self, comps: dict[str, float], decision: str) -> str:
        weighted = {k: round(comps.get(k, 0.0) * COMPONENT_WEIGHTS[k], 3)
                    for k in COMPONENT_WEIGHTS}
        ranked = sorted(weighted.items(), key=lambda kv: (-kv[1], kv[0]))
        top = ", ".join(f"{k}={v:.2f}" for k, v in ranked[:2])
        bottom = f"{ranked[-1][0]}={ranked[-1][1]:.2f}"
        pens = [f"{k}={comps[k]:+.2f}" for k in
                ("repetition_penalty", "prior_usage_penalty")
                if comps.get(k)]
        suffix = f"; penalties: {', '.join(pens)}" if pens else ""
        return (f"decision={decision} (strongest {top}; "
                f"weakest {bottom}{suffix})")

    def score_asset(self, requirement: dict[str, Any],
                    asset: dict[str, Any],
                    context: dict[str, Any] | None = None) -> dict[str, Any]:
        comps = self.components(requirement, asset, context)
        final = self.final_score(comps)
        decision = self.decide(final)
        notes: list[str] = []
        # Relevance gate: zero subject overlap can never pass on technical
        # merit alone — the clip is simply the wrong footage.
        if (comps["semantic_relevance"] <= 0
                and comps["visual_subject_relevance"] <= 0):
            decision = self._cap(decision, "wrong")
            notes.append("gate: no subject overlap with requirement")
        # Rights gate: a verified-rights requirement cannot use unverified
        # or restricted media; permissive tolerates unknown, never restricted.
        want_rights = (requirement.get("rights_requirement")
                       or "verified").lower()
        rights = asset.get("rights_status", "unknown")
        if want_rights == "verified" and rights not in _VERIFIED_RIGHTS:
            decision = self._cap(decision, "wrong")
            notes.append(f"gate: rights_status={rights} fails "
                         f"verified requirement")
        elif rights == "restricted":
            decision = self._cap(decision, "weak")
            notes.append("gate: restricted rights need human clearance")
        # Geography gate: an explicit location the asset does not match
        # caps at weak — right subject, wrong place.
        if ((requirement.get("location") or "").strip()
                and comps["geographic_relevance"] <= 0):
            decision = self._cap(decision, "weak")
            notes.append("gate: location mismatch")
        reason = self.reason(comps, decision)
        if notes:
            reason += "; " + "; ".join(notes)
        return {"requirement_id": requirement.get("id", ""),
                "asset_id": asset.get(
                    "asset_id",
                    f"{asset.get('provider', '')}_"
                    f"{asset.get('source_id', '')}"),
                "final_score": final, "components": comps,
                "reason": reason,
                "decision": decision}

    @staticmethod
    def _cap(decision: str, cap: str) -> str:
        order = ("pass", "weak", "wrong", "missing")
        return cap if order.index(decision) < order.index(cap) else decision

    def score_requirement(self, requirement: dict[str, Any],
                          candidates: list[dict[str, Any]],
                          context: dict[str, Any] | None = None
                          ) -> dict[str, Any]:
        """Score every candidate; stable order; MISSING when empty."""
        if not candidates:
            return {"requirement_id": requirement.get("id", ""),
                    "decision": "missing", "scores": [],
                    "reason": "no candidates retrieved for requirement"}
        scored = [self.score_asset(requirement, a, context)
                  for a in candidates]
        scored.sort(key=lambda s: (-s["final_score"], s["asset_id"]))
        return {"requirement_id": requirement.get("id", ""),
                "decision": scored[0]["decision"], "scores": scored,
                "reason": f"best={scored[0]['asset_id']} "
                          f"({scored[0]['final_score']:.2f}); "
                          f"{scored[0]['reason']}"}

    # -- artifact storage ----------------------------------------------------

    def attach_scores(self, storyboard: dict[str, Any],
                      scoreboards: list[dict[str, Any]]) -> dict[str, Any]:
        """Embed scoring breakdowns into the storyboard artifact (audit)."""
        by_req = {s["requirement_id"]: s for s in scoreboards}
        out_reqs = []
        for req in storyboard.get("requirements", []):
            entry = dict(req)
            board = by_req.get(req.get("id", ""))
            entry["scoring"] = board or {"decision": "missing",
                                         "scores": [],
                                         "reason": "not scored"}
            out_reqs.append(entry)
        out = dict(storyboard)
        out["requirements"] = out_reqs
        out["scoring_summary"] = {
            s["requirement_id"]: s["decision"] for s in scoreboards}
        return out
