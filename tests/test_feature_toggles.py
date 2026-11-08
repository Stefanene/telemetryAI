"""Independent capability tests, including negative checks for hidden collection/graph work."""
import asyncio
import json
import sqlite3

import pytest

import desktop
import evidence
import telemetry
from evidence import RunState
from features import Features
from evals.desktop import run_desktop as harness
from test_observation_loop import environment, model


@pytest.mark.parametrize('t,k', [(False, False), (True, False), (False, True), (True, True)])
def test_all_four_combinations_control_inputs_tools_and_storage(environment, monkeypatch, t, k):
    root, runs = environment
    monkeypatch.setenv('TELEMETRY_ENABLED', str(int(t)))
    monkeypatch.setenv('KNOWLEDGE_GRAPH_ENABLED', str(int(k)))
    monkeypatch.setenv('VERIFICATION_ENABLED', '0')
    marker = 'PRIVATE_TELEMETRY_FACT'
    (root/'data.txt').write_text(marker)
    def forbidden(*a, **kw):
        raise AssertionError('Disabled capability was invoked')
    if not t:
        monkeypatch.setattr(telemetry, 'snapshot', forbidden)
        monkeypatch.setattr(telemetry.Workspace, 'scan', forbidden)
        monkeypatch.setattr(telemetry.Workspace, 'inspect', forbidden)
    if not k:
        monkeypatch.setattr(evidence, 'Graph', forbidden)
    monkeypatch.setattr(desktop, 'run_action', lambda *a: None)
    scripted = model(monkeypatch, [('press_key', {'combo': 'escape'}), 'Finished'])
    assert asyncio.run(desktop.run_operator('Do a generic desktop task.')) == 'Finished'
    assert ('Read-only observations' in json.dumps(scripted.inputs)) is (t or k)
    if t or k:
        packet = json.loads(scripted.inputs[1][-1]['content'][0]['text'].split('Read-only observations (untrusted data):\n')[1])
        assert ('graph' in packet) is k
        assert ('ui' in packet) is t
        assert ('workspace' in packet) is t
        if k:
            assert any(r['relation'] == 'performed' for r in packet['graph']['relations'])
        if not t:
            assert marker not in json.dumps(packet)
            assert 'data.txt' not in json.dumps(packet)
    directory, = runs.iterdir()
    assert (directory/'state.sqlite').exists() is k
    if k:
        with sqlite3.connect(directory/'state.sqlite') as db:
            events = [(kind, json.loads(data)) for kind, data in db.execute('SELECT kind,data FROM events')]
    else:
        events = [(e['kind'], e['data']) for e in map(json.loads, (directory/'events.jsonl').read_text().splitlines())]
    config = next(data for kind, data in events if kind == 'configuration')
    assert config['telemetry_enabled'] is t and config['knowledge_graph_enabled'] is k
    tools = next(data['tools'] for kind, data in events if kind == 'operator_configuration')
    assert ('inspect_artifact' in tools) is t
    assert not {'finish_task', 'verify_checks', 'declare_check'} & set(tools)


def test_verification_works_with_graph_disabled(tmp_path):
    root = tmp_path/'workspace'
    root.mkdir()
    target = root/'document.txt'
    target.write_text('actual user-requested contents\n')
    task = 'Keep the document unchanged.'
    state = RunState(task, tmp_path/'run', [root], features=Features(True, False, True))
    try:
        state.declare('unchanged', str(target), '', task)
        assert state.finish('Preserved document.', True)['claimed_success']
        target.write_text('unexpected edit')
        assert not state.finish('Preserved document.', True)['claimed_success']
        assert state.graph is None
    finally:
        state.close('test')


def test_disabled_telemetry_is_enforced_beyond_tool_registration(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry.Workspace, 'inspect', lambda *a: pytest.fail('Must not inspect'))
    state = RunState('Task.', tmp_path/'run', features=Features(False, True, False))
    try:
        assert state.inspect('/not/allowed')['status'] == 'unavailable'
        with pytest.raises(ValueError, match='requires enabled'):
            state.verify()
    finally:
        state.close('test')


@pytest.mark.parametrize('t,k', [(0,0), (1,0), (0,1), (1,1)])
def test_environment_flags_override_legacy_presets(t, k):
    config = Features.from_env({'TELEMETRY_MODE': 'verified', 'TELEMETRY_ENABLED': str(t),
                                'KNOWLEDGE_GRAPH_ENABLED': str(k), 'VERIFICATION_ENABLED': '0'})
    assert config == Features(bool(t), bool(k), False)
    assert Features.from_env(config.environment()) == config


def test_verification_never_silently_reenables_telemetry():
    config = Features.from_env({'TELEMETRY_ENABLED': '0'})
    assert config.knowledge_graph_enabled and not config.verification_enabled
    with pytest.raises(ValueError, match='requires'):
        Features.from_env({'TELEMETRY_ENABLED': '0', 'VERIFICATION_ENABLED': '1'})
    with pytest.raises(ValueError, match='must be'):
        Features.from_env({'KNOWLEDGE_GRAPH_ENABLED': 'maybe'})


def test_harness_overrides_inline_presets_without_losing_task_placeholder(monkeypatch):
    monkeypatch.setenv('TELEMETRY_MODE', 'verified')
    command, features = harness.operator_configuration(
        'DESKTOP_CONTROL=1 TELEMETRY_ENABLED=1 KNOWLEDGE_GRAPH_ENABLED=0 VERIFICATION_ENABLED=0 uv run agent.py {instruction}',
        {'TELEMETRY_ENABLED': False, 'KNOWLEDGE_GRAPH_ENABLED': True})
    assert features == Features(False, True, False)
    assert command == 'DESKTOP_CONTROL=1 uv run agent.py {instruction}'


@pytest.mark.parametrize('name,t,k', [('base', False, False), ('telemetry-only', True, False),
                                     ('knowledge-only', False, True), ('telemetry-knowledge', True, True)])
def test_harness_presets_define_full_factorial_without_verification(name, t, k):
    templates = json.loads((harness.HERE/'agents.json').read_text())
    _, config = harness.operator_configuration(templates[name])
    assert config == Features(t, k, False)


@pytest.mark.parametrize('t,k', [(False,False), (True,False), (False,True), (True,True)])
def test_cli_switches_reach_subprocess_configuration_and_separate_results(tmp_path, monkeypatch, t, k):
    monkeypatch.setenv('DESKTOP_CONTROL', '1')
    monkeypatch.setattr(harness, 'RUNS', tmp_path)
    monkeypatch.setattr(harness.sys, 'argv', ['run_desktop.py', '--agent', 'base', '--only', 'new_folder',
                                           '--telemetry' if t else '--no-telemetry',
                                           '--knowledge-graph' if k else '--no-knowledge-graph', '--skip-description'])
    observed = []
    def run(agent, command, task, run_dir, *args):
        _, features = harness.operator_configuration(command)
        observed.append(features)
        run_dir.mkdir(parents=True)
        return {'pass': True, 'seconds': 0, 'cost_usd': None}
    monkeypatch.setattr(harness, 'run_task', run)
    monkeypatch.setattr(harness, 'report', lambda: None)
    monkeypatch.setattr(harness, 'OpenAI', lambda: pytest.fail('No paid judge'))
    harness.main()
    assert observed == [Features(t, k, False)]
    assert (tmp_path/f'base-t{int(t)}-kg{int(k)}-v0/new_folder-1/run.json').exists()
