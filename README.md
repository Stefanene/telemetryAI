# Telemetry AI

This is an agentic workflow for managing everyday desktop tasks and securely using system telemetry for advanced features.

## Platforms

The agent runs on the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) (`openai-agents`) with OpenAI models:

- **Agent model** (`MODEL`, default `gpt-6-luna`): chats with you and decides when to call tools.
- **Vision model** (`VISION_MODEL`, defaults to `MODEL`): reads screenshots in `look_at_screen` and operates the desktop in `operate_desktop`.

Tracing is disabled so screen contents never go to OpenAI's trace dashboard. Screenshots are still sent to the OpenAI API for the model to read.

## Setup

To set up this project, make sure you have the UV package manager installed. Then, to initialize the virtual environment and install dependencies run:
```bash
uv sync
```

Create a `.env` in the repo root:
```bash
OPENAI_API_KEY=sk-...
MODEL=gpt-6-luna           # optional
VISION_MODEL=gpt-6-luna    # optional
JUDGE_MODEL=gpt-6-luna     # optional, the eval's judge
```

On macOS, grant Screen Recording permission to your terminal (System Settings > Privacy & Security > Screen Recording) so the agent can take screenshots. Desktop control also needs Accessibility permission (same settings page).

## Running the agent

```bash
uv run agent.py
```

Ask questions about your screen (e.g. "What am I working on?"). The conversation is remembered until you quit with an empty line.

The agent decides from its system prompt when it needs to see your screen: it takes a screenshot for screen questions ("What app am I using?", "Is there an error?") and answers directly otherwise. Each screenshot prints a `[screenshot: ...]` line and is saved to `screenshots/screen-<timestamp>.jpg`. That folder is gitignored because screens can contain secrets, and nothing deletes old screenshots, so clean it out yourself.

## Desktop control

With `DESKTOP_CONTROL=1` the agent also gets `operate_desktop`. That tool hands a task to a desktop operator (`desktop.py`), which sees a fresh 1280-px screenshot before every step and clicks, types and presses keys until the task is done. It drives your real mouse and keyboard, so it's off by default. Every action is logged to `screenshots/actions.jsonl`. If clicks land off target, set `DESKTOP_SCALE` (screen points per screenshot pixel).

```bash
DESKTOP_CONTROL=1 uv run agent.py                                  # chat, with desktop control
DESKTOP_CONTROL=1 uv run agent.py "Open Safari and go to example.com"   # one task, prints a JSON result line
```

## Evaluating desktop tasks

`evals/desktop/` runs 15 macOS tasks (9 sanity checks, 6 challenges) against the agent, grades each by the state it leaves in `~/aos-eval`, and has a judge model describe the recorded screen. See [evals/desktop/README.md](evals/desktop/README.md).

```bash
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --only calculator new_folder
uv run python evals/desktop/run_desktop.py --report
```

Offline tests (graders, eval harness, desktop operator; no GUI, screenshots or API calls):

```bash
uv sync --extra desktop-eval --group dev && uv run pytest -q
```

## Planned: knowledge graph and telemetry

Placeholders for the next layer, not implemented yet:

- `telemetry.py`: read-only macOS collectors (front app, windows, accessibility tree, system stats, logs, sandbox file events) to inform the agent's decisions and enrich eval runs.
- `knowledge.py`: a knowledge graph of tasks, runs, apps, files, UI elements, actions and graded outcomes (backend to be chosen, e.g. graphify), for recall and decision/task evaluation. Stored in `knowledge/` (gitignored).

Every place they plug in is marked:

```bash
grep -rn "TODO(knowledge\|TODO(telemetry" agent.py desktop.py evals/desktop/run_desktop.py pyproject.toml
```
