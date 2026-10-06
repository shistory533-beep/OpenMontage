"""Editorial intelligence contracts for the YouTube documentary factory.

Plain-data contracts (JSON round-trippable) for the research -> evidence ->
script -> fact-check -> storyboard -> visual-scoring chain. Same pattern as
lib/tts_hub/contracts.py and lib/footage_hub/contracts.py: dataclasses with
to_dict / from_dict / required_fields, no provider imports, no network.

These contracts carry structure, linkage, and verdicts. They never invent
content: every Fact/Claim must reference source_ids that exist in the same
ResearchPackage, and every downstream verdict cites the evidence it used.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Vocabularies (single source of truth; validators reference these)
# ---------------------------------------------------------------------------

STATEMENT_TYPES = ("fact", "inference", "opinion", "unresolved")

PRIMARY_SOURCE_TYPES = (
    "government",
    "official_statistics",
    "company_filing",
    "academic",
    "court_document",
    "dataset",
    "original_report",
)

SECONDARY_SOURCE_TYPES = (
    "news",
    "analysis",
    "interview",
    "book",
    "documentary",
    "other_secondary",
)

SOURCE_TYPES = PRIMARY_SOURCE_TYPES + SECONDARY_SOURCE_TYPES

CLAIM_VERDICTS = (
    "verified",
    "partially_verified",
    "contradicted",
    "unsupported",
    "opinion",
    "requires_research",
)

# Verdicts that fail a claim. Approval-blocking is decided per-claim by
# FactCheckAgent (contradicted always blocks; unsupported/requires_research
# block when the claim is critical).
FAILING_VERDICTS = ("contradicted", "unsupported", "requires_research")

SCRIPT_BEATS = (
    "hook",
    "question",
    "setup",
    "discovery",
    "escalation",
    "mechanism",
    "consequence",
    "transformation",
    "payoff",
)

SHOT_FUNCTIONS = (
    "establishing",
    "context",
    "evidence",
    "mechanism",
    "human_impact",
    "detail",
    "transition",
    "comparison",
    "map",
    "chart",
    "archival",
    "consequence",
    "payoff",
)

AVAILABILITY_STATES = ("available", "uncertain", "missing")

SCORING_DECISIONS = ("pass", "weak", "wrong", "missing")


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------


@dataclass
class SourceRecord:
    title: str = ""
    url: str = ""
    publisher: str = ""
    date: str = ""               # ISO date when known, else ""
    source_type: str = ""        # one of SOURCE_TYPES
    retrieved_at: str = ""       # UTC ISO-8601 of retrieval
    credibility: float = 0.0    # 0-1 assessed weight (see research.quality_weight)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def required_fields(cls) -> list[str]:
        return ["title", "url", "publisher", "source_type", "retrieved_at"]


@dataclass
class Fact:
    id: str = ""
    statement: str = ""
    statement_type: str = ""     # one of STATEMENT_TYPES
    source_ids: list[str] = field(default_factory=list)
    subject_key: str = ""        # normalized subject for contradiction grouping
    numeric_value: float | None = None
    numeric_unit: str = ""
    date_value: str = ""         # ISO date when the fact asserts one
    confidence: float = 0.0      # computed by ResearchAgent, never asserted

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Fact":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Claim:
    id: str = ""
    statement: str = ""
    claim_type: str = "factual"  # "factual" | "opinion"
    fact_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    critical: bool = False       # load-bearing: failure blocks approval
    is_direct_quote: bool = False
    attribution: str = ""        # who said it, for quotes/attributions

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Claim":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Contradiction:
    id: str = ""
    subject_key: str = ""
    description: str = ""
    fact_ids: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Contradiction":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class OpenQuestion:
    id: str = ""
    question: str = ""
    why_matters: str = ""
    related_fact_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OpenQuestion":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class ResearchPackage:
    version: str = "1.0"
    topic: str = ""
    audience: str = ""
    language: str = "en"
    target_duration_seconds: float = 0.0
    channel_niche: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    evidence_graph: dict[str, Any] = field(default_factory=dict)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[dict[str, Any]] = field(default_factory=list)
    package_hash: str = ""       # sha256 of canonical payload (see hashing)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ResearchPackage":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def required_fields(cls) -> list[str]:
        return ["topic", "sources", "facts", "claims", "evidence_graph",
                "contradictions", "open_questions", "package_hash"]


# ---------------------------------------------------------------------------
# Script
# ---------------------------------------------------------------------------


@dataclass
class NarrationBlock:
    id: str = ""
    chapter_id: str = ""
    beat: str = ""               # one of SCRIPT_BEATS
    text: str = ""
    estimated_duration_seconds: float = 0.0
    claim_ids: list[str] = field(default_factory=list)
    pacing_intent: str = ""
    emotional_intent: str = ""
    visual_intent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NarrationBlock":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class DocumentaryScript:
    title: str = ""
    language: str = "en"
    target_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0
    blocks: list[dict[str, Any]] = field(default_factory=list)
    claim_mapping: dict[str, list[str]] = field(default_factory=dict)
    unsupported_claim_ids: list[str] = field(default_factory=list)
    pacing_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DocumentaryScript":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def required_fields(cls) -> list[str]:
        return ["title", "target_duration_seconds",
                "total_duration_seconds", "blocks"]


# ---------------------------------------------------------------------------
# Fact check
# ---------------------------------------------------------------------------


@dataclass
class ClaimVerdict:
    claim_id: str = ""
    statement: str = ""
    verdict: str = ""            # one of CLAIM_VERDICTS
    source_ids: list[str] = field(default_factory=list)
    evidence_summary: str = ""
    confidence: float = 0.0
    problem: str = ""            # machine-readable problem code, "" when clean
    recommendation: str = ""     # cut | re-source | hedge | research | none
    blocks_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClaimVerdict":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class FactCheckReport:
    version: str = "1.0"
    script_title: str = ""
    package_hash: str = ""       # research package this report checked against
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    blocking_claim_ids: list[str] = field(default_factory=list)
    passed: bool = False         # True iff no blocking claims remain
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FactCheckReport":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def required_fields(cls) -> list[str]:
        return ["package_hash", "verdicts", "blocking_claim_ids", "passed"]


# ---------------------------------------------------------------------------
# Storyboard
# ---------------------------------------------------------------------------


@dataclass
class VisualRequirement:
    id: str = ""
    narration_block_id: str = ""
    visual_objective: str = ""
    subject: str = ""
    location: str = ""
    period: str = ""
    preferred_media_type: str = "video"   # video | image | any
    shot_type: str = ""                   # wide | aerial | close_up | archival | ...
    shot_function: str = ""               # one of SHOT_FUNCTIONS
    minimum_duration_seconds: float = 0.0
    desired_duration_seconds: float = 0.0
    evidence_relationship: str = ""       # illustrates | proves | context | atmosphere
    claim_ids: list[str] = field(default_factory=list)
    evidence_source_ids: list[str] = field(default_factory=list)
    positive_search_terms: list[str] = field(default_factory=list)
    exclusion_terms: list[str] = field(default_factory=list)
    rights_requirement: str = "verified"  # verified | permissive | audit-only
    priority: str = "normal"              # hero | high | normal | nice_to_have
    fallback_policy: str = "widen_terms"  # widen_terms | adjacent_slot | flag_missing
    availability: str = "uncertain"       # storyboard never sets "available"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VisualRequirement":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Storyboard:
    version: str = "1.0"
    title: str = ""
    script_title: str = ""
    factcheck_passed: bool = False
    requirements: list[dict[str, Any]] = field(default_factory=list)
    chapter_plan: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Storyboard":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def required_fields(cls) -> list[str]:
        return ["title", "requirements", "chapter_plan", "coverage"]


# ---------------------------------------------------------------------------
# Visual scoring
# ---------------------------------------------------------------------------


@dataclass
class VisualScore:
    requirement_id: str = ""
    asset_id: str = ""
    final_score: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    decision: str = ""           # one of SCORING_DECISIONS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VisualScore":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
