# Telemetry AI

This is an agentic workflow for managing everyday desktop tasks and securely using system telemetry for advanced features.

## Platforms

The agent runs on the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) (`openai-agents`), with models served by [Groq](https://console.groq.com/docs/openai) through its OpenAI-compatible endpoint (`https://api.groq.com/openai/v1`).

- **Agent model** (`GROQ_MODEL`, default `openai/gpt-oss-20b`): chats with you and decides when to call tools.
- **Vision model** (`GROQ_VISION_MODEL`, default `qwen/qwen3.8-27b`): reads screenshots inside the `look_at_screen` tool, since the gpt-oss models on Groq are text-only.

Tracing is disabled so screen contents are never uploaded to OpenAI's trace dashboard. Screenshots are sent only to Groq.

## Setup

To set up this project, make sure you have the UV package manager installed. Then, to initialize the virtual environment and install dependencies run:
```bash
uv sync
```

Create a `.env` in the repo root:
```bash
GROQ_API_KEY=gsk_...
GROQ_MODEL=openai/gpt-oss-20b            # optional
GROQ_VISION_MODEL=qwen/qwen3.8-27b       # optional
```

On macOS, grant Screen Recording permission to your terminal (System Settings > Privacy & Security > Screen Recording) so the agent can take screenshots.

## Running the agent

```bash
uv run agent.py
```

Ask questions about your screen (e.g. "What am I working on?"). The conversation is remembered until you quit with an empty line.

The agent decides from its system prompt when it needs to see your screen: it takes a screenshot for screen questions ("What app am I using?", "Is there an error?") and answers directly otherwise. Each screenshot prints a `[screenshot: ...]` line and is saved to `screenshots/screen-<timestamp>.jpg`. That folder is gitignored because screens can contain secrets, and nothing deletes old screenshots, so clean it out yourself.
