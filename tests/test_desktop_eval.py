import json
import subprocess
from types import SimpleNamespace

import pytest

from evals.desktop import run_desktop as runner
from evals.desktop import reliability


@pytest.mark.parametrize("agent_result", ["success", "false_claim", "timeout"])
def test_runner_grades_outcomes_not_agent_claims(tmp_path, monkeypatch, agent_result):
    root = tmp_path / "sandbox"
    run_dir = tmp_path / "runs/agent/exact_save-1"
    monkeypatch.setattr(runner, "SANDBOX", root)
    monkeypatch.setattr(runner, "record", lambda frames, stop: None)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(runner, "setup_task", lambda task, path: reliability.setup_task(task, path, open_apps=False))
    original = subprocess.run
    def execute(command, **kwargs):
        if command[:2] == ["bash", "-c"]:
            if agent_result == "success":
                (root / "final.txt").write_text(reliability.EXACT)
            if agent_result == "timeout":
                raise subprocess.TimeoutExpired(command, 1, output=b"partial output")
            return SimpleNamespace(stdout='{"result":"Successfully saved everything"}', stderr="", returncode=0)
        assert command == ["rm", "-rf", str(root)]
        return original(command, **kwargs)
    monkeypatch.setattr(runner.subprocess, "run", execute)
    task = {"id": "exact_save", "fixture": "exact_save", "instruction": "save", "category": "sanity"}
    row = runner.run_task("telemetry", "agent-command {instruction}", task, run_dir, 1)
    assert row["pass"] is (agent_result == "success")
    assert row["claimed_success"] is None  # narrative is not an annotation
    assert row["category"] == "sanity" and row["track"] == "gui+telemetry"
    assert (run_dir / "agent_output.txt").exists()
    if agent_result == "timeout":
        assert row["exit_code"] is None
        assert "partial output" in (run_dir / "agent_output.txt").read_text()


def test_permission_cleanup_runs_when_agent_launch_fails(tmp_path, monkeypatch):
    root = tmp_path / "sandbox"
    monkeypatch.setattr(runner, "SANDBOX", root)
    monkeypatch.setattr(runner, "record", lambda frames, stop: None)
    monkeypatch.setattr(runner, "setup_task", lambda task, path: reliability.setup_task(task, path, open_apps=False))
    original = subprocess.run
    def execute(command, **kwargs):
        if command[0] == "bash":
            raise OSError("launch failed")
        assert command == ["rm", "-rf", str(root)]
        return original(command, **kwargs)
    monkeypatch.setattr(runner.subprocess, "run", execute)
    with pytest.raises(OSError, match="launch failed"):
        runner.run_task("telemetry", "agent-command", {"id": "blocked_destination", "fixture": "blocked_destination",
                        "instruction": "save"}, tmp_path / "runs/blocked_destination-1", 1)
    assert (root / "protected").stat().st_mode & 0o777 == 0o755
    assert (root / "protected/keep.txt").stat().st_mode & 0o777 == 0o644


def test_report_separates_tracks_categories_and_claim_denominators(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    for agent, track, category, claimed in [("telemetry", "gui", "sanity", True),
                                            ("telemetry", "gui", "challenge", False),
                                            ("codex", "outcome", "challenge", None)]:
        folder = tmp_path / agent / f"{category}-1"
        folder.mkdir(parents=True)
        row = {"agent": agent, "track": track, "category": category, "task": category, "pass": False,
               "seconds": 1, "cost_usd": None, "describe_score": 1.0}
        (folder / "run.json").write_text(json.dumps(row))
        if claimed is not None:
            (folder / "claim_review.json").write_text(json.dumps({"claimed_success": claimed}))
    runner.report()
    text = capsys.readouterr().out
    assert "coverage" in text and "F/C" in text
    totals = [line.split() for line in text.splitlines() if "ALL" in line]
    assert len(totals) == 3
    assert {tuple(line[:3]) for line in totals} == {("telemetry", "gui", "sanity"),
            ("telemetry", "gui", "challenge"), ("codex", "outcome", "challenge")}
    assert next(line for line in totals if line[2] == "sanity")[-1] == "100%"
    assert all(line[-1] == "-" for line in totals if line[2] == "challenge")


def test_skip_description_never_initializes_paid_judge(tmp_path, monkeypatch):
    monkeypatch.setenv('DESKTOP_CONTROL', '1')
    monkeypatch.setattr(runner, 'RUNS', tmp_path)
    monkeypatch.setattr(runner.sys, 'argv', ['run_desktop.py', '--only', 'new_folder', '--skip-description'])
    def denied(*args, **kwargs):
        raise AssertionError('Paid description judge must not be initialized or called')
    monkeypatch.setattr(runner, 'OpenAI', denied)
    monkeypatch.setattr(runner, 'grade_description', denied)
    def run(*args):
        run_dir = args[3]
        run_dir.mkdir(parents=True)
        return {'pass': True, 'seconds': 0, 'cost_usd': None}
    monkeypatch.setattr(runner, 'run_task', run)
    monkeypatch.setattr(runner, 'report', lambda: None)
    runner.main()
    assert json.loads((tmp_path/'telemetry/new_folder-1/run.json').read_text())['describe_score'] is None
