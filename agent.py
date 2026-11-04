import base64
import os
import subprocess
from datetime import datetime
from pathlib import Path

from agents import Agent, OpenAIChatCompletionsModel, Runner, SQLiteSession, function_tool, set_tracing_disabled
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1"
api_key = os.environ.get("GROQ_API_KEY")
if not api_key:
    raise ValueError("Please set GROQ_API_KEY in .env.")
model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
# gpt-oss models are text-only on Groq, so screenshots go to a vision model.
vision_model = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")

# Tracing uploads runs to OpenAI's dashboard; keep screen contents local.
set_tracing_disabled(True)
vision = OpenAI(base_url=GROQ_URL, api_key=api_key)

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


def take_screenshot() -> Path:
    """Capture the full desktop to screenshots/screen-<timestamp>.jpg (macOS `screencapture`)."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    path = SCREENSHOT_DIR / f"screen-{datetime.now():%Y%m%d-%H%M%S-%f}.jpg"
    # -x: no shutter sound. Needs Screen Recording permission for your terminal.
    subprocess.run(["screencapture", "-x", "-t", "jpg", str(path)], check=True)
    return path


@function_tool
def look_at_screen(question: str = "Describe what is on the screen and what the user appears to be doing.") -> str:
    """Take a screenshot of the user's desktop and answer a question about it.
    Use whenever the user asks about their screen, open windows, or what they are doing."""
    try:
        path = take_screenshot()
    except subprocess.CalledProcessError:
        return ("Screenshot failed. Grant Screen Recording permission to this terminal in "
                "System Settings > Privacy & Security > Screen Recording, then restart it.")
    print(f"[screenshot: {path.relative_to(SCREENSHOT_DIR.parent)}]")
    image = base64.b64encode(path.read_bytes()).decode()
    # Groq on-demand caps output tokens per minute and reserves max_tokens up front; keep it small.
    reply = vision.chat.completions.create(model=vision_model, max_tokens=400, messages=[{"role": "user", "content": [
        {"type": "text", "text": f"{question}\nAnswer concisely."},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
    ]}])
    return reply.choices[0].message.content or ""


agent = Agent(
    name="Desktop assistant",
    instructions=(
        "You are a desktop assistant for the user's Mac.\n"
        "Rules:\n"
        "- You cannot see the screen unless you call the look_at_screen tool. Never guess or invent "
        "what is on the screen.\n"
        "- Call look_at_screen whenever the question needs visual context from the desktop (the screen, "
        "windows, apps, errors, 'this', 'here', what the user is doing), or whenever you cannot answer "
        "from the conversation alone.\n"
        "- Each screenshot shows only the moment it was taken. For every new question about the screen, "
        "call look_at_screen again, even if you looked a moment ago.\n"
        "- Do not call it for questions that do not involve the screen: math, general knowledge, or "
        "recalling what was said earlier in this conversation.\n"
        "- Never repeat passwords, keys, or other secrets you see on screen.\n"
        "Examples:\n"
        "  'What app am I using?' -> call look_at_screen.\n"
        "  'Is there an error visible?' (right after another screen question) -> call look_at_screen again.\n"
        "  'What does this code do?' -> call look_at_screen.\n"
        "  'What is 2+2?' -> answer directly, no tool.\n"
        "  'What did I just ask?' -> answer from the conversation, no tool."
    ),
    model=OpenAIChatCompletionsModel(model=model, openai_client=AsyncOpenAI(base_url=GROQ_URL, api_key=api_key)),
    tools=[look_at_screen],
)

session = SQLiteSession("desktop")

if __name__ == "__main__":
    print(f"Desktop assistant on Groq ({model}, vision: {vision_model}). Empty line to quit.")
    while question := input("\n> ").strip():
        print(Runner.run_sync(agent, question, session=session).final_output)
