# Desktop task eval

Fifteen macOS tasks (`tasks.json`) graded by the state they leave in `~/telem-eval` (deleted and
recreated before every run). **Nine are sanity checks; six are challenge tests.** Categories are
explicit in the task definitions, printed during runs, and reported separately. Difficulty labels
describe the intended role of each case, not measured agent performance.

The runner also screenshots every 2 s and asks a judge model (`--judge-model`, default `JUDGE_MODEL`
or `gpt-6-luna`, on OpenAI) to describe sampled frames. Keyword
hits measure **description coverage only**, not correctness, successful recovery, or truthful
completion. A negated sentence can contain every keyword. The report's `coverage` column keeps
this metric separate from the independently checked `pass` column.

```
uv sync --extra desktop-eval --group dev
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --category sanity          # our agent (telemetry)
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --category challenge --reps 3
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --reps 3
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --agent claude-code --only new_folder
uv run python evals/desktop/run_desktop.py --describe-only   # re-grade, no desktop
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

The TextEdit fixtures close TextEdit **without saving existing documents** before setup; save your
work first. The blocked-destination case changes permissions only within the eval sandbox and
restores them after grading, including when agent execution fails. Do not run evals concurrently:
they share the desktop and sandbox. Run as a normal user, not root, so permission denial is meaningful.

## Cases

| ID | Classification | Required outcome |
|---|---|---|
| `textedit_save`, `finder_rename`, `new_folder`, `trash_file`, `calculator`, `safari_url`, `copy_paste`, `open_quit_app` | **SANITY CHECKS (legacy)** | Existing eight basic probes, retained for continuity. |
| `exact_save` | **SANITY CHECK** | Exact multiline text at `final.txt`; similarly named draft and unrelated file unchanged. |
| `preserve_formatting` | **CHALLENGE** | Change one budget value in `brief.rtf`; preserve all other text, bold heading, and italic note. |
| `replace_stale_output` | **CHALLENGE** | Replace outdated contents at the original path; leaving a stale file and saving a new copy fails. |
| `duplicate_names` | **CHALLENGE** | Select the Orion document using content and location; update it while preserving the Vega decoy. |
| `move_with_stale_editor` | **CHALLENGE** | An archived copy starts open in TextEdit. Move the incoming document, edit its destination, preserve the archive, and leave no source file behind. |
| `pdf_export` | **CHALLENGE** | Valid, one-page PDF at the exact path containing all source text; preserve the source. |
| `blocked_destination` | **CHALLENGE** | Use the explicitly permitted fallback after a blocked save; preserve protected contents and permissions. |

New fixtures and graders live in `reliability.py`. Grading uses exact bytes for plain text, `pypdf`
for PDF structure/text, and macOS `textutil` conversion to DOCX for semantic bold/italic run checks.
The rich-text check does not claim pixel-perfect layout preservation. PDF text extraction checks
content, not visual fidelity. Every new case checks an unrelated sentinel file for collateral damage.
Offline tests exercise valid solutions and counterexamples; they do not demonstrate live agent success.

The move case creates a stale **archived copy**, not an unsaved buffer of the moved inode: macOS may
automatically track an open document when its original file moves. Outcome graders verify final
state, not that a particular click occurred. The blocked-save case also cannot prove an attempted
save from final state alone; inspect the recorded trajectory for that behavior.

Legacy graders are intentionally unchanged. Their limitations include substring matching for text
and URLs, absence-only Trash checks, and checking only that Chess is not running. Do not use those
sanity probes alone to support reliability claims; the new exact checks reject plausible wrong results.

## Completion claims and access tracks

Read `agent_output.txt` and, where necessary, the frames. Add a human-reviewed `claim_review.json`
beside `run.json`:

```json
{"claimed_success": true, "notes": "Agent explicitly claimed the requested file was saved."}
```

Use `false` when the agent reports failure, uncertainty, or no completion claim. Omit the file for
unreviewed runs. `--report` reads these annotations and prints `reviewed` plus `F/C`: incorrect
completion claims divided by completion claims **among reviewed runs**. With no positive claims,
`F/C` is undefined (`-`), not zero. Outcome checks alone do not establish honest reporting of the
fallback path; include that in the review notes. Claims are never inferred from description keywords.

The known agent configurations declare `gui`, `gui+telemetry` or `outcome` access tracks, stored in each run and
kept separate in reports. `--track gui|gui+telemetry|outcome` records an explicit override if you change an agent's
tools; this is a declaration, not enforcement. `telemetry` uses GUI actions plus read-only workspace/accessibility observations, so its track is
`gui+telemetry`. `telemetry-screenshot` retains screenshot-only GUI observations. All configurations
now default to 40 operator model turns (`DESKTOP_MAX_TURNS`, including inspection/check calls). Record model/settings and budgets when
comparing runs; challenge cases may exhaust that budget.

Offline validation (no screenshots, GUI actions, models, or API keys):

```
uv run pytest -q tests/test_desktop_reliability.py tests/test_desktop.py tests/test_desktop_eval.py
```

RTF conversion cases need macOS `textutil` and are skipped elsewhere; install the `desktop-eval`
extra to run PDF cases. Desktop operator regressions (`tests/test_desktop.py`, scripted model) cover
action errors and recovery, invalid key combos, turn-limit failure, and screenshot failure. Harness tests
check independent scoring, timeout output, permission cleanup, access tracks, and claim denominators.

## Telemetry and graph comparisons

See [the evaluation handoff](../../docs/knowledge-telemetry.md) for all four configurations, observation
access, leakage boundaries and held-out evaluation requirements. `--skip-description` avoids the optional
paid description judge; live agents still require model credits. The independent artifact graders
remain unchanged. Enhanced configurations have their own `gui+telemetry` access track; do not attribute
their extra read access to graph structure alone. Cross-run memory is disabled.

## Independent switches

| Preset (`--agent`) | Telemetry | Knowledge graph | Verification |
|---|---|---|---|
| `base` | off | off | off |
| `telemetry-only` | on | off | off |
| `knowledge-only` | off | on | off |
| `telemetry-knowledge` | on | on | off |

Alternatively use `--agent base` with `--telemetry` / `--no-telemetry` and `--knowledge-graph` /
`--no-knowledge-graph`. `--verification` is a separate optional intervention requiring telemetry.
CLI overrides beat preset values, are recorded under `operator_features`, and get distinct output
labels (for example `base-t0-kg1-v0`). Access tracks follow resolved telemetry access.

The graph-only arm retains task/action relationships and receives no UI or file telemetry. The
telemetry-only arm never constructs a graph. Harness monitoring and independent grading still run
in all arms, but their data is not supplied to the operator. All four presets keep verification off,
with identical action tools, shared skills and budgets. Cross-run memory stays disabled.
