"""Research Agent: source-grounded evidence packaging.

The agent (LLM + retrieval tools) supplies SourceRecords, Facts, Claims,
and open questions. This module never invents evidence — it structures,
deduplicates, caches, cross-checks, and hashes what it was given:

- disk-backed source cache (content-addressed, resume-safe),
- URL + content deduplication,
- primary/secondary separation with rule-based quality weights,
- FACT / INFERENCE / OPINION / UNRESOLVED separation enforcement,
- numeric + date contradiction detection across facts sharing a subject,
- per-fact confidence from source quality (single-source capped),
- deterministic package hash pinning the whole bundle.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from lib.editorial import hashing
from lib.editorial.contracts import (
    PRIMARY_SOURCE_TYPES,
    SOURCE_TYPES,
    STATEMENT_TYPES,
    Claim,
    Contradiction,
    Fact,
    OpenQuestion,
    ResearchPackage,
    SourceRecord,
)

TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term",
    "utm_content", "gclid", "fbclid", "mc_cid", "mc_eid", "_hsenc",
})


class ResearchError(ValueError):
    """Raised when research material violates structural policy."""


def normalize_url(url: str) -> str:
    """Canonical URL form for dedupe: lower host, drop tracking params."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    kept = sorted(
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((
        parsed.scheme.lower() or "https", host, path,
        "", urlencode(kept), "",
    ))


def content_hash(text: str) -> str:
    return hashing.sha256_hex(text.strip())


def quality_weight(source: SourceRecord) -> float:
    """Deterministic source-quality weight from type + date presence.

    Primary sources outrank secondary ones; a stated publication date adds
    a small verifiability bonus. Publisher reputation is NOT guessed here —
    unknown publishers simply get no bonus.
    """
    if source.source_type in PRIMARY_SOURCE_TYPES:
        base = 1.0
    elif source.source_type in ("news", "interview"):
        base = 0.6
    elif source.source_type in ("analysis", "book", "documentary"):
        base = 0.5
    else:
        base = 0.4
    if source.date.strip():
        base = min(1.0, base + 0.1)
    return round(base, 2)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Source cache (disk-backed, resume-safe)
# ---------------------------------------------------------------------------


class SourceCache:
    """Content-addressed cache of retrieved sources.

    Layout: <dir>/records/<sha256(url)>.json + <dir>/state.json listing
    ingested URL hashes in order. Re-ingesting an identical URL is a
    no-op (dedupe); a crashed run resumes by reloading state.
    """

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.records_dir = self.cache_dir / "records"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.cache_dir / "state.json"

    def _key(self, url: str) -> str:
        return hashlib.sha256(normalize_url(url).encode()).hexdigest()

    def load_state(self) -> list[str]:
        if not self.state_path.exists():
            return []
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return list(data.get("ingested", []))
        except (OSError, ValueError):
            return []

    def _save_state(self, ingested: list[str]) -> None:
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"ingested": ingested}, indent=2),
                       encoding="utf-8")
        tmp.replace(self.state_path)

    def add(self, record: SourceRecord) -> tuple[bool, str]:
        """Store a record. Returns (is_new, key); duplicates are no-ops."""
        key = self._key(record.url)
        target = self.records_dir / f"{key}.json"
        if target.exists():
            return False, key
        record.retrieved_at = record.retrieved_at or utcnow()
        record.credibility = quality_weight(record)
        target.write_text(json.dumps(record.to_dict(), indent=2),
                          encoding="utf-8")
        ingested = self.load_state()
        ingested.append(key)
        self._save_state(ingested)
        return True, key

    def get(self, url: str) -> SourceRecord | None:
        target = self.records_dir / f"{self._key(url)}.json"
        if not target.exists():
            return None
        return SourceRecord.from_dict(
            json.loads(target.read_text(encoding="utf-8")))

    def all_records(self) -> list[SourceRecord]:
        out = []
        for key in self.load_state():
            target = self.records_dir / f"{key}.json"
            if target.exists():
                out.append(SourceRecord.from_dict(
                    json.loads(target.read_text(encoding="utf-8"))))
        return out


# ---------------------------------------------------------------------------
# Research agent
# ---------------------------------------------------------------------------


_NUM_RE = re.compile(r"([-+]?\d[\d,]*\.?\d*)\s*([a-z%°$€£/²³]*)",
                     re.IGNORECASE)


class ResearchAgent:
    """Builds a validated, hashed ResearchPackage from supplied material."""

    def __init__(self, topic: str, *, audience: str = "",
                 language: str = "en", target_duration_seconds: float = 0.0,
                 channel_niche: str = "",
                 cache_dir: str | Path | None = None) -> None:
        self.topic = topic
        self.audience = audience
        self.language = language
        self.target_duration_seconds = target_duration_seconds
        self.channel_niche = channel_niche
        self.cache = SourceCache(cache_dir) if cache_dir else None
        self._sources: dict[str, SourceRecord] = {}
        self._facts: dict[str, Fact] = {}
        self._claims: dict[str, Claim] = {}
        self._questions: list[OpenQuestion] = []

    # -- ingest ------------------------------------------------------

    def ingest_sources(self, records: list[SourceRecord]) -> dict[str, Any]:
        """Validate + dedupe source records. Returns {added, duplicates}."""
        added, duplicates = [], []
        for rec in records:
            self._check_source(rec)
            key = normalize_url(rec.url)
            is_dup = key in self._sources or any(
                normalize_url(s.url) == key for s in self._sources.values()
            )
            content_dup = any(
                s.title.strip().lower() == rec.title.strip().lower()
                and s.publisher == rec.publisher and rec.title.strip()
                for s in self._sources.values()
            )
            if is_dup or content_dup:
                duplicates.append(rec.url)
                continue
            rec.retrieved_at = rec.retrieved_at or utcnow()
            rec.credibility = quality_weight(rec)
            self._sources[key] = rec
            if self.cache:
                self.cache.add(rec)
            added.append(rec.url)
        return {"added": added, "duplicates": duplicates}

    def add_facts(self, facts: list[Fact]) -> None:
        for fact in facts:
            self._check_fact(fact)
            if fact.id in self._facts:
                raise ResearchError(f"duplicate fact id: {fact.id!r}")
            self._facts[fact.id] = fact

    def add_claims(self, claims: list[Claim]) -> None:
        for claim in claims:
            self._check_claim(claim)
            if claim.id in self._claims:
                raise ResearchError(f"duplicate claim id: {claim.id!r}")
            self._claims[claim.id] = claim

    def add_open_questions(self, questions: list[OpenQuestion]) -> None:
        self._questions.extend(questions)

    # -- validation --------------------------------------------------

    @staticmethod
    def _check_source(rec: SourceRecord) -> None:
        missing = [f for f in SourceRecord.required_fields()
                   if not getattr(rec, f, "").strip()]
        if missing:
            raise ResearchError(
                f"source {rec.url!r} missing required fields: {missing}")
        if rec.source_type not in SOURCE_TYPES:
            raise ResearchError(
                f"source {rec.url!r} has unknown source_type "
                f"{rec.source_type!r}")
        if not rec.url.lower().startswith(("http://", "https://")):
            raise ResearchError(f"source URL must be http(s): {rec.url!r}")

    def _check_fact(self, fact: Fact) -> None:
        if not fact.id or not fact.statement.strip():
            raise ResearchError("fact requires id + non-empty statement")
        if fact.statement_type not in STATEMENT_TYPES:
            raise ResearchError(
                f"fact {fact.id!r} has unknown statement_type "
                f"{fact.statement_type!r}; must be one of {STATEMENT_TYPES}")
        if not fact.source_ids:
            raise ResearchError(
                f"fact {fact.id!r} cites no sources — never invent evidence")
        unknown = [s for s in fact.source_ids
                   if self._source_by_url(s) is None]
        if unknown:
            raise ResearchError(
                f"fact {fact.id!r} cites unknown sources: {unknown}")
        if fact.statement_type == "opinion" and fact.numeric_value is not None:
            raise ResearchError(
                f"fact {fact.id!r}: opinions must not carry numeric values")
        if fact.statement_type == "inference" and len(fact.source_ids) < 1:
            raise ResearchError(
                f"fact {fact.id!r}: inferences must cite their basis")

    def _source_ids(self) -> set[str]:
        return {s.url for s in self._sources.values()}

    def _check_claim(self, claim: Claim) -> None:
        if not claim.id or not claim.statement.strip():
            raise ResearchError("claim requires id + non-empty statement")
        if claim.claim_type not in ("factual", "opinion"):
            raise ResearchError(
                f"claim {claim.id!r} claim_type must be factual|opinion")
        if claim.claim_type == "factual" and not claim.fact_ids:
            raise ResearchError(
                f"factual claim {claim.id!r} links no facts — "
                "every major claim must be traceable to evidence")
        unknown_facts = [f for f in claim.fact_ids if f not in self._facts]
        if unknown_facts:
            raise ResearchError(
                f"claim {claim.id!r} links unknown facts: {unknown_facts}")
        unknown_sources = [s for s in claim.source_ids
                           if s not in self._source_ids()]
        if unknown_sources:
            raise ResearchError(
                f"claim {claim.id!r} cites unknown sources: {unknown_sources}")
        if claim.is_direct_quote and not claim.attribution.strip():
            raise ResearchError(
                f"claim {claim.id!r}: direct quotes require attribution")

    # -- analysis ----------------------------------------------------

    def detect_contradictions(self) -> list[Contradiction]:
        """Numeric + date conflicts between facts sharing a subject_key."""
        out: list[Contradiction] = []
        by_subject: dict[str, list[Fact]] = {}
        for fact in self._facts.values():
            if fact.statement_type not in ("fact", "inference"):
                continue
            if fact.subject_key.strip():
                by_subject.setdefault(fact.subject_key.strip().lower(),
                                      []).append(fact)
        n = 0
        for subject, facts in sorted(by_subject.items()):
            numerics = [(f, f.numeric_value or 0.0,
                         (f.numeric_unit or "").lower())
                        for f in facts if f.numeric_value is not None]
            units: dict[str, list] = {}
            for f, v, u in numerics:
                units.setdefault(u, []).append((f, v))
            for unit, pairs in units.items():
                vals = [v for _, v in pairs]
                if len(vals) > 1 and (max(vals) - min(vals)) > 0.05 * max(
                        abs(max(vals, key=abs)), 1e-9):
                    n += 1
                    out.append(Contradiction(
                        id=f"contradiction-{n}",
                        subject_key=subject,
                        description=(
                            f"Conflicting numeric values for {subject!r} "
                            f"(unit {unit or 'unspecified'}): "
                            + ", ".join(
                                f"{f.id}={v:g}" for f, v in pairs)),
                        fact_ids=[f.id for f, _ in pairs],
                        values=[f"{f.id}={v:g}{unit}" for f, v in pairs],
                    ))
            dated = [(f, f.date_value) for f in facts if f.date_value.strip()]
            dates = {d for _, d in dated}
            if len(dates) > 1:
                n += 1
                out.append(Contradiction(
                    id=f"contradiction-{n}",
                    subject_key=subject,
                    description=(
                        f"Conflicting dates for {subject!r}: "
                        + ", ".join(f"{f.id}={d}" for f, d in dated)),
                    fact_ids=[f.id for f, _ in dated],
                    values=[f"{f.id}={d}" for f, d in dated],
                ))
        return out

    def fact_confidence(self, fact: Fact) -> float:
        """Mean source weight, capped at 0.7 for single-source facts."""
        weights = []
        for s in fact.source_ids:
            rec = self._source_by_url(s)
            if rec is not None:
                weights.append(quality_weight(rec))
        if not weights:
            return 0.0
        conf = sum(weights) / len(weights)
        if len(weights) == 1:
            conf = min(conf, 0.7)
        return round(conf, 2)

    def _source_by_url(self, url: str) -> SourceRecord | None:
        key = normalize_url(url)
        if key in self._sources:
            return self._sources[key]
        for rec in self._sources.values():
            if normalize_url(rec.url) == key:
                return rec
        return None

    def build_package(self) -> ResearchPackage:
        """Validate everything, compute confidence, hash deterministically."""
        if not self._sources:
            raise ResearchError("cannot build package with zero sources")
        contradictions = self.detect_contradictions()
        contradicted_facts = {fid for c in contradictions for fid in c.fact_ids}
        facts_out = []
        for fact in self._facts.values():
            d = fact.to_dict()
            d["confidence"] = self.fact_confidence(fact)
            d["contradicted"] = fact.id in contradicted_facts
            facts_out.append(d)
        sources_out = [s.to_dict() for _, s in
                       sorted(self._sources.items())]
        claims_out = [self._claims[k].to_dict() for k in
                      sorted(self._claims)]
        graph = self._evidence_graph()
        pkg = ResearchPackage(
            topic=self.topic, audience=self.audience,
            language=self.language,
            target_duration_seconds=self.target_duration_seconds,
            channel_niche=self.channel_niche,
            sources=sources_out, facts=facts_out, claims=claims_out,
            evidence_graph=graph,
            contradictions=[c.to_dict() for c in contradictions],
            open_questions=[q.to_dict() for q in self._questions],
            created_at=utcnow(),
        )
        payload = pkg.to_dict()
        payload.pop("package_hash", None)
        payload.pop("created_at", None)
        pkg.package_hash = hashing.package_hash(payload)
        return pkg

    def _evidence_graph(self) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, str]] = []
        for key, rec in self._sources.items():
            nodes[f"source:{rec.url}"] = {"kind": "source", "key": key,
                                          "primary": rec.source_type
                                          in PRIMARY_SOURCE_TYPES}
        for fid, fact in self._facts.items():
            nodes[f"fact:{fid}"] = {"kind": fact.statement_type}
            for url in fact.source_ids:
                edges.append({"from": f"fact:{fid}",
                              "to": f"source:{url}", "rel": "supported_by"})
        for cid, claim in self._claims.items():
            nodes[f"claim:{cid}"] = {"kind": claim.claim_type,
                                     "critical": claim.critical}
            for fid in claim.fact_ids:
                edges.append({"from": f"claim:{cid}", "to": f"fact:{fid}",
                              "rel": "based_on"})
            for url in claim.source_ids:
                edges.append({"from": f"claim:{cid}", "to": f"source:{url}",
                              "rel": "cited_in"})
        return {"nodes": nodes, "edges": edges}

    # -- resume --------------------------------------------------------

    def save_state(self, path: str | Path) -> Path:
        """Persist ingested material so an interrupted run can resume."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "topic": self.topic, "audience": self.audience,
            "language": self.language,
            "target_duration_seconds": self.target_duration_seconds,
            "channel_niche": self.channel_niche,
            "sources": [s.to_dict() for s in self._sources.values()],
            "facts": [f.to_dict() for f in self._facts.values()],
            "claims": [c.to_dict() for c in self._claims.values()],
            "open_questions": [q.to_dict() for q in self._questions],
        }
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(target)
        return target

    @classmethod
    def resume(cls, path: str | Path,
               cache_dir: str | Path | None = None) -> "ResearchAgent":
        """Reload a saved run without re-retrieving anything."""
        state = json.loads(Path(path).read_text(encoding="utf-8"))
        agent = cls(state["topic"], audience=state.get("audience", ""),
                    language=state.get("language", "en"),
                    target_duration_seconds=state.get(
                        "target_duration_seconds", 0.0),
                    channel_niche=state.get("channel_niche", ""),
                    cache_dir=cache_dir)
        agent.ingest_sources(
            [SourceRecord.from_dict(s) for s in state.get("sources", [])])
        agent.add_facts([Fact.from_dict(f) for f in state.get("facts", [])])
        agent.add_claims([Claim.from_dict(c) for c in state.get("claims", [])])
        agent.add_open_questions(
            [OpenQuestion.from_dict(q) for q in state.get("open_questions",
                                                          [])])
        return agent
