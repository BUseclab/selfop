#!/usr/bin/env python3
"""Validate agent_home/ against the structure policy (SKILL.md + references only).

Checks:
  1. SKILL.md has valid YAML frontmatter (name + description)
  2. SKILL.md and each reference file are individually < 5 000 tokens
  3. Every reference file is cited by its full path (~/.codex/skills/...)
     somewhere in SKILL.md or another reference

Exits 0 if all checks pass, 1 if any fail.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


TOKEN_LIMIT = 5000

_results: list[tuple[bool, str]] = []


def _estimate_tokens(text: str) -> int:
    """Rough GPT-style token estimate (~5 chars per token)."""
    return len(text) // 5


def _pass(label: str) -> None:
    _results.append((True, label))
    print(f"  PASS  {label}")


def _fail(label: str, reason: str) -> None:
    _results.append((False, f"{label}: {reason}"))
    print(f"  FAIL  {label}: {reason}")


# -- check 1: YAML frontmatter -------------------------------------------

def check_yaml_frontmatter(skill_md: Path) -> None:
    text = skill_md.read_text(encoding="utf-8")

    fm_match = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not fm_match:
        _fail("SKILL.md frontmatter", "no valid --- ... --- YAML block found")
        return

    fm = fm_match.group(1)
    name_ok = bool(re.search(r'^name\s*:\s*\S', fm, re.MULTILINE))
    desc_ok = bool(re.search(r'^description\s*:\s*\S', fm, re.MULTILINE))

    if not name_ok:
        _fail("SKILL.md frontmatter", "missing or empty 'name' field")
    else:
        _pass("SKILL.md frontmatter.name")

    if not desc_ok:
        _fail("SKILL.md frontmatter", "missing or empty 'description' field")
    else:
        _pass("SKILL.md frontmatter.description")


# -- check 2: per-file token budget ---------------------------------------

def check_token_limits(skill_md: Path, refs_dir: Path | None) -> None:
    skill_tokens = _estimate_tokens(skill_md.read_text(encoding="utf-8"))
    if skill_tokens > TOKEN_LIMIT:
        _fail("SKILL.md tokens", f"~{skill_tokens} tokens > {TOKEN_LIMIT} limit")
    else:
        _pass(f"SKILL.md tokens (~{skill_tokens})")

    if refs_dir and refs_dir.is_dir():
        for ref in sorted(refs_dir.glob("*.md")):
            t = _estimate_tokens(ref.read_text(encoding="utf-8"))
            if t > TOKEN_LIMIT:
                _fail(f"references/{ref.name} tokens",
                      f"~{t} tokens > {TOKEN_LIMIT} limit")
            else:
                _pass(f"references/{ref.name} tokens (~{t})")


# -- check 3: all refs cited by full path --------------------------------

def check_refs_cited(skill_name: str, skill_md: Path, refs_dir: Path | None) -> None:
    if refs_dir is None or not refs_dir.is_dir():
        return
    refs = sorted(refs_dir.glob("*.md"))
    if not refs:
        return

    corpus_by_file: dict[str, str] = {
        skill_md.name: skill_md.read_text(encoding="utf-8"),
    }
    for ref in refs:
        corpus_by_file[ref.name] = ref.read_text(encoding="utf-8")

    for ref in refs:
        full_path = f"~/.codex/skills/{skill_name}/references/{ref.name}"
        mentioned = any(
            full_path in text
            for fname, text in corpus_by_file.items()
            if fname != ref.name
        )
        if mentioned:
            _pass(f"ref cited: {ref.name}")
        else:
            _fail(f"ref cited: {ref.name}",
                  f"not mentioned anywhere as '{full_path}'")


# -- main -----------------------------------------------------------------

def main() -> None:
    workspace = Path(".")
    agent_home = workspace / "agent_home"

    if not agent_home.is_dir():
        print(f"ERROR: agent_home/ not found in {workspace.resolve()}")
        sys.exit(1)

    skills_dir = agent_home / "skills"
    if not skills_dir.is_dir():
        print("ERROR: agent_home/skills/ does not exist")
        sys.exit(1)

    skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
    if len(skill_dirs) != 1:
        names = ", ".join(d.name for d in skill_dirs) or "(none)"
        print(f"ERROR: expected exactly one skill directory, found: {names}")
        sys.exit(1)

    skill_dir = skill_dirs[0]
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        print(f"ERROR: {skill_dir.name}/SKILL.md not found")
        sys.exit(1)

    refs_dir = skill_dir / "references"
    skill_name = skill_dir.name

    print(f"Checking skill '{skill_name}' in {agent_home.resolve()}\n")

    check_yaml_frontmatter(skill_md)
    check_token_limits(skill_md, refs_dir)
    check_refs_cited(skill_name, skill_md, refs_dir)

    passed = sum(1 for ok, _ in _results if ok)
    failed = sum(1 for ok, _ in _results if not ok)
    total = passed + failed

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        for ok, msg in _results:
            if not ok:
                print(f"    ✗ {msg}")
        sys.exit(1)
    else:
        print("  — all checks passed")


if __name__ == "__main__":
    main()
