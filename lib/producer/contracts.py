"""Producer + review contracts for the YouTube documentary factory.

Plain-data contracts (JSON round-trippable) for orchestration, editorial
assembly, audio verification, preview, QA, human review, and packaging.
Same pattern as lib/editorial/contracts.py: dataclasses with to_dict /
from_dict / required_fields, no provider imports, no network.

The Producer coordinates existing services (EpisodeStore, checkpoints,
pipeline guard, TTS Hub, FootageHub, editorial agents, audio mixer,
video_compose). It holds no domain logic of its own: stage content comes
from injected handlers or pre-supplied payloads, never invented here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

PRODUCER_STAGES: tuple[str, ...] = (
    "topic", "research", "evidence", "script", "fact_check", "storyboard",
    "narration", "footage", "footage_intelligence", "editorial", "timeline",
    "audio", "render", "qa", "packaging", "thumbnail", "human_review",
)
# NOTE: publish + analytics are intentionally outside the Producer's scope.

EVENT_KINDS = (
    "run_started", "run_finished", "stage_started", "stage_skipped",
    "stage_completed", "stage_failed", "stage_awaiting_human",
    "retry_started", "dry_run", "gate_decision",
)


@dataclass
class ProducerEvent:
    timestamp: str = ""
    episode_id: str = ""
    stage: str = ""
    kind: str = ""               # one of EVENT_KINDS
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProducerEvent":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class StagePlan:
    stage: str = ""
    inputs: list[str] = field(default_factory=list)    # required artifacts in
    produces: list[str] = field(default_factory=list)  # artifacts out
    will_skip: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StagePlan":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Editorial assembly
# ---------------------------------------------------------------------------


@dataclass
class FootageMoment:
    requirement_id: str = ""
    asset_id: str = ""
    asset_provider: str = ""
    asset_path: str = ""         # vault path or manifest asset id
    in_seconds: float = 0.0      # exact in-point within the asset
    out_seconds: float = 0.0     # exact out-point within the asset
    function: str = ""           # shot function from the requirement
    score: float = 0.0           # visual relevance final score
    decision: str = ""           # pass | weak (never wrong/missing)
    provenance: dict[str, Any] = field(default_factory=dict)
    repetition_count: int = 0    # times this asset is used in this episode

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FootageMoment":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def required_fields(cls) -> list[str]:
        return ["requirement_id", "asset_id", "in_seconds", "out_seconds",
                "function", "score", "provenance", "repetition_count"]


@dataclass
class ShotDecision:
    scene_id: str = ""
    requirement_id: str = ""
    moment: dict[str, Any] = field(default_factory=dict)  # FootageMoment
    rationale: str = ""
    revision: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ShotDecision":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# QA
# ---------------------------------------------------------------------------

QA_AREAS = ("technical", "audio", "editorial", "evidence", "rights",
            "integrity")

CHECK_STATUS = ("pass", "warn", "fail")

QA_VERDICTS = ("PASS", "WARN", "FAIL")
READINESS = ("READY", "BLOCKED")


@dataclass
class CheckResult:
    name: str = ""
    area: str = ""               # one of QA_AREAS
    status: str = ""             # one of CHECK_STATUS
    detail: str = ""
    blocking: bool = True        # fail+blocking => BLOCKED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CheckResult":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class QAReport:
    version: str = "1.0"
    episode_id: str = ""
    video_path: str = ""
    verdict: str = ""            # one of QA_VERDICTS
    readiness: str = ""          # READY | BLOCKED
    checks: list[dict[str, Any]] = field(default_factory=list)
    checks_run: int = 0
    checks_skipped: int = 0
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QAReport":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Human review + packaging
# ---------------------------------------------------------------------------

REVIEW_DECISIONS = ("READY_FOR_REVIEW", "CHANGES_REQUESTED", "APPROVED",
                    "REJECTED")


@dataclass
class ReviewDecision:
    decision: str = ""           # one of REVIEW_DECISIONS
    approver: str = ""           # explicit identity, never empty on APPROVED
    rationale: str = ""          # required, never empty
    timestamp: str = ""
    episode_id: str = ""
    video_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReviewDecision":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def required_fields(cls) -> list[str]:
        return ["decision", "approver", "rationale", "timestamp",
                "episode_id"]


@dataclass
class TitleCandidate:
    title: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    final_score: float = 0.0
    misleading_risk: float = 0.0
    accepted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TitleCandidate":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


TITLE_AXES = ("clarity", "curiosity", "specificity", "relevance",
              "originality")


def manifest_assets(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Manifest assets with sidecar provenance merged back in.

    The canonical asset_manifest schema closes asset items, so the
    footage runner keeps items schema-pure and stores full FootageHub
    records + visual picks under ``metadata.provenance`` /
    ``metadata.visual`` (``metadata`` is open). Downstream readers
    (editorial, QA) use this view instead of ``manifest["assets"]``
    directly so license/rights/attribution/checksum stay auditable
    without forking the Timeline/manifest contracts.
    """
    metadata = manifest.get("metadata") or {}
    provenance = metadata.get("provenance") or {}
    visual = metadata.get("visual") or {}
    out = []
    for asset in manifest.get("assets") or []:
        aid = asset.get("id", asset.get("asset_id", ""))
        merged = dict(asset)
        extra = provenance.get(aid, {})
        if isinstance(extra, dict):
            merged.update(extra)
        picks = visual.get(aid, {})
        if isinstance(picks, dict):
            merged.update(picks)
        merged.setdefault("asset_id", aid)
        merged.setdefault("id", aid)
        out.append(merged)
    return out


def script_claims(script: dict[str, Any]) -> dict[str, list[str]]:
    """Map script section id -> claim ids, reading the canonical location.

    The canonical script schema forbids extra section fields, so the
    editorial ScriptAgent stores claim linkage under
    ``metadata.documentary`` (blocks[] + claim_mapping). Legacy callers
    may still carry ``claim_ids`` inline on sections; those are honored
    as a fallback so offline fixtures keep working.
    """
    out: dict[str, list[str]] = {}
    documentary = ((script.get("metadata") or {}).get("documentary") or {})
    for block in documentary.get("blocks") or []:
        if block.get("id"):
            out[str(block["id"])] = [str(c) for c in
                                     block.get("claim_ids", [])]
    for section_id, cids in (documentary.get("claim_mapping") or {}).items():
        out.setdefault(str(section_id), [str(c) for c in cids])
    for section in script.get("sections") or []:
        if section.get("id") and section.get("claim_ids"):
            out.setdefault(str(section["id"]),
                           [str(c) for c in section["claim_ids"]])
    return out
