import base64
import os
import subprocess
import tempfile

from dotenv import load_dotenv
from deepagents import create_deep_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

load_dotenv()

api_key = os.environ.get("OPENAI_API_KEY")
model_name = os.environ.get("MODEL", "gpt-6-luna")

if not api_key:
    raise ValueError("Please set your OPENAI_API_KEY environment variable.")

print(f"Initializing Deep Agent with model: {model_name}")

llm = ChatOpenAI(model=model_name)


def take_screenshot() -> bytes:
    """Capture the full desktop as JPEG bytes (macOS `screencapture`)."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "screen.jpg")
        # -x: no shutter sound. Needs Screen Recording permission for your terminal.
        subprocess.run(["screencapture", "-x", "-t", "jpg", path], check=True)
        with open(path, "rb") as f:
            return f.read()


@tool
def look_at_screen(question: str = "Describe what is on the screen and what the user appears to be doing.") -> str:
    """Take a screenshot of the user's desktop and answer a question about it.
    Use whenever the user asks about their screen, open windows, or what they are doing."""
    try:
        image = base64.b64encode(take_screenshot()).decode()
    except subprocess.CalledProcessError:
        return ("Screenshot failed. Grant Screen Recording permission to this terminal in "
                "System Settings > Privacy & Security > Screen Recording, then restart it.")
    # ponytail: vision call happens inside the tool and returns text; pass images to the agent directly if it needs pixel-level follow-ups
    reply = llm.invoke([HumanMessage(content=[
        {"type": "text", "text": question},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
    ])])
    return reply.text


agent = create_deep_agent(
    model=llm,
    tools=[look_at_screen],
    system_prompt=(
        "You are a desktop assistant. Use the look_at_screen tool to see the user's screen, "
        "explain what is happening on it, and answer questions about it. "
        "Never repeat passwords, keys, or other secrets you see on screen."
    ),
    checkpointer=InMemorySaver(),
)

config = {"configurable": {"thread_id": "desktop"}}

if __name__ == "__main__":
    print("Ask about your screen (empty line to quit).")
    while question := input("\n> ").strip():
        result = agent.invoke({"messages": [("user", question)]}, config)
        print(result["messages"][-1].text)
