"""Arbitrary task data: checks do not import the benchmark fixtures or graders."""
import json
import os
import sqlite3
import subprocess
import uuid

import pytest
from pypdf import PdfWriter

import telemetry
from evidence import RunState
from knowledge import Graph, record_eval


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / 'documents'
    root.mkdir()
    return root


@pytest.fixture
def state(tmp_path, workspace, monkeypatch):
    monkeypatch.setattr(telemetry, 'snapshot', lambda: {'time': 1, 'frontmost_app': {
        'name': 'Editor', 'bundle_id': 'test.editor', 'pid': 9},
        'windows': [{'title': 'same.txt', 'bounds': [0, 0, 100, 100]}], 'ui': {}})
    run = RunState('Write the requested text. Preserve the other document.', tmp_path/'run', [workspace])
    yield run
    run.close('test completed')


def test_exact_reads_newlines_missing_file_and_stale_existing_output(state, workspace):
    target = workspace/'memo.txt'
    expected = uuid.uuid4().hex + '\n'
    target.write_text(expected.rstrip())
    state.declare('text_equals', str(target), expected, 'Write the requested text.')
    assert state.verify()['checks'][0]['status'] == 'fail'
    target.write_text(expected)
    assert state.verify()['all_declared_checks_pass']
    # No action hook or mtime comparison is needed to detect a later external edit.
    target.write_text('outdated\n')
    assert not state.finish('done', True)['claimed_success']
    target.unlink()
    assert state.verify()['checks'][0]['status'] == 'fail'


def test_unknown_never_passes_and_conditions_require_instruction_quote(state, workspace, monkeypatch):
    with pytest.raises(ValueError, match='exact passage'):
        state.declare('exists', str(workspace/'x'), '', 'An invented instruction')
    assert not state.finish('done', True)['claimed_success']
    state.declare('exists', str(workspace/'x'), '', 'Write the requested text.')
    monkeypatch.setattr(state.workspace, 'inspect', lambda *a: (_ for _ in ()).throw(PermissionError('blocked')))
    result = state.finish('done', True)
    assert not result['claimed_success']
    assert result['checks'][0]['status'] == 'unknown'


def test_baseline_preservation_includes_permissions(tmp_path, workspace):
    target = workspace/'preserve.txt'
    target.write_text(uuid.uuid4().hex)
    state = RunState('Preserve this document.', tmp_path/'run', [workspace])
    try:
        state.declare('unchanged', str(target), '', state.task)
        assert state.verify()['all_declared_checks_pass']
        target.chmod(0o400)
        assert not state.verify()['all_declared_checks_pass']
        target.chmod(0o600)
        target.write_text('different')
        assert not state.verify()['all_declared_checks_pass']
    finally:
        state.close('test')


def test_absence_and_unknown_baseline_are_distinct(state, workspace):
    path = str(workspace/'new.txt')
    state.declare('absent', path, '', 'Write the requested text.')
    assert state.verify()['all_declared_checks_pass']
    state.declare('unchanged', path, '', 'Preserve the other document.')
    assert state.verify()['checks'][1]['status'] == 'fail'  # currently missing
    (workspace/'new.txt').write_text('created after baseline')
    assert state.verify()['checks'][1]['status'] == 'unknown'


def test_inspection_is_invalidated_after_action(state, workspace):
    target = workspace/'same.txt'
    target.write_text('first')
    prior = state.inspect(str(target))
    state.action('key', {'combo': 'cmd+s'}, 'ok')
    assert state.inspections[prior['id']]['status'] == 'stale'
    assert state.finished is None
    assert state.inspect(str(target))['status'] == 'observed'


def test_duplicate_names_are_distinct_and_window_identity_is_not_invented(state, workspace):
    for folder in ['one', 'two']:
        (workspace/folder).mkdir()
        (workspace/folder/'same.txt').write_text(uuid.uuid4().hex)
    packet = state.observe()
    paths = {n['data']['path'] for n in packet['graph']['nodes'] if n['kind'] == 'Path'}
    assert paths == {str(workspace/'one/same.txt'), str(workspace/'two/same.txt')}
    assert not any(r['relation'] in {'displays', 'backed_by'} for r in packet['graph']['relations'])


def test_move_is_inferred_not_certain_and_old_edges_become_stale(state, workspace):
    source, destination = workspace/'before.txt', workspace/'after.txt'
    source.write_text('arbitrary unchanged content')
    state.observe()
    state.action('key', {'combo': 'cmd+v'}, 'ok')
    source.rename(destination)
    packet = state.observe()
    moves = [r for r in packet['graph']['relations'] if r['relation'] == 'possibly_moved_to']
    assert len(moves) == 1 and moves[0]['status'] == 'inferred'
    assert not any(r['source'] == 'path:'+str(source) and r['relation'] == 'current_version' for r in packet['graph']['relations'])
    assert any(c['event'] == 'deleted' and c['path'] == str(source) for c in packet['changes'])


def test_incomplete_scan_never_invents_deletion():
    before = {'files': {'a': {'sha256': 'x'}}, 'complete': True}
    after = {'files': {}, 'complete': False}
    assert telemetry.file_events(before, after)[0]['event'] == 'unknown'


def test_scope_rejects_repository_escape_hidden_credentials_and_symlinks(workspace, tmp_path):
    ws = telemetry.Workspace([workspace])
    outside = tmp_path/'answer.txt'
    outside.write_text('not accessible')
    (workspace/'link.txt').symlink_to(outside)
    (workspace/'folder').mkdir()
    (workspace/'folder'/'nested').symlink_to(tmp_path, target_is_directory=True)
    for path in [outside, workspace/'../answer.txt', workspace/'link.txt',
                 workspace/'folder/nested/answer.txt', workspace/'.env', workspace/'private.key']:
        with pytest.raises(ValueError):
            ws.inspect(str(path))
    for root in [telemetry.REPO, telemetry.REPO.parent, os.path.expanduser('~'), '/']:
        with pytest.raises(ValueError):
            telemetry.Workspace([root])


def test_large_and_special_files_are_not_read(workspace):
    ws = telemetry.Workspace([workspace])
    large = workspace/'large.txt'
    large.write_bytes(b'x'*(telemetry.MAX_BYTES+1))
    with pytest.raises(ValueError):
        ws.read(large)
    pipe = workspace/'pipe'
    os.mkfifo(pipe)
    with pytest.raises(ValueError):
        ws.read(pipe)
    assert not ws.scan()['complete']


def test_partial_telemetry_redacts_and_marks_unavailable(monkeypatch):
    monkeypatch.setattr(telemetry, 'frontmost_app', lambda: (_ for _ in ()).throw(PermissionError()))
    monkeypatch.setattr(telemetry, 'window_list', lambda: [])
    monkeypatch.setattr(telemetry, 'ui_tree', lambda: {'value': 'safe'})
    packet = telemetry.snapshot()
    assert packet['frontmost_app']['status'] == 'unavailable'
    assert packet['ui']['value'] == 'safe'
    assert 'abcdef' not in json.dumps(telemetry.redact({'title': 'password=abcdef', 'token': 'abcdef'}))


def test_inspect_pdf_is_structure_not_extension(state, workspace):
    path = workspace/'result.pdf'
    path.write_text('This is not a PDF')
    assert state.inspect(str(path), 'pdf')['status'] == 'unavailable'
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with path.open('wb') as stream:
        writer.write(stream)
    assert state.inspect(str(path), 'pdf')['result']['page_count'] == 1
    state.declare('page_count', str(path), '1', 'Write the requested text.')
    assert state.verify()['all_declared_checks_pass']


def test_rich_text_observation_and_preservation(state, workspace):
    path = workspace/'styled.rtf'
    path.write_bytes(br'{\rtf1\ansi\b Heading\b0\par Value: initial\par\i Note\i0}')
    initial = state.inspect(str(path), 'rich_text')
    if initial['status'] == 'unavailable':
        pytest.fail(f'Native rich-text conversion failed: {initial}')
    fragments = [r for p in initial['result']['paragraphs'] for r in p if r['bold'] or r['italic']]
    assert {r['text'] for r in fragments} == {'Heading', 'Note'}
    state.declare('formatting_preserved', str(path), json.dumps(fragments), 'Preserve the other document.')
    state.action('type', {'text': 'replacement'}, 'ok')
    path.write_bytes(br'{\rtf1\ansi\b Heading\b0\par Value: changed\par\i Note\i0}')
    assert state.verify()['all_declared_checks_pass']
    path.write_bytes(br'{\rtf1\ansi Heading\par Value: changed\par Note}')
    assert not state.verify()['all_declared_checks_pass']


def test_eval_records_are_separate_and_previous_runs_never_enter_context(state, tmp_path):
    analysis = tmp_path/'analysis'
    analysis.mkdir()
    secret = 'HELD_OUT_ANSWER_'+uuid.uuid4().hex
    record_eval({'pass': True, 'check_detail': secret}, analysis)
    old = Graph(tmp_path/'old.sqlite', 'past-run')
    old.record_run({'answer': secret})
    old.close()
    assert secret not in json.dumps(state.observe())
    assert not any('evaluation' in row[0] for row in state.graph.db.execute('SELECT kind FROM events'))
    # Separate SQLite connection can inspect persisted action/observation provenance.
    db = sqlite3.connect(state.directory/'state.sqlite')
    assert db.execute("SELECT count(*) FROM events WHERE kind='observation'").fetchone()[0] == 1
    db.close()


def test_runtime_source_has_no_evaluator_dependency_or_task_specific_answers():
    import ast
    from pathlib import Path
    modules = ['desktop.py', 'evidence.py', 'telemetry.py', 'knowledge.py', 'skills.py']
    for name in modules:
        source = Path(name).read_text()
        imports = [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.Import, ast.ImportFrom))]
        for node in imports:
            names = [node.module or ''] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
            assert not any(n.startswith(('evals', 'tests')) for n in names)
        assert 'tasks.json' not in source and 'claim_review.json' not in source
    # The runtime's only persistent-memory entry point is deliberately disabled.
    from knowledge import related_context
    assert related_context('anything') == ''


def test_permissions_predicate_and_empty_contains_are_not_vacuous(state, workspace):
    path = workspace/'folder'
    path.mkdir(mode=0o755)
    state.declare('mode_equals', str(path), '755', 'Preserve the other document.')
    assert state.verify()['all_declared_checks_pass']
    path.chmod(0o555)
    assert not state.verify()['all_declared_checks_pass']
    for kind in ['text_contains', 'pdf_text_contains']:
        with pytest.raises(ValueError, match='nonempty'):
            state.declare(kind, str(path), '', 'Write the requested text.')
    with pytest.raises(ValueError, match='octal'):
        state.declare('mode_equals', str(path), '999', 'Preserve the other document.')


def test_inspection_and_packet_sizes_are_bounded(state, workspace, monkeypatch):
    path = workspace/'long.txt'
    path.write_text('z'*(telemetry.MAX_TEXT+100))
    assert '[truncated]' in state.inspect(str(path))['result']['text']
    monkeypatch.setattr(telemetry, 'snapshot', lambda: {'ui': {'children': [{'value': 'x'*20000} for _ in range(100)]}})
    packet = state.observe()
    assert packet['truncated'] is True
    assert len(json.dumps(packet)) < 34000


def test_flat_and_graph_expose_the_same_retained_facts(tmp_path, workspace, monkeypatch):
    monkeypatch.setattr(telemetry, 'snapshot', lambda: {'time': 1, 'windows': [], 'ui': {}})
    (workspace/'item.txt').write_text('same information')
    flat = RunState('Inspect item.txt.', tmp_path/'flat', [workspace], 'flat')
    graph = RunState('Inspect item.txt.', tmp_path/'graph', [workspace], 'graph')
    try:
        f, g = flat.observe(), graph.observe()
        assert f['workspace'] == g['workspace']
        relations = [(r['subject']['id'], r['predicate'], r['object']['id'], r['status']) for r in f['state_facts']]
        assert relations == [(r['source'], r['relation'], r['target'], r['status']) for r in g['graph']['relations']]
        assert 'graph' not in f and 'state_facts' not in g
    finally:
        flat.close('test')
        graph.close('test')


def test_workspace_cannot_include_its_run_outputs(tmp_path, workspace):
    with pytest.raises(ValueError, match='outside observable'):
        RunState('Inspect files.', workspace/'run', [workspace])
    assert not (workspace/'run').exists()


def test_external_changes_invalidate_inspections_and_cached_checks(state, workspace):
    path = workspace/'external.txt'
    path.write_text('initial')
    state.observe()
    inspection = state.inspect(str(path))
    state.declare('text_equals', str(path), 'initial', 'Write the requested text.')
    assert state.verify()['all_declared_checks_pass']
    path.write_text('external update')
    packet = state.observe()
    assert state.inspections[inspection['id']]['status'] == 'stale'
    assert packet['declared_checks'][0]['status'] == 'unknown'


def test_excluded_files_do_not_make_ordinary_scan_incomplete(workspace):
    (workspace/'.DS_Store').write_text('hidden')
    (workspace/'secret.key').write_text('credential')
    (workspace/'public.txt').write_text('observable')
    scan = telemetry.Workspace([workspace]).scan()
    assert scan['complete']
    assert set(scan['files']) == {str(workspace/'public.txt')}


def test_incomplete_initial_scan_never_invents_creation():
    before = {'files': {}, 'complete': False}
    after = {'files': {'possibly_already_existed': {'sha256': 'x'}}, 'complete': True}
    assert telemetry.file_events(before, after)[0]['event'] == 'unknown'
