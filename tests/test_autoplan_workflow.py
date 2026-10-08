"""Autoplan workflow config guard: AGENTS.md rule, build prompt wiring,
reviewer, skills, and commands ship together and stay valid.

Covers FREE-AUTO preservation: the provider shim must survive config edits.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_opencode() -> dict:
    return json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))


def test_opencode_json_valid_and_free_auto_intact():
    cfg = _load_opencode()
    provider = cfg["provider"]["free-auto"]
    assert provider["options"]["baseURL"].startswith("http://127.0.0.1:")
    assert "free-auto" in provider["models"]


def test_build_prompt_wiring_resolves():
    cfg = _load_opencode()
    ref = cfg["agent"]["build"]["prompt"]
    assert ref.startswith("{file:") and ref.endswith("}")
    target = ROOT / ref[len("{file:"):-1]
    assert target.is_file(), f"build prompt target missing: {target}"
    body = target.read_text(encoding="utf-8")
    for keyword in ("AGENTS.md", "todowrite", "explore", "reviewer", "Verify"):
        assert keyword in body, f"build prompt missing {keyword!r}"


def test_agents_md_lifecycle_rule_present():
    body = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for keyword in (
        "Autoplan", "UNDERSTAND", "EXPLORE", "PLAN", "TODO",
        "BUILD", "VERIFY", "REVIEW", "REPORT", "todowrite",
        "AGENT_GUIDE.md",
    ):
        assert keyword in body, f"AGENTS.md missing {keyword!r}"


def test_reviewer_agent_read_only():
    body = (ROOT / ".opencode" / "agents" / "reviewer.md").read_text(encoding="utf-8")
    assert "mode: subagent" in body
    assert "deny" in body  # edit + bash denied
    assert "push" in body.lower()


def test_skills_discoverable_with_frontmatter():
    for name in ("repository-archaeology", "implementation-verify", "production-smoke"):
        skill = ROOT / ".opencode" / "skills" / name / "SKILL.md"
        assert skill.is_file(), f"missing {skill}"
        head = skill.read_text(encoding="utf-8").split("---")
        assert f"name: {name}" in head[1]
        assert "description:" in head[1]


def test_commands_present_and_target_agents():
    for name, agent in (("autoplan", "build"), ("verify", "build"), ("review", "reviewer")):
        cmd = ROOT / ".opencode" / "commands" / f"{name}.md"
        assert cmd.is_file(), f"missing {cmd}"
        head = cmd.read_text(encoding="utf-8").split("---")
        assert f"agent: {agent}" in head[1]
        assert "description:" in head[1]


def test_adaptive_depth_tiers_in_build_prompt():
    body = (ROOT / ".opencode" / "prompts" / "build-autoplan.md").read_text(encoding="utf-8")
    for keyword in ("T0", "T1", "T2", "T3", "plans/<task>.md", "finding / ruling",
                    "Compact context", "FREE-AUTO", "automatically per session"):
        assert keyword in body, f"build prompt missing {keyword!r}"


def test_evidence_pack_format_in_archaeology_skill():
    body = (ROOT / ".opencode" / "skills" / "repository-archaeology" / "SKILL.md").read_text(encoding="utf-8")
    for keyword in ("EVIDENCE PACK", "FILES", "SYMBOLS", "FINDINGS",
                    "CONSTRAINTS", "GAPS", "RECOMMENDATION",
                    "reuse -> extend -> adapt -> build new",
                    "PROJECT_CONTEXT.md"):
        assert keyword in body, f"archaeology skill missing {keyword!r}"


def test_verify_skill_token_efficiency_rules():
    body = (ROOT / ".opencode" / "skills" / "implementation-verify" / "SKILL.md").read_text(encoding="utf-8")
    for keyword in ("narrowest", "root", "regression test"):
        assert keyword in body, f"verify skill missing {keyword!r}"


def test_plans_dir_exists_for_t2_t3_artifacts():
    assert (ROOT / "docs" / "openmontage" / "plans").is_dir()
