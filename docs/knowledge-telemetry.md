# Live evidence for desktop reasoning

The operator always receives a fresh screenshot. With telemetry enabled it also receives bounded
read-only observations before each decision. The knowledge graph is independently optional.
It can inspect artifacts to resolve ambiguous document identity and verify saved outputs. A run-local
SQLite graph relates paths, file versions, applications, windows, observations, actions and declared
goal conditions. It records provenance and temporal order; it does not infer causation from order.

## Implemented data flow

1. Create a unique run directory. Capture an initial workspace manifest only when telemetry is on;
   create an empty graph only when the graph is on. No previous graph is opened.
2. Capture the main display. When telemetry is enabled, collect the frontmost app, its windows and
   bounded accessibility tree; scan the configured workspace for metadata/content hashes and changes.
3. Append a decision packet to the screenshot input. The packet is ephemeral, not appended to the
   conversation history. Relevant state and inspection results are retained explicitly in run state.
4. Execute one mouse/keyboard action. Record its transport result, invalidate old inspection/check
   status and collect observations before the next decision. `ok` only means the action executed.
5. With telemetry enabled, the operator can inspect a specific artifact: UTF-8 text, file metadata, PDF page count/text, or
   rich-text semantic runs via native `textutil`. These tools cannot write files or run arbitrary commands.
6. With verification enabled, the model declares conditions citing exact passages from the user's request,
   then verifies and finishes. Checks re-read artifacts, including once more before returning the
   final operator result. Failed, missing or inaccessible evidence cannot produce a passed check.

Window titles are never automatically resolved to file paths. Same-named files remain separate.
File versions include path, hash and observation metadata; an inode is not treated as permanent
identity. Matching inode/device/content across a delete/create pair yields an explicitly **inferred**
possible-move relation. Earlier versions remain historical and cease to be current.

The graph is implemented using standard-library SQLite, with locks for SDK worker-thread tool
execution. UI element detail stays in bounded observation records; it is not assigned a misleading
permanent identity across accessibility snapshots. Screenshot coordinates remain pixels; accessibility
bounds are labeled screen points and are not automatically converted into clicks.

## What checks establish

Available predicates: existence, absence, exact text, text containment, unchanged file bytes and
permissions, explicit octal permissions, PDF page count/text containment, and preservation of selected semantic
bold/italic fragments from a real pre-edit inspection. Checks can be combined. Expected text must be chosen from the task or actual source inspection; there is no benchmark-specific PDF checker in the agent.
Rich-text inspection preserves semantic runs, not pixel-perfect layout. `unchanged` applies to files;
directory contents require separate conditions on their relevant files.

The structured `declared_checks_passed` result is deliberately narrower than task success. A model
can omit requirements, misinterpret an instruction, quote an irrelevant passage, or choose a weak
predicate. Literal quote validation establishes provenance, not semantic entailment. The independent
evaluator must still grade the final artifacts and review completion claims. Visual-only results
currently remain unverified in this file-check protocol; a model's screen description is not used as
an independent certificate. The parent is instructed to preserve these limitations when reporting.

## Leakage and comparison boundaries

- Runtime modules do not import benchmark fixtures, task definitions, graders, test code, or human
  claim reviews. There is no task-ID dispatch, embedded expected fixture content or solution trajectory.
- Input consists of the user task, actual desktop state and artifacts within explicitly configured
  workspace roots. A workspace is observable environment data, not a hidden answer key. Keep grading
  files and answer keys outside it. The runner supplies **only** the workspace path and output location;
  it does not supply graders, task IDs, expected outputs, scores or fixture metadata to the agent.
- Read tools reject repository paths, broad home/root scopes, hidden/credential files, path escapes
  and symlinks. Run outputs must be outside observable workspaces. This is scoped access for a normal
  single-user desktop, not a security boundary against malicious concurrent filesystem replacement.
- Each run uses an isolated graph and artifact directory. Cross-run retrieval is disabled. Evaluation
  analysis is written beside grader outputs; the runtime never reads it. A later memory experiment
  requires a separately frozen development corpus and a new evaluation protocol.
- File and accessibility access is an **additional observation capability**. Report the enhanced agent
  as GUI actions plus telemetry, not as screenshot-only GUI interaction. Compare to an equal-information
  baseline when attributing improvements to the graph.
- Telemetry and the graph are independent switches. Telemetry-only and telemetry+graph receive the
  same raw UI/file observations and inspection tools. The graph adds retained relationships and
  structured action history; telemetry-only does not construct a hidden graph. This measures the
  graph mechanism, including its retention/inferences, rather than just alternative JSON formatting.
- Graph-only uses the user task and executed-action history already available to the base agent.
  It does not collect UI trees, front-app/window data, workspace manifests or artifact contents.
  No visual facts are invented from screenshots; screenshots continue through the ordinary base input.
- Verification is independently switchable, requires telemetry, and works with the graph off.
  Keep verification off across the four-way telemetry/graph experiment to avoid confounding its effect.
  Compare it separately with identical telemetry/graph settings. Shared skills/actions/budgets stay fixed.
- General user documents can themselves contain instructions; observations are explicitly labeled
  untrusted data. Redaction minimizes obvious credentials but does not guarantee secret-free arbitrary
  text or screenshots. Only configure roots appropriate to send to the model API.

## Configuration and artifacts

```bash
# Create a dedicated workspace yourself. Never point roots at the repo or your entire home.
export TELEMETRY_ROOTS='["/absolute/path/to/task-workspace"]'
export TELEMETRY_ENABLED=1
export KNOWLEDGE_GRAPH_ENABLED=1
export VERIFICATION_ENABLED=0  # optional, requires telemetry; independent of the graph
export DESKTOP_MAX_TURNS=40     # same budget for all comparison arms
DESKTOP_CONTROL=1 uv run agent.py "Your desktop task"
```

Without roots, UI observations work but file inspection cannot access any files. Root configuration
must precede process launch. `TELEMETRY_RUN_DIR` optionally chooses the artifact parent; otherwise
runs live in `screenshots/<random-run-id>/` with screenshots and `actions.jsonl`. With the graph on,
`state.sqlite` stores configuration, input packets, observations, inspections, actions and claims.
With the graph off, an ordinary `events.jsonl` journal records diagnostics; no graph is constructed.
No screenshot bytes are stored in graph rows. Inspect these artifacts locally; do not commit them.

All flags accept `0`/`1` or `false`/`true`. Explicit flags override legacy `TELEMETRY_MODE` presets:
`screenshot` = neither, `flat` = telemetry only, `graph` = both without verification, `verified` = both
with verification. Without explicit settings the legacy verified default is retained. Turning telemetry
off also defaults verification off; explicitly requesting verification with telemetry off is an error.
There is no dependency between the telemetry and graph flags.

Collectors use a 5-second command timeout, a 100-node accessibility budget and depth cap, a bounded
workspace scan (300 files/directories; files up to 1 MB), bounded inspection text, and a 32 KB decision
packet cap. Incomplete scans and truncated packets are labeled. Missing data is unknown, not proof of
absence. Large or non-UTF-8 text needs another inspection strategy. `system_snapshot` and `recent_logs`
are optional local diagnostics, not routine model inputs or agent tools.

## Saved graph visualizations

Graph-enabled runs save diagnostic images under `<run-directory>/graph_snapshots/`. These are
exports of the stored graph, not agent inputs, graders or extra observations. Graph-off runs do not
construct a graph or generate graph images.

- `latest.svg`: dependency-free, scalable image of the most recent exported graph.
- `latest.png`: the same diagram as a raster image when the optional `graph-viz` extra is installed.
- `latest.json`: complete stored nodes and edges, including historical/stale relationships.
- Numbered `.svg`, `.png` and `.json` files: retained snapshot history.

Images label node kinds and relationship names. Inferred relations are dashed amber; stale edges
are hidden in the image but retained in JSON/SQLite. The image is a compact view (up to 25 nodes,
5 per category, and 40 edges) and explicitly reports displayed/total counts. It is not a complete
rendering of a large graph. Long labels are shortened, typed document contents are omitted from
image labels, and paths show their last two components. The full JSON contains the same redacted,
bounded data held in SQLite, which can still contain private workspace information; keep it local.

```bash
uv sync --extra desktop-eval --extra graph-viz --group dev  # adds PNG support
export GRAPH_VISUALIZATION=updates  # default; alternatives: final or off
export GRAPH_SNAPSHOT_KEEP=20        # default; retain 1..200 snapshots, plus latest
```

`updates` exports after complete observations, actions, inspections, declared checks and verification,
plus initialization and close. Low-level node/edge SQL writes are grouped into these logical updates;
a caller making raw Graph mutations can call `graph.checkpoint("reason")` explicitly. `final` saves
only when the graph closes; `off` disables rendering/export entirely. A run killed without cleanup
may lack a final image; updates mode preserves earlier snapshots. The snapshot limit removes old
numbered images/JSON, not the SQLite history. Visualization settings are recorded with run configuration.

Rendering errors are reported diagnostically and do not turn a successful action into an agent error.
SVG output needs no optional packages. PNG is omitted when Pillow is unavailable. Rendering adds time
and storage overhead; set `GRAPH_VISUALIZATION=off` consistently when measuring agent latency without
diagnostic rendering, or report the enabled setting. There are no model calls for visualization.

Existing run databases can also be rendered offline without modifying them:

```bash
uv run python graph_visualizer.py /absolute/path/to/run/state.sqlite --output /absolute/path/to/export
```

## Handoff to the evaluation runner

Install dependencies and run offline checks first:

```bash
uv sync --extra desktop-eval --group dev
uv run pytest -q
```

The suite blocks network connections. Scripted models exercise the real SDK dispatch loop with mocked
screenshots and simulated actions. Native rich-text conversion and PDF parsing are exercised locally.
No API key, paid model call or live GUI action is needed by tests. This validates mechanics, **not**
live-agent success, correct planning, accessibility availability, or performance improvement.

The following commands are for the person running the **live** evaluation. They use paid agent calls
and control the real desktop. Existing fixtures close TextEdit without saving and recreate `~/aos-eval`;
save personal work first. Keep task apps on the main display. Run modes sequentially, not concurrently.

The harness has four presets with verification **off** in all four:

| `--agent` | Telemetry | Knowledge graph |
|---|---|---|
| `base` | off | off |
| `telemetry-only` | on | off |
| `knowledge-only` | off | on |
| `telemetry-knowledge` | on | on |

```bash
# Substitute any preset from the table.
DESKTOP_CONTROL=1 DESKTOP_MAX_TURNS=40 uv run python evals/desktop/run_desktop.py --agent base --category challenge --reps 3 --skip-description

# Equivalent explicit controls on the same base harness:
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --agent base --telemetry --no-knowledge-graph --skip-description
DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py --agent base --no-telemetry --knowledge-graph --skip-description
```

The CLI supports `--telemetry` / `--no-telemetry`, `--knowledge-graph` / `--no-knowledge-graph`, and
`--verification` / `--no-verification`. CLI overrides take precedence over preset assignments and the
resolved flags are recorded in each result. Override runs use distinct `-t0-kg1-v0` style folder labels
and report groups, so changing switches cannot overwrite another combination's results. Ordinary
reruns of the exact same combination still overwrite its previous task/rep folders.

`--skip-description` skips only the optional paid screenshot-description judge. Artifact graders are
unchanged. Tracks follow actual telemetry access: `gui` without it, `gui+telemetry` with it. Harness-side
monitoring/grading still runs for all arms and is never forwarded as operator input. Cross-run memory
remains disabled in every combination.
The budget is now 40 operator model turns for **every** mode (previous default was 15). The verified
mode spends some turns on checks, so report both total turns and GUI action counts, plus time/tokens.
Do not compare to historical 15-turn results as a controlled ablation.

Report challenge and sanity results separately: independent success, preservation violations, reviewed
false completion claims with coverage, latency and token cost. The optional description keyword metric
is coverage only. Independently inspect all positive claims; a passed internal check is not a label for
human claim review. Archive results before rerunning the same agent/task/rep: the existing harness
overwrites those folders. Use the same model, settings, fixtures and budgets in all arms. Vary filenames,
content, decoy location and starting windows for held-out evaluation. Because these challenge families
informed the design, results on the existing cases are development results, not untouched test evidence.
Randomize/counterbalance mode order for the final study; the desktop cannot be run in parallel.

Remaining limitations: no persistent experience retrieval, no automatic semantic completeness proof,
no stable window-to-document binding when macOS does not expose a document URL, and no measured live
performance yet. Review telemetry errors and task-budget exhaustion before interpreting failures.
