"""Human review gate: explicit, append-only, timestamped decisions.

States: READY_FOR_REVIEW (package assembled, awaiting a human),
CHANGES_REQUESTED (sent back with reasons), APPROVED (explicit human
sign-off with identity + rationale), REJECTED (refused with reasons).

Rules enforced here, not by convention:
- approval requires a non-empty approver identity AND rationale;
- decisions append to review_log.jsonl (never rewritten);
- the review_decision checkpoint + episode human_review stage move only
  through the same transitions as any stage (REVIEW -> APPROVED -> DONE);
- publishing stays impossible without APPROVED: assert_publish_allowed
  raises until the latest decision for the episode is APPROVED
  (pipeline_guard enforces the same at the publish stage).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.producer.contracts import REVIEW_DECISIONS, ReviewDecision


class ReviewError(ValueError):
    """Base class: review gate refused (fail closed)."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def assemble_review_package(
    *,
    episode_id: str,
    video_path: str,
    preview_path: str = "",
    script: dict[str, Any] | None = None,
    storyboard: dict[str, Any] | None = None,
    picks: list[dict[str, Any]] | None = None,
    qa_report: dict[str, Any] | None = None,
    rights_summary: dict[str, Any] | None = None,
    narration_status: dict[str, Any] | None = None,
    titles: list[dict[str, Any]] | None = None,
    thumbnail: dict[str, Any] | None = None,
    description: str = "",
    chapters: list[dict[str, Any]] | None = None,
    subtitles_path: str = "",
) -> dict[str, Any]:
    """Bundle everything a human needs to judge the episode."""
    package = {"version": "1.0", "episode_id": episode_id,
               "assembled_at": _utcnow(),
               "video_path": video_path, "preview_path": preview_path,
               "script": script or {},
               "storyboard": storyboard or {},
               "selected_footage": picks or [],
               "qa_report": qa_report or {},
               "rights_summary": rights_summary or {},
               "narration_status": narration_status or {},
               "title_candidates": titles or [],
               "thumbnail": thumbnail or {},
               "description": description,
               "chapters": chapters or [],
               "subtitles_path": subtitles_path,
               "status": "READY_FOR_REVIEW"}
    missing = [key for key in ("video_path", "script", "qa_report")
               if not package[key]]
    if missing:
        raise ReviewError(
            f"Review package incomplete, cannot mark READY_FOR_REVIEW: "
            f"missing {missing}.")
    return package


def review_log_path(workdir: Path) -> Path:
    return Path(workdir) / "review_log.jsonl"


def read_decisions(workdir: Path) -> list[ReviewDecision]:
    path = review_log_path(workdir)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(ReviewDecision.from_dict(json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def latest_decision(workdir: Path) -> ReviewDecision | None:
    decisions = read_decisions(workdir)
    return decisions[-1] if decisions else None


def record_decision(workdir: Path, *, episode_id: str, decision: str,
                    approver: str, rationale: str,
                    video_path: str = "") -> ReviewDecision:
    """Append one explicit human decision. APPROVED needs identity+reasons."""
    if decision not in REVIEW_DECISIONS:
        raise ReviewError(
            f"Unknown review decision {decision!r}; must be one of "
            f"{list(REVIEW_DECISIONS)}.")
    if decision == "APPROVED" and not approver.strip():
        raise ReviewError(
            "APPROVED requires an explicit approver identity "
            "(no anonymous approvals).")
    if decision in ("APPROVED", "REJECTED", "CHANGES_REQUESTED") \
            and not rationale.strip():
        raise ReviewError(
            f"{decision} requires a rationale (no unexplained verdicts).")
    if decision == "APPROVED":
        prior = latest_decision(workdir)
        if prior is None or prior.decision not in ("READY_FOR_REVIEW",
                                                   "CHANGES_REQUESTED"):
            raise ReviewError(
                "APPROVED is only valid after READY_FOR_REVIEW "
                "(review the package first; approval cannot come first).")
    entry = ReviewDecision(decision=decision, approver=approver.strip(),
                           rationale=rationale.strip(),
                           timestamp=_utcnow(), episode_id=episode_id,
                           video_path=video_path)
    path = review_log_path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict()) + "\n")
    return entry


def assert_publish_allowed(workdir: Path) -> ReviewDecision:
    """Publishing stays impossible without APPROVED. Raises otherwise."""
    latest = latest_decision(workdir)
    if latest is None or latest.decision != "APPROVED":
        raise ReviewError(
            "Publish blocked: no APPROVED human review on record "
            f"(latest: {latest.decision if latest else 'none'}).")
    return latest


def mark_ready_for_review(workdir: Path, episode_id: str,
                          video_path: str = "") -> ReviewDecision:
    """Open the review: package assembled, awaiting a human verdict."""
    return record_decision(workdir, episode_id=episode_id,
                           decision="READY_FOR_REVIEW", approver="producer",
                           rationale="Review package assembled; awaiting "
                                     "human verdict.",
                           video_path=video_path)
