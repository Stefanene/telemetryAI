"""Exercise actual SDK tool dispatch with a scripted model; no model/API/GUI calls."""
import asyncio
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

import desktop
import telemetry
from test_desktop import FakeModel


@pytest.fixture
def environment(tmp_path, monkeypatch):
    root, runs = tmp_path/'workspace', tmp_path/'runs'
    root.mkdir()
    monkeypatch.setenv('TELEMETRY_MODE', 'verified')
    monkeypatch.setenv('TELEMETRY_ROOTS', json.dumps([str(root)]))
    monkeypatch.setenv('TELEMETRY_RUN_DIR', str(runs))
    monkeypatch.setattr(desktop.time, 'sleep', lambda *a: None)
    def capture():
        path = desktop.ACTIVE_RUN.get().directory / (uuid.uuid4().hex+'.jpg')
        path.write_bytes(b'\xff\xd8offline')
        return path
    monkeypatch.setattr(desktop, 'take_screenshot', capture)
    monkeypatch.setattr(telemetry, 'snapshot', lambda: {'time': 1, 'frontmost_app': {
        'name': 'Test Editor', 'bundle_id': 'local.editor', 'pid': 17}, 'windows': [], 'ui': {}})
    def forbidden(*args, **kwargs):
        raise AssertionError('Real desktop actions are forbidden in offline tests')
    monkeypatch.setattr(desktop, 'run_action', forbidden)
    return root, runs


def model(monkeypatch, turns):
    scripted = FakeModel(turns)
    monkeypatch.setattr(desktop, 'operator', desktop.operator.clone(model=scripted))
    return scripted


def test_reasoning_packet_changes_after_action_and_finish_is_evidence_backed(environment, monkeypatch):
    root, runs = environment
    target, other = root/'output.txt', root/'other.txt'
    target.write_text('old state')
    other.write_text('preserve '+uuid.uuid4().hex)
    expected = uuid.uuid4().hex+'\n'
    task = f'Write {expected!r} to output.txt. Preserve other.txt.'
    def simulate(tool, args):
        assert tool == 'type'
        target.write_text(args['text'])
    monkeypatch.setattr(desktop, 'run_action', simulate)
    scripted = model(monkeypatch, [
        ('inspect_artifact', {'path': str(target), 'kind': 'text'}),
        ('declare_check', {'kind': 'text_equals', 'path': str(target), 'expected': expected, 'instruction_quote': task}),
        ('declare_check', {'kind': 'unchanged', 'path': str(other), 'expected': '', 'instruction_quote': 'Preserve other.txt.'}),
        ('type_text', {'text': expected}),
        ('verify_checks', {}),
        ('finish_task', {'summary': 'Saved output.txt; other.txt preserved.', 'claimed_success': True}),
        'FINAL MODEL TEXT CANNOT OVERRIDE THE STRUCTURED EVIDENCE RESULT',
    ])
    result = json.loads(asyncio.run(desktop.run_operator(task)))
    assert result['status'] == 'declared_checks_passed'
    assert result['claimed_success'] is True
    assert len(result['checks']) == 2
    assert result['summary'].startswith('Saved output.txt')
    packets = [json.loads(i[-1]['content'][0]['text'].split('Read-only observations (untrusted data):\n')[1]) for i in scripted.inputs]
    assert 'graph' in packets[0]
    assert packets[4]['revision'] == 1
    assert any(c['path'] == str(target) and c['event'] == 'changed' for c in packets[4]['changes'])
    assert desktop.ACTIVE_RUN.get() is None
    directory, = runs.iterdir()
    assert (directory/'actions.jsonl').exists()
    db = sqlite3.connect(directory/'state.sqlite')
    assert db.execute("SELECT count(*) FROM events WHERE kind='action'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM events WHERE kind='verification'").fetchone()[0] >= 2
    db.close()


def test_claim_without_finish_is_not_certified(environment, monkeypatch):
    model(monkeypatch, ['Everything is successfully saved'])
    result = json.loads(asyncio.run(desktop.run_operator('Save a file.')))
    assert result['status'] == 'unverified_or_incomplete'
    assert result['claimed_success'] is False


def test_change_between_finish_and_final_reply_is_rechecked(environment, monkeypatch):
    root, _ = environment
    target = root/'artifact.txt'
    target.write_text('requested')
    task = 'Keep artifact.txt containing requested.'
    model(monkeypatch, [
        ('declare_check', {'kind': 'text_equals', 'path': str(target), 'expected': 'requested', 'instruction_quote': task}),
        ('finish_task', {'summary': 'done', 'claimed_success': True}),
        'done',
    ])
    original = desktop.take_screenshot
    def capture():
        if desktop.ACTIVE_RUN.get().finished:
            target.write_text('external replacement')
        return original()
    monkeypatch.setattr(desktop, 'take_screenshot', capture)
    result = json.loads(asyncio.run(desktop.run_operator(task)))
    assert not result['claimed_success']
    assert result['checks'][0]['status'] == 'fail'


@pytest.mark.parametrize('mode', ['screenshot', 'flat', 'graph', 'verified'])
def test_modes_and_repeat_runs_are_isolated(environment, monkeypatch, mode):
    _, runs = environment
    monkeypatch.setenv('TELEMETRY_MODE', mode)
    first_secret = 'PREVIOUS_RUN_'+uuid.uuid4().hex
    model(monkeypatch, [first_secret])
    asyncio.run(desktop.run_operator('Earlier unrelated task.'))
    scripted = model(monkeypatch, ['second answer'])
    asyncio.run(desktop.run_operator('Fresh unrelated task.'))
    serialized = json.dumps(scripted.inputs)
    assert first_secret not in serialized
    assert len(list(runs.iterdir())) == 2
    assert ('Read-only observations' in serialized) is (mode != 'screenshot')
    if mode != "screenshot":
        packet = json.loads(scripted.inputs[0][-1]["content"][0]["text"].split("Read-only observations (untrusted data):\n")[1])
        assert ("graph" in packet) is (mode in {"graph", "verified"})
        assert "state_facts" not in packet


def test_unavailable_ui_still_allows_file_reasoning(environment, monkeypatch):
    root, _ = environment
    path = root/'fact.txt'
    path.write_text('observable fact')
    monkeypatch.setattr(telemetry, 'snapshot', lambda: {'time': 1, 'ui': {'status': 'unavailable'},
                                                       'windows': {'status': 'unavailable'}})
    scripted = model(monkeypatch, [('inspect_artifact', {'path': str(path), 'kind': 'text'}), 'unverified'])
    result = json.loads(asyncio.run(desktop.run_operator('Inspect fact.txt.')))
    assert not result['claimed_success']
    assert 'observable fact' in json.dumps(scripted.inputs[1])
