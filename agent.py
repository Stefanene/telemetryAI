import json
import os
import subprocess
import sys

from agents import Agent, Runner, SQLiteSession, function_tool, set_tracing_disabled
from dotenv import load_dotenv
from openai import OpenAI

from desktop import SCREENSHOT_DIR, VISION_MODEL as vision_model, image_url, operate_desktop, operator_usage, take_screenshot

load_dotenv()

if not os.environ.get("OPENAI_API_KEY"):
    raise ValueError("Please set OPENAI_API_KEY in .env.")
model = os.environ.get("MODEL", "gpt-6-luna")

# Tracing uploads runs to OpenAI's dashboard; keep screen contents local.
set_tracing_disabled(True)
vision = OpenAI()


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
    reply = vision.chat.completions.create(model=vision_model, messages=[{"role": "user", "content": [
        {"type": "text", "text": f"{question}\nAnswer concisely."},
        {"type": "image_url", "image_url": {"url": image_url(path)}},
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
        "- To do something in a desktop app (open, click, type, save, rename...), call operate_desktop "
        "with a self-contained task, then report its summary and any answer it found.\n"
        "- Never repeat passwords, keys, or other secrets you see on screen.\n"
        "Examples:\n"
        "  'What app am I using?' -> call look_at_screen.\n"
        "  'Is there an error visible?' (right after another screen question) -> call look_at_screen again.\n"
        "  'What does this code do?' -> call look_at_screen.\n"
        "  'What is 2+2?' -> answer directly, no tool.\n"
        "  'What did I just ask?' -> answer from the conversation, no tool."
    ),
    model=model,
    # operate_desktop drives the real mouse and keyboard, so it is opt-in.
    # TODO(telemetry, knowledge): + telemetry.TELEMETRY_TOOLS + [a `recall` tool over knowledge.query]
    tools=[look_at_screen] + ([operate_desktop] if os.environ.get("DESKTOP_CONTROL") == "1" else []),
)

session = SQLiteSession("desktop")

if __name__ == "__main__" and len(sys.argv) > 1:  # one task, one JSON line (evals/desktop/agents.json)
    result = Runner.run_sync(agent, " ".join(sys.argv[1:]), max_turns=20)
    usage = result.context_wrapper.usage
    usage.add(operator_usage)
    print(json.dumps({"result": result.final_output, "total_cost_usd": None,  # ponytail: tokens only; multiply by your model's price for USD
                      "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}))
elif __name__ == "__main__":
    print(f"Desktop assistant ({model}, vision: {vision_model}). Empty line to quit.")
    while question := input("\n> ").strip():
        print(Runner.run_sync(agent, question, session=session).final_output)
