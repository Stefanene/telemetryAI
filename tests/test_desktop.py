"""Desktop operator regressions with a scripted model: no network, screenshots or GUI actions."""

import asyncio
import json
import subprocess

import pytest
from agents import Model, ModelResponse, Usage
from agents.run_config import CallModelData, ModelInputData
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

import desktop


class FakeModel(Model):
    """Replies with queued turns: a (tool, args) tuple is a tool call, a str is the final answer.
    The last turn repeats once the queue is empty. Every call's input is kept in `inputs`."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.inputs = []

    async def get_response(self, system_instructions, input, *args, **kwargs):
        self.inputs.append(input)
        turn = self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]
        n = len(self.inputs)
        if isinstance(turn, str):
            item = ResponseOutputMessage(id=f"m{n}", type="message", role="assistant", status="completed",
                                         content=[ResponseOutputText(type="output_text", text=turn, annotations=[])])
        else:
            tool, args = turn
            item = ResponseFunctionToolCall(id=f"f{n}", call_id=f"c{n}", type="function_call", status="completed",
                                            name=tool, arguments=json.dumps(args))
        return ModelResponse(output=[item], usage=Usage(), response_id=None)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Screenshots are tiny files in tmp_path, the log goes there too, and nothing waits on the UI."""
    monkeypatch.setattr(desktop, "SCREENSHOT_DIR", tmp_path)
    monkeypatch.setattr(desktop.time, "sleep", lambda seconds: None)

    def capture():
        path = tmp_path / f"shot-{len(list(tmp_path.glob('shot-*')))}.jpg"
        path.write_bytes(b"\xff\xd8frame")
        return path
    monkeypatch.setattr(desktop, "take_screenshot", capture)


def use_model(monkeypatch, turns):
    model = FakeModel(turns)
    monkeypatch.setattr(desktop, "operator", desktop.operator.clone(model=model))
    return model


def records(tmp_path):
    return [json.loads(line) for line in (tmp_path / "actions.jsonl").read_text().splitlines()]


def tool_outputs(model_input):
    return [item["output"] for item in model_input if isinstance(item, dict) and item.get("type") == "function_call_output"]


def test_action_error_is_logged_and_model_can_recover(monkeypatch, tmp_path):
    acted = []
    def run_action(tool, args):
        acted.append(tool)
        if len(acted) == 1:
            raise subprocess.CalledProcessError(1, ["osascript"], stderr="not allowed")
    monkeypatch.setattr(desktop, "run_action", run_action)
    model = use_model(monkeypatch, [("click", {"x": 1, "y": 2}), ("press_key", {"combo": "escape"}), "Recovered"])

    assert asyncio.run(desktop.run_operator("test")) == "Recovered"
    assert acted == ["click", "key"]
    assert [r["result"].startswith("error:") for r in records(tmp_path)] == [True, False]
    assert any("not allowed" in out for out in tool_outputs(model.inputs[1]))


def test_bad_key_combo_is_logged_without_acting(monkeypatch, tmp_path):
    scripts = []
    monkeypatch.setattr(desktop, "_osascript", lambda *args: scripts.append(args))
    use_model(monkeypatch, [("press_key", {"combo": "magic+s"}), "Stopped safely"])

    assert asyncio.run(desktop.run_operator("test")) == "Stopped safely"
    assert not scripts
    assert records(tmp_path)[0]["result"].startswith("error: KeyError")


def test_turn_limit_is_reported_as_unfinished(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "run_action", lambda tool, args: None)
    use_model(monkeypatch, [("press_key", {"combo": "tab"})])

    result = asyncio.run(desktop.run_operator("test", max_turns=2))
    assert result.startswith("stopped: turn limit of 2")
    assert len(records(tmp_path)) == 2  # evidence kept


@pytest.mark.parametrize("fail_on", [1, 2])
def test_screenshot_failure_never_reports_completion(monkeypatch, tmp_path, fail_on):
    captures = []
    def capture():
        captures.append(1)
        if len(captures) == fail_on:
            raise subprocess.CalledProcessError(1, ["screencapture"])
        path = tmp_path / f"shot-{len(captures)}.jpg"
        path.write_bytes(b"\xff\xd8frame")
        return path
    monkeypatch.setattr(desktop, "take_screenshot", capture)
    monkeypatch.setattr(desktop, "run_action", lambda tool, args: None)
    use_model(monkeypatch, [("click", {"x": 1, "y": 2}), "Success"])

    result = asyncio.run(desktop.run_operator("test"))
    assert result.startswith("failed:") and "Screen Recording" in result
    if fail_on > 1:
        assert records(tmp_path)[0]["tool"] == "click"


def test_add_screenshot_appends_one_image_without_touching_history():
    history = [{"role": "user", "content": "task"}]
    data = CallModelData(model_data=ModelInputData(input=history, instructions="sys"), agent=None, context=None)
    updated = desktop.add_screenshot(data)
    assert updated.input[:-1] == history and len(history) == 1
    assert updated.instructions == "sys"
    image = updated.input[-1]["content"][1]
    assert image["type"] == "input_image" and image["image_url"].startswith("data:image/jpeg;base64,")
