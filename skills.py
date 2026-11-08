"""Skills: short, app-specific know-how added to the desktop operator's instructions when a task needs it.

A skill is a markdown file in skills/ with a header:

    ---
    name: finder
    description: Navigate to folders, create, rename and trash files in Finder.
    triggers: finder, folder, rename, trash
    ---
    - Go to a folder: cmd+shift+g, type the path, return.

A skill applies when any trigger word appears in the task (case-insensitive); `triggers: always`
applies to every task. Matching skills are appended to the operator's system prompt for that run,
so they cost no extra model turns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    triggers: tuple[str, ...]
    body: str


def parse(text: str) -> Skill:
    """A skill from its markdown text; raises ValueError if the header is missing or incomplete."""
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if not match:
        raise ValueError("skill file must start with a --- header ---")
    header = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    header = {k.strip(): v.strip() for k, v in header.items()}
    missing = {"name", "description", "triggers"} - header.keys()
    if missing:
        raise ValueError(f"skill header is missing: {', '.join(sorted(missing))}")
    triggers = tuple(t.strip().lower() for t in header["triggers"].split(",") if t.strip())
    return Skill(header["name"], header["description"], triggers, match.group(2).strip())


def load(directory: Path = SKILLS_DIR) -> list[Skill]:
    """Every skills/*.md, sorted by file name (so 'general' style skills can be ordered with a prefix)."""
    return [parse(p.read_text()) for p in sorted(directory.glob("*.md"))]


def match(task: str, skills: list[Skill]) -> list[Skill]:
    """Skills whose trigger words appear in the task as whole words, plus `always` skills."""
    words = set(re.findall(r"[a-z0-9+]+(?:\.[a-z0-9+]+)*", task.lower()))  # "safari." -> "safari", keeps "example.com"
    # ponytail: whole-word trigger matching; swap for embeddings or knowledge.related_context() if it misfires
    return [s for s in skills if "always" in s.triggers or words & set(s.triggers)]


def render(skills: list[Skill]) -> str:
    """The text appended to the operator's instructions."""
    if not skills:
        return ""
    return "\n\nSkills for this task:\n" + "\n\n".join(f"## {s.name}: {s.description}\n{s.body}" for s in skills)


def for_task(task: str, directory: Path = SKILLS_DIR) -> str:
    """Rendered skills that apply to `task` (empty when none do)."""
    return render(match(task, load(directory)))
