"""Knowledge graph of what the agent did and what happened, for recall and decision/task evaluation.

Placeholders: every function is a TODO. Hook points are marked `TODO(knowledge)` in desktop.py,
agent.py and evals/desktop/run_desktop.py.

Model (planned):
  nodes  Task, Run, App, File, UIElement, Action, Outcome
  edges  Run -performed-> Action, Action -touched-> App/File/UIElement, Action -followed_by-> Action,
         Run -produced-> File, Run -succeeded|failed-> Outcome (from eval graders, not agent claims)

Backend: TODO choose one. Candidate: graphify (confirm its API and that it fits incremental
writes from a running agent). A JSON-lines node/edge log under GRAPH_DIR is the stdlib fallback.
Never store secrets or raw screenshots in the graph; reference screenshot paths instead.
"""

from __future__ import annotations

from pathlib import Path

GRAPH_DIR = Path(__file__).parent / "knowledge"  # gitignored


def record_action(tool: str, args: dict, result: str, telemetry: dict | None = None) -> None:
    """Add one operator action (and the app/UI element it touched, from telemetry) to the graph.

    TODO: Action node linked to the current Run, the previous Action, and App/UIElement nodes.
    """
    raise NotImplementedError


def record_run(task: str, outcome: str, actions_log: Path, telemetry: dict | None = None) -> None:
    """Add a finished operator run: the task, its final output and its actions (from actions.jsonl).

    TODO: Task + Run nodes; link the Run's Actions; outcome here is the agent's claim, not a grade.
    """
    raise NotImplementedError


def record_eval(row: dict, run_dir: Path) -> None:
    """Add an eval result (run.json row, claim_review.json, frame paths) as graded facts about a Run.

    TODO: Outcome node from row["pass"] / check_detail; flag false completions; link frames by path.
    """
    raise NotImplementedError


def related_context(task: str, limit: int = 5) -> str:
    """Short hints from similar past runs (what worked, what failed) to prepend to an operator task.

    TODO: match Task nodes by text/app, rank by graded success, format as a few bullet lines.
    """
    raise NotImplementedError


def query(question: str) -> str:
    """Answer a question about past tasks, runs and outcomes from the graph.

    TODO: structured lookups first; expose as a `recall` @function_tool for the chat agent (agent.py).
    """
    raise NotImplementedError
