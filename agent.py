import os
from dotenv import load_dotenv
from deepagents import create_deep_agent

load_dotenv()

api_key = os.environ.get("OPENAI_API_KEY")
model_name = os.environ.get("MODEL", "gpt-6-luna")

if not api_key:
    raise ValueError("Please set your OPENAI_API_KEY environment variable.")

print(f"Initializing Deep Agent with model: {model_name}")

agent = create_deep_agent(
    model=model_name,
    tools=[],
    system_prompt="You are a meticulous assistant. Use your built-in planning tool to map out multi-step tasks.",
)

inputs = {"messages": [("user", "Draft a short essay on why agentic loops need a virtual file system.")]}

for event in agent.stream(inputs):
    for node, output in event.items():
        print(f"\n--- Node Executed: {node} ---")
        
        if output and isinstance(output, dict) and "messages" in output:
            if output["messages"]:
                print(output["messages"][-1].content)

