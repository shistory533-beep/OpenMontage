"""Documentary Script Agent: structure + evidence-link enforcement.

The directing agent writes narration; this module enforces the
documentary contract deterministically:

- 9-beat structure (HOOK..PAYOFF) in order, each block fully specified,
- speaking-duration estimation (per-language WPM table) with ±10%
  target-duration enforcement,
- every factual claim linked to research claim IDs that exist,
- every numeric token in narration grounded in linked evidence
  (no fabricated statistics),
- quoted strings require attributed, evidence-linked quotes (no fake quotes),
- causal/superlative language flagged unless multi-sourced,
- repeated filler n-grams flagged,
- uncertainty preserved: unresolved claims must keep hedge language,
- unsupported claims explicitly listed, never silently passed.

Outputs: script.json (script.schema-compatible sections + documentary
extension fields), a readable markdown script, a pacing report, and a
claim mapping.
"""

from __future__ import annotations

import re
from typing import Any

from lib.editorial.contracts import (
    SCRIPT_BEATS,
    Claim,
    DocumentaryScript,
    Fact,
    NarrationBlock,
    ResearchPackage,
)

WPM_RATES = {
    "en": 150.0, "es": 160.0, "fr": 150.0, "de": 140.0,
    "hi": 140.0, "zh": 220.0, "ja": 300.0, "ar": 130.0,
}
DEFAULT_WPM = 150.0
DURATION_TOLERANCE = 0.10

CAUSAL_PHRASES = (
    "proves that", "proves the", "causes", "caused by", "is caused by",
    "studies prove", "scientists prove", "led directly to",
    "was the sole cause", "sole cause of", "proves conclusively",
)

SUPERLATIVE_PHRASES = (
    "the largest", "the smallest", "the first", "the only", "the best",
    "the worst", "the fastest", "the slowest", "the most", "the least",
    "the greatest", "never before", "no other", "unprecedented",
    "world record", "all-time",
)

ATTRIBUTION_WEASELS = (
    "scientists say", "experts say", "studies show", "research shows",
    "it is said", "many believe", "critics say", "sources say",
)

HEDGE_WORDS = (
    "may", "might", "could", "possibly", "perhaps", "likely", "unlikely",
    "unclear", "unknown", "uncertain", "debate", "disputed", "suggests",
    "suggest", "indicates", "indicate", "appears", "seems",
    "preliminary", "tentative", "hypothesis",
)

_QUOTE_RE = re.compile(r'"([^"]{4,})"')
_NUMBER_RE = re.compile(
    r"(?<![\w$])(?:\$)?\d[\d,]*(?:\.\d+)?\s?(?:%|percent|million|billion|"
    r"thousand|x\b)?",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z0-9'’-]+")


class ScriptError(ValueError):
    """Raised when a script violates the documentary contract."""


def estimate_duration_seconds(text: str, language: str = "en") -> float:
    """Deterministic speaking-time estimate from word count."""
    words = len(_WORD_RE.findall(text))
    wpm = WPM_RATES.get(language, DEFAULT_WPM)
    return round(words / wpm * 60.0, 2)


def extract_numbers(text: str) -> list[str]:
    """Numeric tokens, normalized (commas stripped, lowercased)."""
    return [m.group(0).replace(",", "").strip().lower()
            for m in _NUMBER_RE.finditer(text)]


def extract_quotes(text: str) -> list[str]:
    return [m.group(1).strip() for m in _QUOTE_RE.finditer(text)]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


STOPWORDS = frozenset(
    "a an the and or but of to in on for with from by at as is are was "
    "were be been it its this that these those we you they he she him her "
    "them our your their his her there here where when what which who whom "
    "how why not no yes if then than so such can could will would should "
    "may might must shall do does did done have has had having over under "
    "into out up down about into through during before after between more "
    "most other some such only own same very just now today".split()
)


class ScriptAgent:
    """Validates, times, and packages documentary narration blocks."""

    def __init__(self, package: ResearchPackage,
                 target_duration_seconds: float = 0.0,
                 language: str = "en") -> None:
        self.package = package
        self.target_duration_seconds = (
            target_duration_seconds or package.target_duration_seconds)
        self.language = language or package.language or "en"
        self.claims: dict[str, Claim] = {
            c["id"]: Claim.from_dict(c) for c in package.claims}
        self.facts: dict[str, Fact] = {
            f["id"]: Fact.from_dict(f) for f in package.facts}

    # -- validation --------------------------------------------------

    def validate_blocks(self, blocks: list[NarrationBlock]) -> dict[str, Any]:
        """Full contract check. Returns findings; raises on structural errors."""
        if not blocks:
            raise ScriptError("script has no narration blocks")
        self._check_beat_order(blocks)
        findings: list[dict[str, str]] = []
        for block in blocks:
            if not block.id or not block.text.strip():
                raise ScriptError("every block requires id + non-empty text")
            if block.beat not in SCRIPT_BEATS:
                raise ScriptError(
                    f"block {block.id!r} has unknown beat {block.beat!r}")
            for attr in ("chapter_id", "pacing_intent", "emotional_intent",
                         "visual_intent"):
                if not getattr(block, attr, "").strip():
                    raise ScriptError(
                        f"block {block.id!r} missing {attr}")
            findings.extend(self._check_claim_links(block))
            findings.extend(self._check_numbers(block))
            findings.extend(self._check_quotes(block))
            findings.extend(self._check_language(block))
            findings.extend(self._check_uncertainty(block))
        findings.extend(self._check_filler(blocks))
        return {"findings": findings}

    def _check_beat_order(self, blocks: list[NarrationBlock]) -> None:
        seen: list[str] = []
        for block in blocks:
            if not seen or block.beat != seen[-1]:
                seen.append(block.beat)
        order = [b for b in SCRIPT_BEATS if b in seen]
        if seen != order:
            raise ScriptError(
                f"beats out of order: {seen} (expected subsequence of "
                f"{list(SCRIPT_BEATS)})")
        if seen[0] != "hook":
            raise ScriptError("documentary must open on the HOOK beat")
        if seen[-1] != "payoff":
            raise ScriptError("documentary must close on the PAYOFF beat")

    def _linked_claims(self, block: NarrationBlock) -> list[Claim]:
        out = []
        for cid in block.claim_ids:
            claim = self.claims.get(cid)
            if claim is None:
                raise ScriptError(
                    f"block {block.id!r} links unknown claim {cid!r}")
            out.append(claim)
        return out

    def _linked_fact_statements(self, claims: list[Claim]) -> list[str]:
        texts = []
        for claim in claims:
            for fid in claim.fact_ids:
                fact = self.facts.get(fid)
                if fact is not None:
                    texts.append(_norm(fact.statement))
            for url in claim.source_ids:
                texts.append(_norm(url))
        return texts

    def _check_claim_links(self, block: NarrationBlock) -> list[dict[str, str]]:
        claims = self._linked_claims(block)
        factual = [c for c in claims if c.claim_type == "factual"]
        text = block.text.strip()
        looks_factual = bool(extract_numbers(text)) or any(
            w in _norm(text) for w in ("study", "data", "report", "found",
                                       "discovered", "measured", "recorded",
                                       "announced", "confirmed"))
        if looks_factual and not factual:
            return [{"block_id": block.id, "code": "unsupported_claim",
                     "detail": "factual-sounding narration links no factual "
                               "claim — flag as unsupported"}]
        return []

    def _check_numbers(self, block: NarrationBlock) -> list[dict[str, str]]:
        numbers = extract_numbers(block.text)
        if not numbers:
            return []
        claims = self._linked_claims(block)
        evidence = self._linked_fact_statements(claims)
        claims_text = [_norm(self.claims[cid].statement)
                       for cid in block.claim_ids if cid in self.claims]
        corpus = evidence + claims_text
        bad = [n for n in numbers
               if not any(n in stmt for stmt in corpus)]
        if bad:
            return [{"block_id": block.id, "code": "fabricated_statistic",
                     "detail": f"numbers not grounded in linked evidence: "
                               f"{sorted(set(bad))}"}]
        return []

    def _check_quotes(self, block: NarrationBlock) -> list[dict[str, str]]:
        quotes = extract_quotes(block.text)
        if not quotes:
            return []
        claims = self._linked_claims(block)
        quoted_claims = [c for c in claims if c.is_direct_quote
                         and c.attribution.strip()]
        if not quoted_claims:
            return [{"block_id": block.id, "code": "unattributed_quote",
                     "detail": f"quoted text has no attributed quote claim: "
                               f"{quotes[0][:60]}..."}]
        evidence = self._linked_fact_statements(quoted_claims)
        bad = [q for q in quotes
               if not any(_norm(q) in stmt or stmt in _norm(q)
                          for stmt in evidence)]
        if bad:
            return [{"block_id": block.id, "code": "fake_quote_risk",
                     "detail": "quoted wording not found in linked evidence"}]
        return []

    def _check_language(self, block: NarrationBlock) -> list[dict[str, str]]:
        out = []
        low = _norm(block.text)
        causal = [p for p in CAUSAL_PHRASES if p in low]
        superl = [p for p in SUPERLATIVE_PHRASES if p in low]
        weasel = [p for p in ATTRIBUTION_WEASELS if p in low]
        if causal or superl or weasel:
            claims = self._linked_claims(block)
            independent = {u for c in claims for u in c.source_ids}
            for c in claims:
                for fid in c.fact_ids:
                    fact = self.facts.get(fid)
                    if fact is not None:
                        independent.update(fact.source_ids)
            if (causal or superl) and len(independent) < 2:
                out.append({"block_id": block.id,
                            "code": "unsupported_causal_or_superlative",
                            "detail": f"strong language "
                                      f"{causal + superl} needs >=2 "
                                      f"independent sources"})
            if weasel:
                out.append({"block_id": block.id,
                            "code": "weasel_attribution",
                            "detail": f"vague attribution {weasel} — name "
                                      f"the source or cut"})
        return out

    def _check_uncertainty(self, block: NarrationBlock) -> list[dict[str, str]]:
        claims = self._linked_claims(block)
        touches_unresolved = False
        for claim in claims:
            for fid in claim.fact_ids:
                fact = self.facts.get(fid)
                if fact is not None and fact.statement_type == "unresolved":
                    touches_unresolved = True
        if touches_unresolved:
            low = _norm(block.text)
            if not any(h in low for h in HEDGE_WORDS):
                return [{"block_id": block.id, "code": "uncertainty_dropped",
                         "detail": "block states unresolved evidence without "
                                   "hedge language"}]
        return []

    def _check_filler(self,
                      blocks: list[NarrationBlock]) -> list[dict[str, str]]:
        seen: dict[str, str] = {}
        out = []
        for block in blocks:
            words = [w for w in _WORD_RE.findall(block.text.lower())
                     if w not in STOPWORDS]
            for i in range(len(words) - 3):
                gram = " ".join(words[i:i + 4])
                if gram in seen and seen[gram] != block.id:
                    out.append({"block_id": block.id,
                                "code": "repetitive_filler",
                                "detail": f"4-gram repeats block "
                                          f"{seen[gram]}: {gram!r}"})
                    break
            else:
                for i in range(len(words) - 3):
                    seen.setdefault(" ".join(words[i:i + 4]), block.id)
        return out

    # -- timing + outputs ----------------------------------------------

    def time_blocks(self, blocks: list[NarrationBlock]) -> list[NarrationBlock]:
        timed = []
        cursor = 0.0
        for block in blocks:
            est = estimate_duration_seconds(block.text, self.language)
            nb = NarrationBlock(**{**block.to_dict(),
                                   "estimated_duration_seconds": est})
            timed.append(nb)
            cursor += est
        return timed

    def check_duration(self, total: float) -> dict[str, Any]:
        target = self.target_duration_seconds
        if not target:
            return {"target": 0.0, "total": total, "within_tolerance": True,
                    "deviation": 0.0}
        deviation = (total - target) / target
        return {"target": target, "total": round(total, 2),
                "within_tolerance": abs(deviation) <= DURATION_TOLERANCE,
                "deviation": round(deviation, 3)}

    def build_script(self, title: str,
                     blocks: list[NarrationBlock]) -> DocumentaryScript:
        findings = self.validate_blocks(blocks)
        timed = self.time_blocks(blocks)
        total = round(sum(b.estimated_duration_seconds for b in timed), 2)
        duration = self.check_duration(total)
        if self.target_duration_seconds and not duration["within_tolerance"]:
            raise ScriptError(
                f"script duration {total}s misses target "
                f"{self.target_duration_seconds}s by "
                f"{duration['deviation']:+.1%} (tolerance ±10%)")
        unsupported = sorted({f["block_id"] for f in findings["findings"]
                              if f["code"] in ("unsupported_claim",
                                               "fabricated_statistic",
                                               "fake_quote_risk",
                                               "unattributed_quote")})
        mapping = {b.id: list(b.claim_ids) for b in timed}
        pacing = self._pacing_report(timed, total)
        return DocumentaryScript(
            title=title, language=self.language,
            target_duration_seconds=self.target_duration_seconds,
            total_duration_seconds=total,
            blocks=[b.to_dict() for b in timed],
            claim_mapping=mapping, unsupported_claim_ids=unsupported,
            pacing_report=pacing)

    def _pacing_report(self, blocks: list[NarrationBlock],
                       total: float) -> dict[str, Any]:
        by_beat: dict[str, dict[str, float]] = {}
        for b in blocks:
            slot = by_beat.setdefault(b.beat, {"seconds": 0.0, "blocks": 0})
            slot["seconds"] = round(
                slot["seconds"] + b.estimated_duration_seconds, 2)
            slot["blocks"] += 1
        return {"total_seconds": total, "block_count": len(blocks),
                "mean_block_seconds": round(total / len(blocks), 2)
                if blocks else 0.0,
                "beats": by_beat}

    # -- writers --------------------------------------------------------

    def script_json(self, script: DocumentaryScript) -> dict[str, Any]:
        """script.schema-compatible artifact.

        Sections carry only schema-declared fields; all documentary
        extension fields (claim links, chapter, intents, mapping, pacing)
        live under top-level ``metadata.documentary``.
        """
        sections, cursor = [], 0.0
        for b in script.blocks:
            dur = b["estimated_duration_seconds"]
            sections.append({
                "id": b["id"], "label": b["beat"],
                "text": b["text"],
                "start_seconds": round(cursor, 2),
                "end_seconds": round(cursor + dur, 2),
            })
            cursor += dur
        documentary = {
            "beats": [b["beat"] for b in script.blocks],
            "blocks": [
                {"id": b["id"], "chapter_id": b["chapter_id"],
                 "beat": b["beat"],
                 "claim_ids": b["claim_ids"],
                 "pacing_intent": b["pacing_intent"],
                 "emotional_intent": b["emotional_intent"],
                 "visual_intent": b["visual_intent"],
                 "estimated_duration_seconds":
                     b["estimated_duration_seconds"]}
                for b in script.blocks
            ],
            "claim_mapping": script.claim_mapping,
            "unsupported_claim_ids": script.unsupported_claim_ids,
            "pacing_report": script.pacing_report,
        }
        return {"version": "1.0", "title": script.title,
                "total_duration_seconds": script.total_duration_seconds,
                "sections": sections,
                "metadata": {"documentary": documentary}}

    def claim_mapping_json(self, script: DocumentaryScript) -> dict[str, Any]:
        """Standalone claim-mapping artifact (block -> claims + verdicts)."""
        return {"version": "1.0", "script_title": script.title,
                "claim_mapping": script.claim_mapping,
                "unsupported_claim_ids": script.unsupported_claim_ids}

    def readable_script(self, script: DocumentaryScript) -> str:
        lines = [f"# {script.title}", "",
                 f"_Target {script.target_duration_seconds:g}s · "
                 f"estimated {script.total_duration_seconds:g}s · "
                 f"{script.language}_", ""]
        chapter = None
        for b in script.blocks:
            if b["chapter_id"] != chapter:
                chapter = b["chapter_id"]
                lines += [f"## Chapter: {chapter}", ""]
            claims = ", ".join(b["claim_ids"]) or "none"
            lines += [f"### [{b['beat'].upper()}] {b['id']} "
                      f"({b['estimated_duration_seconds']:.1f}s)", "",
                      b["text"], "",
                      f"_Claims: {claims}_", ""]
        return "\n".join(lines)
