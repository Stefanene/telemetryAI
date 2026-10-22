# Telemetry AI

This is an agentic workflow for manageing everyday desktop tasks and securely using system telemetry for advanced features.

## Platforms

This agent uses OpenAI's SDK for LLM calls, wrapped in LangChain's DeepAgents harness for general purpose usecases and built-in filesystem tools, subagents, persistent memory, and skills.

## Setup

To setup this project, make sure you have the UV package manager installed. Then, to inititalize the virtual environment and install dependencies run:
```bash
uv init --bare
uv sync
```

Now you can run our code using:
```bash
uv run <file>.py
```