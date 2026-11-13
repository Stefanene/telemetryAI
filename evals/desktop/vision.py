"""Final-category vision tasks: a random image shown only on screen, graded from runner memory.

The PNG is rendered outside the sandbox, opened in Preview, then deleted, so the answer exists
only as pixels. ANSWERS keeps the truth in this process between setup and grading; nothing
about it is written to disk.
"""

import json
import random
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

TASKS = {"image_code", "shape_count", "clock_time", "transcribe_image", "circled_file"}
ANSWERS: dict[str, str] = {}
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L lookalikes
NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six"]
LETTERS = "abcde"
rng = random.SystemRandom()


def _font(size):
    from PIL import ImageFont
    return ImageFont.load_default(size=size)


def _canvas(width=900, height=500):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (width, height), "white")
    return image, ImageDraw.Draw(image)


def _image_code():
    from PIL import Image, ImageDraw
    code = "".join(rng.choice(CODE_ALPHABET) for _ in range(6))
    image, draw = _canvas()
    for _ in range(12):
        draw.line([(rng.randint(0, 900), rng.randint(0, 500)), (rng.randint(0, 900), rng.randint(0, 500))],
                  fill=(170, 170, 170), width=3)
    for n, char in enumerate(code):
        glyph = Image.new("RGBA", (120, 140), (0, 0, 0, 0))
        ImageDraw.Draw(glyph).text((20, 10), char, font=_font(100), fill=(30, 30, 30))
        glyph = glyph.rotate(rng.uniform(-20, 20), expand=True)
        image.paste(glyph, (90 + n * 120, 170 + rng.randint(-25, 25)), glyph)
    return image, code


def _shape_count():
    count = rng.randint(0, 6)
    others = [(s, c) for s in ("circle", "square", "triangle") for c in ("red", "blue", "green") if (s, c) != ("circle", "red")]
    cells = [("circle", "red")] * count + [rng.choice(others) for _ in range(16 - count)]
    rng.shuffle(cells)
    image, draw = _canvas(560, 560)
    for n, (shape, color) in enumerate(cells):
        x, y = 40 + (n % 4) * 125, 40 + (n // 4) * 125
        box = [x + 15, y + 15, x + 95, y + 95]
        if shape == "circle":
            draw.ellipse(box, fill=color)
        elif shape == "square":
            draw.rectangle(box, fill=color)
        else:
            draw.polygon([(x + 55, y + 15), (x + 15, y + 95), (x + 95, y + 95)], fill=color)
    return image, str(count)


def _clock_time():
    import math
    hour, minute = rng.randint(1, 12), rng.choice(range(0, 60, 5))
    image, draw = _canvas(520, 520)
    cx = cy = 260
    draw.ellipse([30, 30, 490, 490], outline="black", width=6)
    for h in range(1, 13):
        a = math.radians(h * 30 - 90)
        draw.text((cx + 195 * math.cos(a), cy + 195 * math.sin(a)), str(h), font=_font(34), fill="black", anchor="mm")
    for angle, length, width in [((hour % 12 + minute / 60) * 30, 120, 12), (minute * 6, 180, 6)]:
        a = math.radians(angle - 90)
        draw.line([(cx, cy), (cx + length * math.cos(a), cy + length * math.sin(a))], fill="black", width=width)
    draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill="black")
    return image, f"{hour}:{minute:02d}"


def _transcribe_image():
    sentence = (f"Order {rng.randint(1000, 9999)} ships "
                f"{rng.choice(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'])} "
                f"to {rng.choice(['Lyon', 'Porto', 'Gdansk', 'Bergen', 'Turin', 'Ghent'])}.")
    image, draw = _canvas(1000, 300)
    draw.text((500, 150), sentence, font=_font(48), fill="black", anchor="mm")
    return image, sentence


def _circled_file():
    chosen = rng.choice(LETTERS)
    image, draw = _canvas(600, 520)
    for n, letter in enumerate(LETTERS):
        y = 60 + n * 90
        draw.text((150, y), f"invoice-{letter}.txt", font=_font(40), fill="black")
        if letter == chosen:
            draw.ellipse([110, y - 20, 520, y + 65], outline="red", width=6)
    return image, chosen


RENDER = {"image_code": _image_code, "shape_count": _shape_count, "clock_time": _clock_time,
          "transcribe_image": _transcribe_image, "circled_file": _circled_file}


def _osascript(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30).stdout.strip()


def _show(image):
    folder = Path(tempfile.mkdtemp())
    path = folder / "image.png"
    image.save(path)
    try:
        cleanup()
        for _ in range(10):  # LaunchServices can still report error -600 shortly after Preview quits
            if subprocess.run(["open", "-a", "Preview", str(path)], capture_output=True, timeout=30).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Preview could not be launched with the task image")
        for _ in range(20):
            if _osascript('tell application "Preview" to count windows') not in ("", "0"):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Preview did not open the task image")
        time.sleep(1)
    finally:
        shutil.rmtree(folder)  # Preview keeps the decoded image; nothing readable stays on disk


def setup(task_id: str, root: Path, open_apps=True) -> None:
    image, ANSWERS[task_id] = RENDER[task_id]()
    if task_id == "circled_file":
        for letter in LETTERS:
            (root / "inbox").mkdir(exist_ok=True)
            (root / "inbox" / f"invoice-{letter}.txt").write_text(f"Invoice {letter.upper()}\n")
        (root / "chosen").mkdir()
    if open_apps:
        _show(image)


def cleanup() -> None:
    try:
        _osascript('if application "Preview" is running then tell application "Preview" to quit')
        for _ in range(20):  # reopening while Preview is still quitting fails with LaunchServices error -600
            if subprocess.run(["pgrep", "-x", "Preview"], capture_output=True).returncode != 0:
                break
            time.sleep(0.5)
    except (OSError, subprocess.SubprocessError):
        pass


def answer_text(output: str) -> str:
    """The agent's final answer: "result" of the last JSON line (agent.py, claude -p), else raw output."""
    for line in reversed(output.strip().splitlines()):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "result" in data:
            return str(data["result"])
    return output


def _file_is(path: Path, text: str) -> bool:
    return path.is_file() and not path.is_symlink() and path.read_bytes() == text.encode()


def grade(task_id: str, root: Path, output: str) -> bool:
    answer, text = ANSWERS[task_id], answer_text(output)
    if task_id == "image_code":
        return re.search(rf"\b{answer}\b", text, re.I) is not None
    if task_id == "shape_count":
        # ponytail: substring match; an answer listing every number would pass, so review outliers by hand
        return re.search(rf"\b({answer}|{NUMBER_WORDS[int(answer)]})\b", text, re.I) is not None
    if task_id == "clock_time":
        hour, minute = map(int, answer.split(":"))
        return any(int(h) % 12 == hour % 12 and int(m) == minute
                   for h, m in re.findall(r"\b(\d{1,2}):(\d{2})\b", text))
    if task_id == "transcribe_image":
        return _file_is(root / "transcript.txt", answer + "\n")
    if task_id == "circled_file":
        rest = [letter for letter in LETTERS if letter != answer]
        return (sorted(p.name for p in (root / "chosen").iterdir()) == [f"invoice-{answer}.txt"]
                and _file_is(root / "chosen" / f"invoice-{answer}.txt", f"Invoice {answer.upper()}\n")
                and sorted(p.name for p in (root / "inbox").iterdir()) == [f"invoice-{l}.txt" for l in rest]
                and all(_file_is(root / "inbox" / f"invoice-{l}.txt", f"Invoice {l.upper()}\n") for l in rest))
    raise ValueError(f"unknown vision task: {task_id}")
