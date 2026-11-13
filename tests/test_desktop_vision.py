"""Final-category vision graders: right answers pass, wrong ones fail, and no answer reaches the sandbox."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("PIL")
SPEC = importlib.util.spec_from_file_location(
    "desktop_reliability", Path(__file__).parents[1] / "evals/desktop/reliability.py")
reliability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reliability)
vision = reliability.vision


def agent_json(result):
    """Last output line as agent.py prints it; token counts must not count as answers."""
    return "[click ...: ok]\n" + json.dumps({"result": result, "input_tokens": 1234567, "output_tokens": 89})


def wrong(task, answer):
    if task == "image_code":
        return "ZZZZZZ" if answer != "ZZZZZZ" else "YYYYYY"
    if task == "shape_count":
        return str((int(answer) + 1) % 7)
    hour, minute = map(int, answer.split(":"))
    return f"{hour % 12 + 1}:{minute:02d}"


@pytest.mark.parametrize("task", ["image_code", "shape_count", "clock_time"])
def test_answer_tasks(tmp_path, task):
    reliability.setup_task(task, tmp_path, open_apps=False)
    answer = vision.ANSWERS[task]
    assert reliability.grade_task(task, tmp_path, agent_json(f"It shows {answer}."))[0]
    assert not reliability.grade_task(task, tmp_path, agent_json(f"It shows {wrong(task, answer)}."))[0]
    assert not reliability.grade_task(task, tmp_path, "")[0]


def test_answer_hidden_from_sandbox(tmp_path):
    for task in vision.TASKS:
        shutil.rmtree(tmp_path)
        reliability.setup_task(task, tmp_path, open_apps=False)
        contents = b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
        if task != "circled_file":  # its inbox names are the neutral choices, not the answer
            assert vision.ANSWERS[task].encode() not in contents


def test_token_counts_ignored(tmp_path):
    reliability.setup_task("shape_count", tmp_path, open_apps=False)
    vision.ANSWERS["shape_count"] = "4"
    assert not reliability.grade_task("shape_count", tmp_path, agent_json("I could not see the image."))[0]
    assert reliability.grade_task("shape_count", tmp_path, agent_json("There are four red circles."))[0]


def test_transcribe_image(tmp_path):
    reliability.setup_task("transcribe_image", tmp_path, open_apps=False)
    sentence = vision.ANSWERS["transcribe_image"]
    (tmp_path / "transcript.txt").write_text(sentence)  # missing final newline
    assert not reliability.grade_task("transcribe_image", tmp_path)[0]
    (tmp_path / "transcript.txt").write_text(sentence + "\n")
    assert reliability.grade_task("transcribe_image", tmp_path)[0]
    (tmp_path / "unrelated.txt").write_text("overwritten")
    assert not reliability.grade_task("transcribe_image", tmp_path)[0]


def test_circled_file(tmp_path):
    reliability.setup_task("circled_file", tmp_path, open_apps=False)
    chosen = vision.ANSWERS["circled_file"]
    other = next(letter for letter in vision.LETTERS if letter != chosen)
    assert not reliability.grade_task("circled_file", tmp_path)[0]
    (tmp_path / "inbox" / f"invoice-{other}.txt").rename(tmp_path / "chosen" / f"invoice-{other}.txt")
    assert not reliability.grade_task("circled_file", tmp_path)[0]
    (tmp_path / "chosen" / f"invoice-{other}.txt").rename(tmp_path / "inbox" / f"invoice-{other}.txt")
    (tmp_path / "inbox" / f"invoice-{chosen}.txt").rename(tmp_path / "chosen" / f"invoice-{chosen}.txt")
    assert reliability.grade_task("circled_file", tmp_path)[0]
    shutil.copy(tmp_path / "chosen" / f"invoice-{chosen}.txt", tmp_path / "inbox" / f"invoice-{chosen}.txt")
    assert not reliability.grade_task("circled_file", tmp_path)[0]  # copied, not moved
