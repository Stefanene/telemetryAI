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
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from openai import OpenAI

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))  # the repo root, for desktop.py
from desktop import image_url, take_screenshot  # noqa: E402

RUNS = HERE / "runs"
SANDBOX = Path.home() / "aos-eval"
QUESTION = "These screenshots were taken every 2 seconds while someone used this Mac. Describe step by step what they did."


def record(frames: Path, stop: threading.Event, every: float = 2.0) -> None:
    n = 0
    while not stop.is_set():
        try:
            take_screenshot().rename(frames / f"{n:03d}.jpg")
            n += 1
        except subprocess.CalledProcessError:
            pass
        stop.wait(every)


def run_task(agent: str, command: str, task: dict, run_dir: Path, timeout: int) -> dict:
    subprocess.run(["rm", "-rf", str(SANDBOX)], check=True)
    SANDBOX.mkdir()
    subprocess.run(["bash", "-c", task["setup"]], check=True)
    frames = run_dir / "frames"
    frames.mkdir(parents=True)
    stop = threading.Event()
    recorder = threading.Thread(target=record, args=(frames, stop))
    recorder.start()
    started = time.time()
    try:
        proc = subprocess.run(["bash", "-c", command.replace("{instruction}", shlex.quote(task["instruction"]))],
                              capture_output=True, text=True, timeout=timeout, cwd=HERE.parent.parent)
        output, code = proc.stdout + proc.stderr[-3000:], proc.returncode
    except subprocess.TimeoutExpired as exc:
        output, code = f"{exc.stdout or ''}\n(timeout after {timeout}s)", None
    seconds = round(time.time() - started, 1)
    time.sleep(1)  # one more frame of the end state
    stop.set()
    recorder.join()
    (run_dir / "agent_output.txt").write_text(output)
    check = subprocess.run(["bash", "-c", task["check"]], env={**os.environ, "AGENT_OUTPUT": output})
    return {"agent": agent, "task": task["id"], "rep": int(run_dir.name.rsplit("-", 1)[1]),
            "pass": check.returncode == 0, "exit_code": code, "seconds": seconds, "cost_usd": cost(output)}


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
    rows = [json.loads(p.read_text()) for p in sorted(RUNS.glob("*/*/run.json"))]
    if not rows:
        print("no runs yet")
        return
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    fmt = lambda v, f: "-" if v is None else format(v, f)
    print(f"{'agent':18s} {'task':15s} {'runs':>4s} {'pass':>5s} {'secs':>6s} {'cost$':>7s} {'describe':>8s}")
    groups = {}
    for r in rows:
        groups.setdefault((r["agent"], r["task"]), []).append(r)
        groups.setdefault((r["agent"], "ALL"), []).append(r)
    for (agent, task), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] == "ALL", kv[0][1])):
        costs = [r["cost_usd"] for r in rs if r["cost_usd"] is not None]
        scores = [r["describe_score"] for r in rs if r.get("describe_score") is not None]
        print(f"{agent:18s} {task:15s} {len(rs):4d} {mean([r['pass'] for r in rs]):5.0%} "
              f"{mean([r['seconds'] for r in rs]):6.1f} {fmt(mean(costs), '7.4f'):>7s} {fmt(mean(scores), '8.2f'):>8s}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--agent", default="telemetry", help="a name from agents.json")
    p.add_argument("--only", nargs="*", help="task ids to run (default: all)")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--timeout", type=int, default=600, help="seconds per run")
    p.add_argument("--describe-only", action="store_true", help="re-grade descriptions of recorded runs")
    p.add_argument("--report", action="store_true")
    p.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", "gpt-6-luna"),
                   help="OpenAI vision model that describes the frames (default JUDGE_MODEL or gpt-6-luna)")
    args = p.parse_args()
    tasks = {t["id"]: t for t in json.loads((HERE / "tasks.json").read_text())}
    if args.report:
        return report()
    judge = OpenAI()  # OPENAI_API_KEY from .env (loaded by desktop.py)

    if args.describe_only:
        for path in sorted(RUNS.glob(f"{args.agent}/*/run.json")):
            row = json.loads(path.read_text())
            if args.only and row["task"] not in args.only:
                continue
            row["describe_score"] = grade_description(judge, args.judge_model, tasks[row["task"]], path.parent)
            path.write_text(json.dumps(row, indent=2) + "\n")
            print(f"{row['task']}-{row['rep']}: describe {row['describe_score']}")
        return report()

    if os.environ.get("DESKTOP_CONTROL") != "1":
        raise SystemExit("This drives the real desktop (and deletes ~/aos-eval). Set DESKTOP_CONTROL=1 to go ahead.")
    command = json.loads((HERE / "agents.json").read_text())[args.agent]
    for task_id in args.only or tasks:
        for rep in range(1, args.reps + 1):
            run_dir = RUNS / args.agent / f"{task_id}-{rep}"
            if run_dir.exists():
                subprocess.run(["rm", "-rf", str(run_dir)], check=True)
            print(f"[{args.agent}] {task_id} #{rep} ...", flush=True)
            row = run_task(args.agent, command, tasks[task_id], run_dir, args.timeout)
            row["describe_score"] = grade_description(judge, args.judge_model, tasks[task_id], run_dir)
            (run_dir / "run.json").write_text(json.dumps(row, indent=2) + "\n")
            print(f"  pass={row['pass']} {row['seconds']}s cost={row['cost_usd']} describe={row['describe_score']}")
    report()


if __name__ == "__main__":
    main()
