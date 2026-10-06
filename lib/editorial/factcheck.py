"""Fact Check Agent: independent claim verification.

Takes a DocumentaryScript and the ResearchPackage it was built from, and
classifies every factual claim independently of the script agent:

  verified | partially_verified | contradicted | unsupported |
  opinion | requires_research

Each verdict cites claim id, statement, source ids, evidence summary,
confidence, a machine-readable problem code, and a recommendation.
Critical contradicted/unsupported claims block approval
(blocks_approval=True; report.passed=False while any remain).

What this module will NOT do, by construction:
- it never rewrites a claim (no replacement text is ever generated),
- it never invents replacement facts (recommendations are actions:
  cut | re-source | hedge | research | none),
- it never consults anything except the script + package it was given
  (the package_hash is pinned on the report).
"""

from __future__ import annotations

import re
from functools import partial
from typing import Any

from lib.editorial.contracts import (
    CLAIM_VERDICTS,
    Claim,
    ClaimVerdict,
    Fact,
    FactCheckReport,
    ResearchPackage,
)
from lib.editorial.script_agent import (
    CAUSAL_PHRASES,
    SUPERLATIVE_PHRASES,
    extract_numbers,
    extract_quotes,
)


class FactCheckError(ValueError):
    """Raised on malformed inputs (never on a failed check)."""


_ATTRIBUTION_RE = re.compile(
    r"according to ([A-Z][\w&'’.\-]*(?:\s+[A-Z][\w&'’.\-]*){0,4})"
    r"|([A-Z][\w&'’.\-]*(?:\s+[A-Z][\w&'’.\-]*){0,2})\s+"
    r"(said|says|reported|reports|found|announced|confirmed|warned)",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _independent_source_count(claim: Claim,
                              facts: dict[str, Fact]) -> int:
    urls = set(claim.source_ids)
    for fid in claim.fact_ids:
        fact = facts.get(fid)
        if fact is not None:
            urls.update(fact.source_ids)
    return len(urls)


class FactCheckAgent:
    """Independent verifier. Reads script + package; writes only verdicts."""

    def check(self, script_blocks: list[dict[str, Any]],
            package: ResearchPackage) -> FactCheckReport:
        if not isinstance(package, ResearchPackage):
            raise FactCheckError("fact-check requires a ResearchPackage")
        claims = {c["id"]: Claim.from_dict(c) for c in package.claims}
        facts = {f["id"]: Fact.from_dict(f) for f in package.facts}
        contradicted_facts = {
            fid for c in package.contradictions for fid in
            (c.get("fact_ids") or [])}
        verdicts: list[ClaimVerdict] = []
        for block in script_blocks:
            for cid in block.get("claim_ids", []):
                claim = claims.get(cid)
                if claim is None:
                    verdicts.append(ClaimVerdict(
                        claim_id=cid,
                        statement=f"(claim {cid} not found in package)",
                        verdict="unsupported", source_ids=[],
                        evidence_summary="claim id has no package entry",
                        confidence=0.0, problem="source_mismatch",
                        recommendation="cut", blocks_approval=True))
                    continue
                verdicts.append(self._verdict_claim(
                    claim, claims, facts, contradicted_facts, package))
        blocking = sorted(v.claim_id for v in verdicts if v.blocks_approval)
        return FactCheckReport(
            script_title="", package_hash=package.package_hash,
            verdicts=[v.to_dict() for v in verdicts],
            blocking_claim_ids=blocking, passed=not blocking)

    # -- per-claim classification ------------------------------------

    def _verdict_claim(self, claim: Claim, claims: dict[str, Claim],
                       facts: dict[str, Fact],
                       contradicted_facts: set[str],
                       package: ResearchPackage) -> ClaimVerdict:
        base: dict[str, Any] = dict(
            claim_id=claim.id, statement=claim.statement,
            source_ids=list(claim.source_ids))
        publishers = {_norm(s.get("publisher", ""))
                      for s in package.sources} - {""}
        if claim.claim_type == "opinion":
            return ClaimVerdict(**base, verdict="opinion",
                                evidence_summary="opinion: no verification "
                                "required or performed",
                                confidence=1.0, problem="",
                                recommendation="none", blocks_approval=False)
        linked = [facts[fid] for fid in claim.fact_ids if fid in facts]
        missing = [fid for fid in claim.fact_ids if fid not in facts]
        if missing:
            return ClaimVerdict(
                **base, verdict="unsupported",
                evidence_summary=f"linked facts missing from package: "
                                 f"{missing}",
                confidence=0.0, problem="source_mismatch",
                recommendation="re-source",
                # structural break: the claim points at evidence that
                # does not exist — always blocking, critical or not.
                blocks_approval=True)
        if not linked and not claim.source_ids:
            return ClaimVerdict(
                **base, verdict="unsupported",
                evidence_summary="no linked facts and no cited sources",
                confidence=0.0, problem="no_evidence",
                recommendation="cut", blocks_approval=True)
        if any(f.id in contradicted_facts for f in linked):
            return ClaimVerdict(
                **base, verdict="contradicted",
                evidence_summary="linked evidence is contradicted by "
                                 "another package source; see contradictions",
                confidence=0.0, problem="contradiction",
                recommendation="research", blocks_approval=True)
        if any(f.statement_type == "unresolved" for f in linked):
            blocks = claim.critical
            return ClaimVerdict(
                **base, verdict="requires_research",
                evidence_summary="linked evidence is unresolved — the "
                                 "question is still open",
                confidence=round(min(
                    [f.confidence for f in linked] or [0.0]), 2),
                problem="open_question", recommendation="research",
                blocks_approval=blocks)
        detectors = (
            self._numeric_discrepancy,
            self._date_discrepancy,
            partial(self._attribution_error, publishers=publishers),
            self._fake_quote,
            self._causal_overclaim,
            self._unsupported_superlative,
        )
        for detector in detectors:
            hit = detector(claim, linked, facts)
            if hit is not None:
                return hit
        confidence = round(min([f.confidence for f in linked] or [1.0]), 2)
        summary = "; ".join(
            f"{f.id} ({f.statement_type}, conf {f.confidence})"
            for f in linked) or "direct source citation"
        return ClaimVerdict(**base, verdict="verified",
                            evidence_summary=summary, confidence=confidence,
                            problem="", recommendation="none",
                            blocks_approval=False)

    # -- detectors (each returns a ClaimVerdict or None) --------------

    def _evidence_corpus(self, claim: Claim,
                         linked: list[Fact]) -> list[str]:
        return [_norm(f.statement) for f in linked]

    def _numeric_discrepancy(self, claim: Claim, linked: list[Fact],
                             facts: dict[str, Fact]) -> ClaimVerdict | None:
        # Year-shaped tokens belong to the date detector below, not here.
        numbers = [n for n in extract_numbers(claim.statement)
                   if not re.fullmatch(r"(1[5-9]\d\d|20\d\d|21\d\d)", n)]
        if not numbers:
            return None
        corpus = self._evidence_corpus(claim, linked)
        bad = [n for n in numbers if not any(n in stmt for stmt in corpus)]
        if not bad:
            return None
        return ClaimVerdict(
            claim_id=claim.id, statement=claim.statement,
            source_ids=list(claim.source_ids), verdict="unsupported",
            evidence_summary=f"numbers not present in linked evidence: "
                             f"{sorted(set(bad))}",
            confidence=0.0, problem="numeric_discrepancy",
            recommendation="re-source", blocks_approval=True)

    def _date_discrepancy(self, claim: Claim, linked: list[Fact],
                          facts: dict[str, Fact]) -> ClaimVerdict | None:
        years = re.findall(r"\b(1[5-9]\d\d|20\d\d|21\d\d)\b", claim.statement)
        if not years:
            return None
        corpus = self._evidence_corpus(claim, linked)
        bad = [y for y in years if not any(y in stmt for stmt in corpus)]
        if not bad:
            return None
        return ClaimVerdict(
            claim_id=claim.id, statement=claim.statement,
            source_ids=list(claim.source_ids), verdict="unsupported",
            evidence_summary=f"dates not present in linked evidence: "
                             f"{sorted(set(bad))}",
            confidence=0.0, problem="date_discrepancy",
            recommendation="re-source", blocks_approval=True)

    def _attribution_error(self, claim: Claim, linked: list[Fact],
                           facts: dict[str, Fact],
                           publishers: set[str]) -> ClaimVerdict | None:
        """'According to X' where X published none of the cited evidence.

        Skipped for direct-quote claims with a structured attribution —
        the quote detector owns that case.
        """
        if claim.is_direct_quote and claim.attribution.strip():
            return None
        named = set()
        for m in _ATTRIBUTION_RE.finditer(claim.statement):
            name = m.group(1) or m.group(2)
            if name:
                named.add(_norm(name))
        named |= {_norm(claim.attribution)} if claim.attribution.strip() \
            else set()
        if not named:
            return None
        if not claim.source_ids and not linked:
            return ClaimVerdict(
                claim_id=claim.id, statement=claim.statement,
                source_ids=list(claim.source_ids),
                verdict="unsupported",
                evidence_summary="names a source but cites none",
                confidence=0.0, problem="attribution_error",
                recommendation="re-source", blocks_approval=True)
        unmatched = sorted(
            n for n in named
            if not any(n in pub or pub in n for pub in publishers))
        if unmatched:
            return ClaimVerdict(
                claim_id=claim.id, statement=claim.statement,
                source_ids=list(claim.source_ids),
                verdict="unsupported",
                evidence_summary=f"attributed to {unmatched}, who published "
                                 f"none of the cited evidence",
                confidence=0.0, problem="attribution_error",
                recommendation="re-source", blocks_approval=True)
        return None

    def _fake_quote(self, claim: Claim, linked: list[Fact],
                    facts: dict[str, Fact]) -> ClaimVerdict | None:
        quotes = extract_quotes(claim.statement)
        if not quotes or not claim.is_direct_quote:
            if quotes and not claim.is_direct_quote:
                return ClaimVerdict(
                    claim_id=claim.id, statement=claim.statement,
                    source_ids=list(claim.source_ids),
                    verdict="unsupported",
                    evidence_summary="quoted wording with no attributed "
                                     "quote claim",
                    confidence=0.0, problem="fake_quote_risk",
                    recommendation="cut", blocks_approval=True)
            return None
        corpus = self._evidence_corpus(claim, linked)
        bad = [q for q in quotes
               if not any(_norm(q) in stmt or stmt in _norm(q)
                          for stmt in corpus)]
        if bad:
            return ClaimVerdict(
                claim_id=claim.id, statement=claim.statement,
                source_ids=list(claim.source_ids),
                verdict="unsupported",
                evidence_summary="quoted wording not found in cited sources",
                confidence=0.0, problem="fake_quote_risk",
                recommendation="cut", blocks_approval=True)
        return None

    def _causal_overclaim(self, claim: Claim, linked: list[Fact],
                          facts: dict[str, Fact]) -> ClaimVerdict | None:
        low = _norm(claim.statement)
        if not any(p in low for p in CAUSAL_PHRASES):
            return None
        n = _independent_source_count(claim, facts)
        if n == 0:
            return ClaimVerdict(
                claim_id=claim.id, statement=claim.statement,
                source_ids=list(claim.source_ids),
                verdict="unsupported",
                evidence_summary="causal claim with no supporting evidence",
                confidence=0.0, problem="causal_overclaim",
                recommendation="cut", blocks_approval=True)
        if n == 1:
            return ClaimVerdict(
                claim_id=claim.id, statement=claim.statement,
                source_ids=list(claim.source_ids),
                verdict="partially_verified",
                evidence_summary="causal claim with a single source — "
                                 "correlation is not causation",
                confidence=0.4, problem="causal_overclaim",
                recommendation="hedge", blocks_approval=False)
        return None

    def _unsupported_superlative(self, claim: Claim, linked: list[Fact],
                                 facts: dict[str, Fact]) -> ClaimVerdict | None:
        low = _norm(claim.statement)
        if not any(p in low for p in SUPERLATIVE_PHRASES):
            return None
        n = _independent_source_count(claim, facts)
        if n < 2:
            return ClaimVerdict(
                claim_id=claim.id, statement=claim.statement,
                source_ids=list(claim.source_ids),
                verdict="partially_verified",
                evidence_summary=f"superlative backed by {n} independent "
                                 f"source(s); needs >= 2",
                confidence=0.4, problem="unsupported_superlative",
                recommendation="hedge", blocks_approval=False)
        return None
