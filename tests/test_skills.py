import json
from pathlib import Path

import pytest

import skills

SKILL = """---
name: finder
description: Finder know-how.
triggers: finder, rename
---
- Go to a folder: cmd+shift+g.
"""


def test_parse_reads_header_and_body():
    skill = skills.parse(SKILL)
    assert (skill.name, skill.description, skill.triggers) == ("finder", "Finder know-how.", ("finder", "rename"))
    assert skill.body == "- Go to a folder: cmd+shift+g."


@pytest.mark.parametrize("text", ["no header", "---\nname: x\n---\nbody", "---\nname: x\ndescription: y\n---\n"])
def test_parse_rejects_bad_headers(text):
    with pytest.raises(ValueError):
        skills.parse(text)


def test_match_uses_whole_words_and_always():
    finder, general = skills.parse(SKILL), skills.parse(SKILL.replace("finder, rename", "always").replace("name: finder", "name: general"))
    assert skills.match("Rename a.txt in Finder", [finder, general]) == [finder, general]
    assert skills.match("Open the finderish app", [finder, general]) == [general]
    assert skills.render([]) == ""
    assert "## finder: Finder know-how." in skills.render([finder])


def test_repo_skills_load_and_apply_to_every_eval_task():
    loaded = skills.load()
    assert loaded and len({s.name for s in loaded}) == len(loaded)
    always = {s.name for s in loaded if "always" in s.triggers}
    assert always, "at least one general skill should apply to every task"
    tasks = {t["id"]: t["instruction"] for t in json.loads(Path("evals/desktop/tasks.json").read_text())}
    for task_id, instruction in tasks.items():
        names = {s.name for s in skills.match(instruction, loaded)}
        assert always <= names, (task_id, names)
