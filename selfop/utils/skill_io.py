from __future__ import annotations

import re
import shutil
from pathlib import Path


_SKILL_FRONTMATTER = """\
---
name: {skill_name}
description: Skill for guiding agent tasks.
---

"""


def ensure_frontmatter(skill_text: str, skill_name: str) -> str:
    if skill_text.lstrip().startswith("---"):
        return skill_text
    return _SKILL_FRONTMATTER.format(skill_name=skill_name) + skill_text


def write_skill_dir(
    base_dir: Path, skill_text: str, skill_name: str,
    *, with_references: bool = False, with_agents: bool = False,
) -> Path:
    """Write skill_text into <base_dir>/<skill_name>/SKILL.md. Returns base_dir."""
    skill_subdir = Path(base_dir) / skill_name
    skill_subdir.mkdir(parents=True, exist_ok=True)
    (skill_subdir / "SKILL.md").write_text(
        ensure_frontmatter(skill_text, skill_name), encoding="utf-8"
    )
    if with_references:
        (skill_subdir / "references").mkdir(exist_ok=True)
    if with_agents:
        (skill_subdir / "agents").mkdir(exist_ok=True)
    return Path(base_dir)


def render_skill_dir(skill_dir: Path) -> str:
    """Render all .md files in skill_dir as a structured multi-file string."""
    skill_dir = Path(skill_dir)
    all_files = sorted(skill_dir.rglob("*.md"))
    skill_md = skill_dir / "SKILL.md"
    ordered = [skill_md] + [f for f in all_files if f != skill_md]
    ordered = [f for f in ordered if f.exists()]

    parts: list[str] = []
    for f in ordered:
        rel = str(f.relative_to(skill_dir))
        content = f.read_text(encoding="utf-8")
        parts.append(f"--- BEGIN FILE: {rel} ---\n{content}\n--- END FILE: {rel} ---")
    return "\n\n".join(parts)


def restore_skill_dir(base_dir: Path, rendered_skill: str, skill_name: str) -> Path:
    """Parse multi-file rendering and write files. Falls back to write_skill_dir."""
    pattern = re.compile(
        r"--- BEGIN FILE: (.+?) ---\n(.*?)\n--- END FILE: \1 ---",
        re.DOTALL,
    )
    matches = list(pattern.finditer(rendered_skill))

    if not matches:
        return write_skill_dir(
            base_dir, rendered_skill, skill_name,
            with_references=True, with_agents=True,
        )

    skill_dir = Path(base_dir) / skill_name
    for m in matches:
        file_path = m.group(1).strip()
        content = m.group(2)
        target = (skill_dir / file_path).resolve()
        try:
            target.relative_to(skill_dir.resolve())
        except ValueError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    (skill_dir / "references").mkdir(exist_ok=True)
    (skill_dir / "agents").mkdir(exist_ok=True)
    return Path(base_dir)


def save_skill_snapshot(
    skills_dir: Path,
    skill_text: str,
    label: str,
    *,
    skill_name: str = "cybergym-poc-generation",
) -> Path:
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / f"{label}.md"
    path.write_text(skill_text, encoding="utf-8")
    restore_skill_dir(skills_dir / label, skill_text, skill_name)
    return path


def skill_root_for_step(
    config,
    epoch: int,
    batch_idx: int,
    label: str,
    skill_text: str,
) -> Path:
    """Write skill to a per-step directory and return the skills-root path."""
    base = config.step_dir(epoch, batch_idx) / "skill_dirs" / label
    return restore_skill_dir(base, skill_text, config.skill_name)


def dir_tree(root: Path, max_depth: int | None = None) -> str:
    """Return a tree-formatted string of root's contents."""
    def _lines(path: Path, prefix: str, depth: int) -> list[str]:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        result = []
        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            result.append(
                f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}"
            )
            if entry.is_dir() and (max_depth is None or depth < max_depth):
                extension = "    " if i == len(entries) - 1 else "│   "
                result.extend(_lines(entry, prefix + extension, depth + 1))
        return result

    return "\n".join([".", *_lines(root, "", 1)])
