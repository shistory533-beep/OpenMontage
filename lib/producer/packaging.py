"""Packaging Agent: upload-ready metadata without clickbait.

Generates title candidates (scored on five axes + misleading-risk gate),
a description assembled only from supplied evidence-backed strings,
chapters from script blocks, tags/hashtags from topic keywords, subtitle
metadata from narration timings, and a thumbnail specification derived
from the hero requirement and storyboard.

Nothing is invented here: titles may only assert wording grounded in
verified claims; the description is a template over supplied inputs;
thumbnail text is capped and must quote verified wording.
"""

from __future__ import annotations

import re
from typing import Any

from lib.producer.contracts import TITLE_AXES, TitleCandidate

CLICKBAIT_SUPERLATIVES = (
    "shocking", "unbelievable", "insane", "crazy", "mind-blowing",
    "you won't believe", "gone wrong", "epic fail", "exposed",
    "secret they", "doctors hate", "banned",
)
ABSOLUTE_PHRASES = (
    "the largest", "the smallest", "the first", "the only", "the best",
    "the worst", "never", "always", "everyone", "nobody", "prove",
    "proof", "guaranteed",
)


class PackagingError(ValueError):
    """Base class: packaging refused (fail closed)."""


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", (text or "").lower())


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def score_title(title: str, topic_keywords: list[str],
                verified_claims: list[str],
                used_titles: list[str] | None = None) -> TitleCandidate:
    """Score one title candidate on five axes + misleading risk."""
    words = _words(title)
    verified_text = _norm(" ".join(verified_claims))
    keys = {_norm(k) for k in topic_keywords if k.strip()}
    title_set = set(words)
    clarity = 1.0 if 4 <= len(words) <= 12 else (
        0.6 if 2 <= len(words) <= 16 else 0.2)
    if title != title.strip() or "  " in title:
        clarity = min(clarity, 0.5)
    curiosity = 0.5
    low = _norm(title)
    if "?" in title or low.startswith(("how ", "why ")):
        curiosity = 0.9
    elif any(w in low for w in ("mystery", "lost", "hidden", "untold",
                                "secret", "inside", "story")):
        curiosity = 0.7
    specificity = (len(keys & title_set) / len(keys)) if keys else 0.5
    relevance = specificity  # same grounding, reported separately per spec
    used = {_norm(t) for t in (used_titles or [])}
    originality = 0.0 if low in used else (
        0.5 if any(low in u or u in low for u in used if u) else 1.0)
    risky = [p for p in CLICKBAIT_SUPERLATIVES + ABSOLUTE_PHRASES
             if p in low]
    grounded = [p for p in risky if p in verified_text]
    ungrounded = [p for p in risky if p not in verified_text]
    misleading_risk = min(1.0, 0.5 * len(ungrounded))
    scores = {"clarity": round(clarity, 2),
              "curiosity": round(curiosity, 2),
              "specificity": round(specificity, 2),
              "relevance": round(relevance, 2),
              "originality": round(originality, 2)}
    final = round(sum(scores.values()) / len(scores)
                  - misleading_risk * 0.5, 3)
    return TitleCandidate(title=title, scores=scores, final_score=final,
                          misleading_risk=round(misleading_risk, 2),
                          accepted=misleading_risk < 0.5)


class PackageAgent:
    """Builds the upload-ready bundle. Deterministic, evidence-bound."""

    def __init__(self, used_titles: list[str] | None = None) -> None:
        self.used_titles = list(used_titles or [])

    def generate_titles(self, topic: str, topic_keywords: list[str],
                        verified_claims: list[str],
                        seeds: list[str] | None = None) -> dict[str, Any]:
        """Score seed titles; always return exactly 5 accepted candidates.

        Seeds come from the directing agent. Rejected seeds (clickbait)
        are reported, never silently shipped. If fewer than 5 survive,
        deterministic variants are derived from the top seed by appending
        grounded qualifiers — never by inventing new assertions.
        """
        seeds = seeds or []
        if not seeds:
            seeds = [f"{topic}: what the evidence shows"]
        scored = [score_title(s, topic_keywords, verified_claims,
                              self.used_titles) for s in seeds]
        accepted = sorted(
            [c for c in scored if c.accepted],
            key=lambda c: (-c.final_score, c.title))
        rejected = [c.title for c in scored if not c.accepted]
        qualifiers = ["the full story", "explained", "what we know",
                      "in context", "a closer look"]
        i = 0
        while len(accepted) < 5 and accepted:
            variant = f"{accepted[0].title} — {qualifiers[i % len(qualifiers)]}"
            candidate = score_title(variant, topic_keywords,
                                    verified_claims, self.used_titles)
            if candidate.accepted and all(
                    candidate.title != c.title for c in accepted):
                accepted.append(candidate)
            i += 1
            if i > 20:
                break
        accepted = sorted(accepted, key=lambda c: (-c.final_score,
                                                   c.title))[:5]
        if len(accepted) < 5:
            raise PackagingError(
                f"Only {len(accepted)} acceptable titles from "
                f"{len(seeds)} seeds (rejected clickbait: {rejected}). "
                f"Supply more grounded seeds.")
        return {"candidates": [c.to_dict() for c in accepted],
                "rejected": rejected}

    def build_description(self, brief_topic: str,
                          chapters: list[dict[str, Any]],
                          source_links: list[str]) -> str:
        lines = [brief_topic.strip(), ""]
        for chapter in chapters:
            title = chapter.get("title", chapter.get("chapter_id", ""))
            stamp = chapter.get("start", "")
            lines.append(f"{stamp} {title}".strip())
        if source_links:
            lines += ["", "Sources:"]
            lines += [f"- {link}" for link in source_links]
        return "\n".join(lines).strip()

    def build_chapters(self, script_blocks: list[dict[str, Any]]
                       ) -> list[dict[str, Any]]:
        """Chapters from script chapter/beat structure with timestamps."""
        chapters: dict[str, dict[str, Any]] = {}
        for block in script_blocks:
            cid = block.get("chapter_id", block.get("beat", "chapter"))
            slot = chapters.setdefault(cid, {"chapter_id": cid,
                                             "title": cid.replace("_", " "
                                                                       ).title(),
                                             "start": "0:00",
                                             "start_seconds": None})
            start = block.get("start_seconds")
            if start is not None and (slot["start_seconds"] is None
                                      or start < slot["start_seconds"]):
                slot["start_seconds"] = float(start)
        out = []
        for chapter in chapters.values():
            seconds = chapter.pop("start_seconds")
            chapter["start"] = _stamp(seconds or 0.0)
            out.append(chapter)
        out.sort(key=lambda c: c["start"])
        return out

    def build_tags(self, topic_keywords: list[str],
                   verified_terms: list[str] | None = None) -> dict[str, Any]:
        tags = []
        for keyword in topic_keywords:
            clean = re.sub(r"[^a-z0-9 ]", "", keyword.lower()).strip()
            if clean and clean not in tags:
                tags.append(clean)
        for term in verified_terms or []:
            clean = re.sub(r"[^a-z0-9 ]", "", term.lower()).strip()
            if clean and clean not in tags:
                tags.append(clean)
        hashtags = ["#" + t.replace(" ", "") for t in tags[:5]]
        return {"tags": tags[:15], "hashtags": hashtags}

    def subtitle_metadata(self, narration_segments: list[dict[str, Any]]
                          ) -> dict[str, Any]:
        cues = [{"start_seconds": s.get("start_seconds", 0),
                 "end_seconds": s.get("end_seconds", 0),
                 "text": s.get("text", s.get("asset_id", ""))}
                for s in narration_segments]
        return {"version": "1.0", "cue_count": len(cues), "cues": cues,
                "format": "srt"}

    def thumbnail_spec(self, hero_requirement: dict[str, Any],
                       title: str,
                       verified_claims: list[str]) -> dict[str, Any]:
        """Thumbnail plan derived from the hero shot + grounded wording."""
        words = _words(title)[:4]
        verified_text = _norm(" ".join(verified_claims))
        text = " ".join(words)
        if text and text not in verified_text:
            # Thumbnail text must quote verified wording; fall back to the
            # hero subject rather than inventing a punchier line.
            fallback: list[str] = (hero_requirement.get("subject") or "").split()[:4]
            text = " ".join(fallback)
        shot = (hero_requirement.get("shot_type") or "wide").lower()
        composition = ("rule-of-thirds, subject offset left, negative "
                       "space right for text" if "close" in shot or "medium"
                       in shot else "center-weighted landscape, horizon "
                       "upper third, title-safe lower third")
        return {"focal_subject": hero_requirement.get("subject", ""),
                "composition": composition,
                "text": text,
                "text_word_count": len(_words(text)),
                "contrast": "high subject/background separation; "
                            "legible at 120px width",
                "visual_concept": hero_requirement.get(
                    "visual_objective", ""),
                "reason": (f"Fits {title!r}: same subject as the hero shot "
                           f"({hero_requirement.get('id')}) with grounded "
                           f"wording only.")}

    def build(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Assemble the full package_bundle (no publish)."""
        topic = str(inputs.get("topic") or
                    (inputs.get("brief") or {}).get("topic") or "episode")
        keywords = [str(k) for k in
                    (inputs.get("topic_keywords")
                     or _words(topic))][:10]
        verified = [str(v.get("statement", v)) if isinstance(v, dict)
                    else str(v)
                    for v in (inputs.get("verified_claims") or [])]
        seeds = inputs.get("title_seeds") or []
        titles = self.generate_titles(topic, keywords, verified, seeds)
        script = inputs.get("script") or {}
        chapters = self.build_chapters(script.get("sections") or
                                       [{"chapter_id": "full",
                                         "start_seconds": 0}])
        storyboard = inputs.get("storyboard") or {}
        reqs = storyboard.get("requirements") or []
        hero: dict[str, Any] = next((r for r in reqs if r.get("priority") == "hero"),
                      reqs[0] if reqs else {})
        chosen: str = titles["candidates"][0]["title"]  # type: ignore[call-overload]
        narration = inputs.get("narration_manifest") or {}
        segments = narration.get("segments") or []
        sources = [s.get("url", "") for s in
                   (inputs.get("research_package") or {}).get("sources",
                                                              [])]
        bundle = {"version": "1.0",
                  "episode_id": inputs.get("episode_id", ""),
                  "titles": titles,
                  "chosen_title": chosen,
                  "description": self.build_description(topic, chapters,
                                                        sources),
                  "chapters": chapters,
                  "tags": self.build_tags(keywords),
                  "subtitles": self.subtitle_metadata(segments),
                  "thumbnail": self.thumbnail_spec(hero, chosen, verified),
                  "video_path": (inputs.get("render_report") or {}).get(
                      "outputs", [{}])[0].get("path", "")
                  if isinstance(inputs.get("render_report"), dict) else ""}
        return bundle


def _stamp(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
