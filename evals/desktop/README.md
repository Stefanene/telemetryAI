# Desktop task eval

Eight basic macOS tasks (`tasks.json`) graded by the state they leave in `~/aos-eval` (deleted and
recreated before every run), plus a description score: this runner screenshots every 2 s during each
run and a judge model (`--judge-model`, default `JUDGE_MODEL` or `gpt-6-luna`, on OpenAI) describes the frames, scored by keyword hits, so every agent is described the same way.

```
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --reps 3                       # our agent
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --agent claude-code --only new_folder
uv run python evals/desktop/run_desktop.py --describe-only            # re-grade, no desktop
uv run python evals/desktop/run_desktop.py --report
```

Agents are command templates in `agents.json` (`{instruction}` is replaced, shell-quoted):

- `telemetry` (default): our agent, `agent.py "<task>"`. The chat agent hands the task to
  `operate_desktop` (`desktop.py`), and its last output line is JSON with the result and token counts.
- `claude-code`, `codex`: outcome track. They may use the shell (`mkdir`, `mv`, `osascript`), so
  compare them to `telemetry` on pass rate, not on GUI skill. Both run unattended with shell access.
- `claude-code-gui`: GUI track, shell disabled. Needs `computer-mcp.json` pointing at a
  computer-control MCP server of your choice.

The terminal running this needs Screen Recording and Accessibility permission. Results go to `runs/`
(git-ignored), one folder per run with frames, agent output, description and `run.json`.
