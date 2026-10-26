"""AOS worker that screenshots the macOS desktop and describes it.

Loaded through AOS_WORKERS=screen_worker.py:Screen (see .env).
"""

import base64
import os
import subprocess
import tempfile
import time
from pathlib import Path

from aos.tasks import Step
from aos.worker import StepFailed, Worker
from aos.workspace import Workspace

SYSTEM = ("You describe screenshots of the user's desktop. "
          "Never repeat passwords, keys, or other secrets you see on screen.")


def take_screenshot() -> bytes:
    """Capture the full desktop as JPEG bytes (macOS `screencapture`)."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "screen.jpg")
        # -x: no shutter sound. Needs Screen Recording permission for your terminal.
        subprocess.run(["screencapture", "-x", "-t", "jpg", path], check=True)
        with open(path, "rb") as f:
            return f.read()


class Screen(Worker):
    name = "screen"
    description = (
        "Takes a screenshot of the user's macOS desktop right now and answers a question about it "
        "with a vision model. Use whenever the goal involves the user's screen, open windows or what "
        "they are doing. instructions = the question to answer about the screen (optional); inputs are "
        "ignored; writes output_dir/screen-<timestamp>.jpg and output_dir/screen-<timestamp>.md "
        "(the answer). Takes a few seconds."
    )

    def __init__(self, llm, capture=take_screenshot):
        self.llm = llm
        self.capture = capture

    def run(self, ws: Workspace, step: Step, log: Path) -> str:
        try:
            image = self.capture()
        except subprocess.CalledProcessError:
            raise StepFailed("Screenshot failed. Grant Screen Recording permission to this terminal in "
                             "System Settings > Privacy & Security > Screen Recording, then restart it.")
        out = ws.abspath(step.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        stem = out / f"screen-{time.strftime('%Y%m%d-%H%M%S')}"
        stem.with_suffix(".jpg").write_bytes(image)
        question = step.instructions or "Describe what is on the screen and what the user appears to be doing."
        reply = self.llm.chat([
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(image).decode()}"}},
            ]},
        ])
        answer = reply.content or ""
        stem.with_suffix(".md").write_text(f"# {question}\n\n{answer}\n")
        with open(log, "a") as f:
            f.write(f"screenshot {len(image)} bytes -> {ws.relpath(stem.with_suffix('.jpg'))}\n")
        return f"{ws.relpath(stem.with_suffix('.md'))}: {answer[:200]}"


if __name__ == "__main__":  # self-check with a fake screenshot and a fake model, no network
    from types import SimpleNamespace

    class FakeLLM:
        def chat(self, messages):
            assert messages[1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
            return SimpleNamespace(content="A terminal window.")

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace.create(Path(d) / "ws")
        log = Path(d) / "step.log"
        summary = Screen(FakeLLM(), capture=lambda: b"\xff\xd8jpeg").run(
            ws, Step(worker="screen", instructions="", output_dir="generated/screen"), log)
        files = sorted(p.suffix for p in (ws.root / "generated/screen").iterdir())
        assert files == [".jpg", ".md"], files
        assert "A terminal window." in summary
        print("ok:", summary)
