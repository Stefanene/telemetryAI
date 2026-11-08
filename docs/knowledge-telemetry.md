# Live evidence for desktop reasoning

The operator receives a fresh screenshot plus bounded read-only observations before each decision.
It can inspect artifacts to resolve ambiguous document identity and verify saved outputs. A run-local
SQLite graph relates paths, file versions, applications, windows, observations, actions and declared
goal conditions. It records provenance and temporal order; it does not infer causation from order.

## Implemented data flow

1. Create a unique run directory, initial workspace manifest, and empty graph. No previous graph is opened.
2. Capture the main display. Collect the frontmost app, its windows and bounded accessibility tree;
   scan the configured workspace for metadata/content hashes and changes.
3. Append a decision packet to the screenshot input. The packet is ephemeral, not appended to the
   conversation history. Relevant state and inspection results are retained explicitly in run state.
4. Execute one mouse/keyboard action. Record its transport result, invalidate old inspection/check
   status and collect observations before the next decision. `ok` only means the action executed.
5. The operator can inspect a specific artifact: UTF-8 text, file metadata, PDF page count/text, or
   rich-text semantic runs via native `textutil`. These tools cannot write files or run arbitrary commands.
6. In verified mode, the model declares conditions citing exact passages from the user's request,
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
- `flat` and `graph` expose the same current observations, prior inspection summaries and retained state
  facts. Flat mode presents relationships as standalone subject/predicate/object records; graph mode
  uses deduplicated nodes/edges. Both include the same inferred move evidence. Representation, length
  and truncation can still differ: log them and include token cost in results. This is a representation
  ablation, not evidence of a universally better graph algorithm.
- `verified` adds condition/verification tools and instructions to graph mode. Any improvement there
  belongs to that combined intervention, not solely the graph. The shared skills and action tools
  remain identical across modes.
- General user documents can themselves contain instructions; observations are explicitly labeled
  untrusted data. Redaction minimizes obvious credentials but does not guarantee secret-free arbitrary
  text or screenshots. Only configure roots appropriate to send to the model API.

## Configuration and artifacts

```bash
# Create a dedicated workspace yourself. Never point roots at the repo or your entire home.
export TELEMETRY_ROOTS='["/absolute/path/to/task-workspace"]'
export TELEMETRY_MODE=verified  # screenshot | flat | graph | verified
export DESKTOP_MAX_TURNS=40     # same budget for all comparison arms
DESKTOP_CONTROL=1 uv run agent.py "Your desktop task"
```

Without roots, UI observations work but file inspection cannot access any files. Root configuration
must precede process launch. `TELEMETRY_RUN_DIR` optionally chooses the artifact parent; otherwise
runs live in `screenshots/<random-run-id>/` with `state.sqlite`, screenshots, and `actions.jsonl`.
The DB contains configuration, input packets, observations, inspections, actions and final claims.
No screenshot bytes are stored in graph rows. Inspect these artifacts locally; do not commit them.

Collectors use a 5-second command timeout, a 100-node accessibility budget and depth cap, a bounded
workspace scan (300 files/directories; files up to 1 MB), bounded inspection text, and a 32 KB decision
packet cap. Incomplete scans and truncated packets are labeled. Missing data is unknown, not proof of
absence. Large or non-UTF-8 text needs another inspection strategy. `system_snapshot` and `recent_logs`
are optional local diagnostics, not routine model inputs or agent tools.

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

```bash
DESKTOP_CONTROL=1 DESKTOP_MAX_TURNS=40 uv run python evals/desktop/run_desktop.py --agent telemetry-screenshot --category challenge --reps 3 --skip-description
DESKTOP_CONTROL=1 DESKTOP_MAX_TURNS=40 uv run python evals/desktop/run_desktop.py --agent telemetry-flat --category challenge --reps 3 --skip-description
DESKTOP_CONTROL=1 DESKTOP_MAX_TURNS=40 uv run python evals/desktop/run_desktop.py --agent telemetry-graph --category challenge --reps 3 --skip-description
DESKTOP_CONTROL=1 DESKTOP_MAX_TURNS=40 uv run python evals/desktop/run_desktop.py --agent telemetry --category challenge --reps 3 --skip-description
```

`--skip-description` skips only the optional paid screenshot-description judge. Artifact graders are
unchanged. `telemetry-screenshot` is labeled `gui`; enhanced configurations are `gui+telemetry`.
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
