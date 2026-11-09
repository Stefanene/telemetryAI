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

With `DESKTOP_CONTROL=1` the agent also gets `operate_desktop`. That tool hands a task to a desktop operator (`desktop.py`), which sees a fresh 1280-px screenshot before every step and clicks, types and presses keys until the task is done. It drives your real mouse and keyboard, so it's off by default. Each operator run has its own `screenshots/<run-id>/actions.jsonl` and SQLite evidence graph. If clicks land off target, set `DESKTOP_SCALE` (screen points per screenshot pixel).

```bash
DESKTOP_CONTROL=1 uv run agent.py                                  # chat, with desktop control
DESKTOP_CONTROL=1 uv run agent.py "Open Safari and go to example.com"   # one task, prints a JSON result line
```

## Skills

The desktop operator gets general working habits from `skills/*.md`. Currently one skill, `skills/desktop_task.md`, with sections on avoiding loops, finishing honestly, and handling files. Skills are deliberately **not** step-by-step solutions to specific tasks or apps, so eval results measure the agent rather than memorized answers. Each file has a short header and a few bullets:

```markdown
---
name: desktop_task
description: General habits for doing a desktop task without getting stuck, and reporting it honestly.
triggers: always
---
### Avoid loops
- If the app you need is already open or in front, use it. Do not search for it or launch it again.
```

A skill applies when one of its `triggers` appears as a word in the task (`triggers: always` applies to every task). Matching skills are appended to the operator's instructions for that run (`skills.py`, used in `desktop.run_operator`), so they cost no extra model turns. To add one, drop a new `.md` file in `skills/`; `tests/test_skills.py` checks every skill file parses.

## Evaluating desktop tasks

`evals/desktop/` runs 15 macOS tasks (9 sanity checks, 6 challenges) against the agent, grades each by the state it leaves in `~/telem-eval`, and has a judge model describe the recorded screen. See [evals/desktop/README.md](evals/desktop/README.md).

```bash
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --only calculator new_folder
uv run python evals/desktop/run_desktop.py --report
```

Offline tests (graders, eval harness, desktop operator; no GUI, screenshots or API calls):

```bash
uv sync --extra desktop-eval --group dev && uv run pytest -q
```

## Knowledge graph and telemetry

The operator now receives bounded front-app, window, accessibility and workspace observations,
with a run-local SQLite evidence graph. It can inspect artifacts and check model-declared requirements
against fresh file evidence. Checks are not independent task grades; cross-run memory is disabled.

Configure explicit workspace roots with `TELEMETRY_ROOTS` (JSON array of absolute directory paths).
Without roots, no file inspection is allowed. `TELEMETRY_ENABLED=0|1` and
`KNOWLEDGE_GRAPH_ENABLED=0|1` independently control the two capabilities. `VERIFICATION_ENABLED=0|1`
controls optional file checks (requires telemetry, works without the graph). Legacy `TELEMETRY_MODE`
presets still work; explicit flags win. All configurations use `DESKTOP_MAX_TURNS=40` by default.

The harness presets `base`, `telemetry-only`, `knowledge-only` and `telemetry-knowledge` cover all four
combinations with verification off. You can also override each capability directly:

```bash
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --agent base --telemetry --no-knowledge-graph --skip-description
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --agent base --no-telemetry --knowledge-graph --skip-description
```

Graph-only organizes task/action history without reading UI/file telemetry. Graph-off runs do not
construct or query a graph. Resolved switches are recorded and CLI variants get separate result folders.

See [the implementation, fairness boundaries and evaluation handoff](docs/knowledge-telemetry.md)
for configuration, comparisons, limitations and commands. No live performance improvement has yet
been measured. Offline tests block network access and use scripted models instead of paid API calls.

## Graph snapshots

Graph-enabled runs save SVG snapshots in `screenshots/<run-id>/graph_snapshots/`, with the latest
view in `latest.svg` and complete graph data in `latest.json`. Install `uv sync --extra graph-viz`
for `latest.png` too. By default, snapshots follow logical graph updates and keep the latest 20;
set `GRAPH_VISUALIZATION=final|off` or `GRAPH_SNAPSHOT_KEEP` to change this. Graph-off runs produce
no graph images. See the handoff document for offline export, limits and benchmark timing guidance.
