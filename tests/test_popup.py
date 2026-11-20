"""Launcher command building (no AppKit, nothing launched)."""

from popup import build_command


def test_build_command_picks_agent_task_or_eval_run():
    cmd, env = build_command("Open Calculator", "telemetry-knowledge", "all", desktop=True, privacy=True)
    assert "KNOWLEDGE_GRAPH_ENABLED=1" in cmd and cmd.endswith("agent.py 'Open Calculator'")
    assert env["SCREENSHOT_PRIVACY"] == "ocr" and env["DESKTOP_CONTROL"] == "1"

    cmd, env = build_command("Open Calculator", "base", "all", desktop=False, privacy=False)
    assert "DESKTOP_CONTROL=0" in cmd and "DESKTOP_CONTROL=1" not in cmd and env["SCREENSHOT_PRIVACY"] == "off"

    cmd, _ = build_command("", "telemetry", "all", desktop=True, privacy=False)
    assert cmd.endswith("--agent telemetry-only --skip-description")
    cmd, _ = build_command("  ", "claude-code", "base", desktop=True, privacy=False)
    assert cmd.endswith("--agent claude-code --skip-description --category sanity")

    assert build_command("", "base", "final", desktop=False, privacy=False) == (None, "Eval needs desktop control")


import json
import os
import subprocess
import sys
import time

import pytest

from popup import BackgroundRun, demo_command, response_text


def test_final_answer_is_extracted_after_progress_logs():
    stdout = '[screenshot: local.jpg]\n' + json.dumps({'result': 'Saved the note.', 'input_tokens': 100})
    assert response_text(stdout) == 'Saved the note.'
    assert response_text(json.dumps({'result': 'Permission denied', 'is_error': True})).startswith('Agent reported an error.')


def test_verification_status_is_preserved_in_nested_result():
    data = {'status': 'unverified_or_incomplete', 'claimed_success': False,
            'agent_summary': 'The editor is open.', 'reason': 'Saved contents could not be verified.'}
    answer = response_text(json.dumps({'result': json.dumps(data)}))
    assert 'unverified_or_incomplete' in answer
    assert 'Saved contents could not be verified.' in answer
    assert 'The editor is open.' in answer


def test_failure_empty_plain_text_and_eval_outputs_are_honest():
    assert 'code 1' in response_text('', 'Missing OPENAI_API_KEY', 1)
    assert 'Missing OPENAI_API_KEY' in response_text('', 'Missing OPENAI_API_KEY', 1)
    assert response_text('') == 'The process finished without an answer.'
    assert response_text('plain CLI response') == 'plain CLI response'
    assert 'Review its reported grades' in response_text('Passed: 3/5', evaluation=True)
    assert response_text('\x1b[31mError\x1b[0m') == 'Error'


def await_answer(run):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = run.poll()
        if result is not None:
            return result
        time.sleep(.01)
    run.cancel()
    pytest.fail('synthetic child timed out')


def test_demo_runs_real_subprocess_with_no_api_key(monkeypatch):
    env = {k: v for k, v in os.environ.items() if k not in {'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'}}
    run = BackgroundRun(demo_command('Say hello; $(do not execute this)'), env)
    result = await_answer(run)
    assert run.returncode == 0
    assert 'synthetic agent response' in result
    assert 'No API key was used' in result
    assert run.stdout.closed and run.stderr.closed


def test_large_output_does_not_deadlock_and_final_answer_survives():
    script = "import json,sys; print('x'*200000); sys.stderr.write('y'*200000); print(json.dumps({'result':'Final answer'}))"
    run = BackgroundRun([sys.executable, '-c', script], dict(os.environ))
    assert await_answer(run) == 'Final answer'
    assert run.stdout.closed and run.stderr.closed


def test_failed_child_reports_error():
    run = BackgroundRun([sys.executable, '-c', "import sys; sys.stderr.write('Synthetic failure'); sys.exit(2)"], dict(os.environ))
    result = await_answer(run)
    assert 'code 2' in result and 'Synthetic failure' in result


def test_launch_failure_propagates():
    with pytest.raises(OSError):
        BackgroundRun(['/no/such/telemetry-command'], dict(os.environ))


def test_close_cancels_active_child_and_closes_streams():
    run = BackgroundRun([sys.executable, '-c', 'import time; time.sleep(60)'], dict(os.environ))
    run.cancel()
    assert run.proc.poll() is not None
    assert run.stdout.closed and run.stderr.closed
