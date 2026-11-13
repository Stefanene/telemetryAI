"""Run the desktop tasks against any agent and grade them by the state they leave behind.

  DESKTOP_CONTROL=1 uv run python evals/desktop/run_desktop.py [--agent telemetry] [--only new_folder] [--reps 3]
  uv run python evals/desktop/run_desktop.py --describe-only      # re-grade recorded frames, no desktop
  uv run python evals/desktop/run_desktop.py --report             # just print the table

Each run gets runs/<agent>/<task>-<rep>/ with the frames this script recorded every 2 s
(so every agent is described the same way), agent_output.txt, description.md and run.json.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # the repo root, for desktop.py
import knowledge
import telemetry
from features import Features
from desktop import image_url, take_screenshot  # noqa: E402

if __package__:
    from .reliability import cleanup_task, completion_review, grade_task, setup_task
else:
    from reliability import cleanup_task, completion_review, grade_task, setup_task

HERE = Path(__file__).parent
RUNS = HERE / "runs"
SANDBOX = Path.home() / "telem-eval"
QUESTION = "These screenshots were taken every 2 seconds while someone used this Mac. Describe step by step what they did."
OPERATOR_AGENTS = {"base", "telemetry-only", "knowledge-only", "telemetry-knowledge",
                   "telemetry", "telemetry-screenshot", "telemetry-flat", "telemetry-graph"}
AGENT_TRACKS = {"base": "gui", "telemetry-only": "gui+telemetry", "knowledge-only": "gui",
                "telemetry-knowledge": "gui+telemetry", "telemetry": "gui+telemetry", "telemetry-screenshot": "gui",
                "telemetry-flat": "gui+telemetry", "telemetry-graph": "gui+telemetry", "claude-code-gui": "gui", "claude-code": "outcome", "codex": "outcome"}


def operator_configuration(command: str, overrides: dict | None = None):
    """Resolve leading environment assignments, then CLI overrides; strip capability presets
    so inline assignments cannot silently override the effective subprocess environment."""
    environment = dict(os.environ)
    prefixes = []
    remaining = command
    while match := re.match(r'([A-Z_][A-Z_0-9]*)=([^\s]+)\s+', remaining):
        key, value = match.groups()
        environment[key] = value
        prefixes.append((key, value))
        remaining = remaining[match.end():]
    environment.update({k: str(int(v)) for k, v in (overrides or {}).items() if v is not None})
    features = Features.from_env(environment)
    keys = {'TELEMETRY_MODE', 'TELEMETRY_ENABLED', 'KNOWLEDGE_GRAPH_ENABLED', 'VERIFICATION_ENABLED'}
    clean = ''.join(f'{k}={v} ' for k, v in prefixes if k not in keys) + remaining
    return clean, features


def record(frames: Path, stop: threading.Event, every: float = 2.0) -> None:
    n = 0
    while not stop.is_set():
        try:
            take_screenshot().rename(frames / f"{n:03d}.jpg")
            n += 1
        except subprocess.CalledProcessError:
            pass
        stop.wait(every)


def run_task(agent: str, command: str, task: dict, run_dir: Path, timeout: int, track=None) -> dict:
    features = None
    if agent in OPERATOR_AGENTS:
        command, features = operator_configuration(command)
    subprocess.run(["rm", "-rf", str(SANDBOX)], check=True)
    SANDBOX.mkdir()
    fixture = task.get("fixture")
    # Reject missing PDF tooling before opening apps or invoking a paid agent.
    if fixture == "pdf_export":
        from pypdf import PdfReader  # noqa: F401
    if fixture and task.get("category") == "final":
        from PIL import Image  # noqa: F401
    frames = run_dir / "frames"
    frames.mkdir(parents=True)
    stop = threading.Event()
    recorder = threading.Thread(target=record, args=(frames, stop))
    try:
        if fixture:
            setup_task(fixture, SANDBOX)
        else:
            subprocess.run(["bash", "-c", task["setup"]], check=True)
        recorder.start()
        started = time.time()
        workspace = telemetry.Workspace([SANDBOX])
        before = workspace.scan()
        environment = {**os.environ, "TELEMETRY_ROOTS": json.dumps([str(SANDBOX.resolve())]),
                       "TELEMETRY_RUN_DIR": str((run_dir / "operator").resolve())}
        if features is not None:
            environment.update(features.environment())
        try:
            proc = subprocess.run(["bash", "-c", command.replace("{instruction}", shlex.quote(task["instruction"]))],
                                  capture_output=True, text=True, timeout=timeout, cwd=HERE.parent.parent, env=environment)
            output, code = proc.stdout + proc.stderr[-3000:], proc.returncode
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode(errors="replace")
            output, code = f"{partial}\n(timeout after {timeout}s)", None
        seconds = round(time.time() - started, 1)
        changes = telemetry.file_events(before, workspace.scan())
        time.sleep(1)  # one more frame of the end state
        stop.set()
        recorder.join()
        (run_dir / "agent_output.txt").write_text(output)
        if fixture:
            passed, detail = grade_task(fixture, SANDBOX, output)
        else:
            check = subprocess.run(["bash", "-c", task["check"]], env={**os.environ, "AGENT_OUTPUT": output})
            passed, detail = check.returncode == 0, "Legacy task check (see README for limitations)."
        return {"agent": agent, "track": track or (("gui+telemetry" if features.telemetry_enabled else "gui")
                                      if features else AGENT_TRACKS.get(agent, "unclassified")),
                "category": task.get("category", "sanity"), "task": task["id"],
                "rep": int(run_dir.name.rsplit("-", 1)[1]), "pass": passed, "check_detail": detail,
                "exit_code": code, "seconds": seconds, "cost_usd": cost(output),
                "file_events": changes, "model": os.environ.get("MODEL", "gpt-6-luna"),
                "vision_model": os.environ.get("VISION_MODEL", os.environ.get("MODEL", "gpt-6-luna")),
                "max_turns": int(os.environ.get("DESKTOP_MAX_TURNS", "40")),
                "memory": "disabled", "operator_features": features.as_dict() if features else None,
                **completion_review(run_dir, passed)}
    finally:
        stop.set()
        if recorder.ident is not None:
            recorder.join()
        if fixture:
            cleanup_task(fixture, SANDBOX)


def cost(output: str) -> float | None:
    """total_cost_usd from an agent's JSON output (claude -p --output-format json, agent.py)."""
    for line in reversed(output.strip().splitlines()):
        try:
            return json.loads(line).get("total_cost_usd")
        except (json.JSONDecodeError, AttributeError):
            continue
    return None


def describe(judge: OpenAI, model: str, frames: list[Path], question: str) -> str:
    """One vision call over all frames; set JUDGE_MODEL to a different model than the agent's for an independent judge."""
    content = [{"type": "text", "text": question}]
    content += [{"type": "image_url", "image_url": {"url": image_url(p)}} for p in frames]
    reply = judge.chat.completions.create(model=model, messages=[{"role": "user", "content": content}])
    return reply.choices[0].message.content or ""


def grade_description(judge: OpenAI, model: str, task: dict, run_dir: Path, max_frames: int = 8) -> float:
    frames = sorted((run_dir / "frames").glob("*.jpg"))
    picked = [frames[round(i * (len(frames) - 1) / (max_frames - 1))] for i in range(max_frames)] if len(frames) > max_frames else frames
    text = describe(judge, model, picked, QUESTION) if picked else ""
    (run_dir / "description.md").write_text(text + "\n")
    keywords = task["describe_keywords"]
    return round(sum(k.lower() in text.lower() for k in keywords) / len(keywords), 2)


def report() -> None:
    rows = []
    for path in sorted(RUNS.glob("*/*/run.json")):
        row = json.loads(path.read_text())
        row.update(completion_review(path.parent, row["pass"]))
        rows.append(row)
    if not rows:
        print("no runs yet")
        return
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    fmt = lambda v, f: "-" if v is None else format(v, f)
    print(f"{'agent':18s} {'track':12s} {'category':10s} {'task':24s} {'runs':>4s} {'pass':>5s} "
          f"{'secs':>6s} {'cost$':>7s} {'coverage':>8s} {'reviewed':>8s} {'F/C':>6s}")
    groups = {}
    for r in rows:
        key = (r["agent"], r.get("track", "unclassified"), r.get("category", "legacy"))
        groups.setdefault((*key, r["task"]), []).append(r)
        groups.setdefault((*key, "ALL"), []).append(r)
    for (agent, track, category, task), rs in sorted(groups.items()):
        costs = [r["cost_usd"] for r in rs if r["cost_usd"] is not None]
        scores = [r["describe_score"] for r in rs if r.get("describe_score") is not None]
        reviewed = [r for r in rs if r.get("claimed_success") is not None]
        claims = [r for r in reviewed if r["claimed_success"]]
        false_rate = mean([r["false_completion"] for r in claims])
        print(f"{agent:18s} {track:12s} {category:10s} {task:24s} {len(rs):4d} {mean([r['pass'] for r in rs]):5.0%} "
              f"{mean([r['seconds'] for r in rs]):6.1f} {fmt(mean(costs), '7.4f'):>7s} "
              f"{fmt(mean(scores), '8.2f'):>8s} {len(reviewed):8d} {fmt(false_rate, '6.0%'):>6s}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--agent", default="telemetry", help="a name from agents.json")
    p.add_argument("--only", nargs="*", help="task ids to run (default: all)")
    p.add_argument("--category", choices=["sanity", "challenge", "final"], help="run only sanity, challenge or final tasks")
    p.add_argument("--track", choices=["gui", "gui+telemetry", "outcome"], help="override the declared access track for this agent configuration")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--timeout", type=int, default=600, help="seconds per run")
    p.add_argument("--describe-only", action="store_true", help="re-grade descriptions of recorded runs")
    p.add_argument("--report", action="store_true")
    p.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", "gpt-6-luna"),
                   help="OpenAI vision model that describes the frames (default JUDGE_MODEL or gpt-6-luna)")
    p.add_argument("--skip-description", action="store_true", help="Skip the optional paid screenshot-description model")
    p.add_argument("--telemetry", action=argparse.BooleanOptionalAction, default=None,
                   help="Enable/disable operator telemetry independently of the graph")
    p.add_argument("--knowledge-graph", action=argparse.BooleanOptionalAction, default=None,
                   help="Enable/disable the operator knowledge graph independently of telemetry")
    p.add_argument("--verification", action=argparse.BooleanOptionalAction, default=None,
                   help="Optional file verification (requires telemetry); hold fixed in comparisons")
    args = p.parse_args()
    tasks = {t["id"]: t for t in json.loads((HERE / "tasks.json").read_text())}
    selected = args.only or list(tasks)
    unknown = set(selected) - tasks.keys()
    if unknown:
        p.error(f"unknown task IDs: {', '.join(sorted(unknown))}")
    selected = [tid for tid in selected if not args.category or tasks[tid].get("category") == args.category]
    if args.report:
        return report()
    command = json.loads((HERE / "agents.json").read_text())[args.agent]
    overrides = {"TELEMETRY_ENABLED": args.telemetry, "KNOWLEDGE_GRAPH_ENABLED": args.knowledge_graph,
                 "VERIFICATION_ENABLED": args.verification}
    label = args.agent
    if any(v is not None for v in overrides.values()):
        if args.agent not in OPERATOR_AGENTS:
            p.error("Capability switches apply only to this project's operator configurations")
        try:
            command, features = operator_configuration(command, overrides)
        except ValueError as exc:
            p.error(str(exc))
        command = ' '.join(f'{key}={value}' for key, value in features.environment().items()) + ' ' + command
        label += f"-t{int(features.telemetry_enabled)}-kg{int(features.knowledge_graph_enabled)}-v{int(features.verification_enabled)}"
    judge = None if args.skip_description else OpenAI()

    if args.describe_only:
        if args.skip_description:
            p.error("--describe-only and --skip-description cannot be combined")
        for path in sorted(RUNS.glob(f"{label}/*/run.json")):
            row = json.loads(path.read_text())
            if row["task"] not in selected:
                continue
            row["describe_score"] = grade_description(judge, args.judge_model, tasks[row["task"]], path.parent)
            path.write_text(json.dumps(row, indent=2) + "\n")
            print(f"{row['task']}-{row['rep']}: describe {row['describe_score']}")
        return report()

    if os.environ.get("DESKTOP_CONTROL") != "1":
        raise SystemExit("This drives the real desktop (and deletes ~/telem-eval). Set DESKTOP_CONTROL=1 to go ahead.")
    for task_id in selected:
        for rep in range(1, args.reps + 1):
            run_dir = RUNS / label / f"{task_id}-{rep}"
            if run_dir.exists():
                subprocess.run(["rm", "-rf", str(run_dir)], check=True)
            print(f"[{args.agent}] [{tasks[task_id].get('category', 'sanity').upper()}] {task_id} #{rep} ...", flush=True)
            row = run_task(args.agent, command, tasks[task_id], run_dir, args.timeout, args.track)
            row["agent"] = label
            row["describe_score"] = None if args.skip_description else grade_description(judge, args.judge_model, tasks[task_id], run_dir)
            (run_dir / "run.json").write_text(json.dumps(row, indent=2) + "\n")
            knowledge.record_eval(row, run_dir)  # Analysis only, never runtime retrieval
            print(f"  pass={row['pass']} {row['seconds']}s cost={row['cost_usd']} describe={row['describe_score']}")
    report()


if __name__ == "__main__":
    main()
