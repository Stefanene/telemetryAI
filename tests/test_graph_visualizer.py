"""Offline graph snapshots, actual SVG/PNG outputs and read-only export."""
import json
import sqlite3
import sys
from xml.etree import ElementTree as ET

import pytest

from knowledge import Graph
import graph_visualizer as viz


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setenv('GRAPH_VISUALIZATION', 'updates')
    monkeypatch.setenv('GRAPH_SNAPSHOT_KEEP', '3')
    graph = Graph(tmp_path/'state.sqlite', 'visual-test')
    yield graph
    graph.close()


def test_snapshots_follow_additions_modifications_and_prune_history(graph):
    folder = graph.visualizations.directory
    before = json.loads((folder/'latest.json').read_text())
    assert before['reason'] == 'initialized'
    action = graph.record_action('key', {'combo': 'cmd+s'}, 'ok')
    added = json.loads((folder/'latest.json').read_text())
    assert any(n['id'] == action for n in added['nodes'])
    graph.node(action, 'Action', {'tool': 'key', 'args': {'combo': 'escape'}, 'transport_result': 'error'})
    graph.checkpoint('changed action')
    modified = json.loads((folder/'latest.json').read_text())
    assert next(n for n in modified['nodes'] if n['id'] == action)['data']['transport_result'] == 'error'
    for _ in range(5):
        graph.record_action('key', {'combo': 'tab'}, 'ok')
    assert len(list(folder.glob('[0-9]*.json'))) == 3
    assert len(list(folder.glob('[0-9]*.svg'))) == 3
    ET.parse(folder/'latest.svg')


def test_actual_png_output_and_nonempty_diagram(graph):
    image_module = pytest.importorskip('PIL.Image', reason='PNG is an optional graph-viz extra')
    graph.record_action('key', {'combo': 'cmd+s'}, 'ok')
    path = graph.visualizations.directory/'latest.png'
    with image_module.open(path) as image:
        image.verify()
    with image_module.open(path) as image:
        assert image.width == 1480 and image.height >= 600
        assert len(image.getcolors(image.width*image.height)) > 10


def test_final_only_defers_export_and_off_does_not_create_images(tmp_path, monkeypatch):
    monkeypatch.setenv('GRAPH_VISUALIZATION', 'final')
    final = Graph(tmp_path/'final/state.sqlite', 'final')
    final.record_action('key', {'combo': 'return'}, 'ok')
    assert not final.visualizations.directory.exists()
    final.close()
    assert json.loads((final.visualizations.directory/'latest.json').read_text())['reason'] == 'final'
    monkeypatch.setenv('GRAPH_VISUALIZATION', 'off')
    off = Graph(tmp_path/'off/state.sqlite', 'off')
    off.record_action('key', {'combo': 'return'}, 'ok')
    off.close()
    assert not off.visualizations.directory.exists()


def test_svg_fallback_escaping_and_inferred_edge_style(tmp_path, monkeypatch):
    monkeypatch.setattr(viz, 'png', lambda view: None)
    graph = {'nodes': [{'id': 'a', 'kind': 'Path', 'data': {'path': '/folder/<script>.txt'}},
                       {'id': 'b', 'kind': 'Path', 'data': {'path': '/folder/destination.txt'}}],
             'edges': [{'source': 'a', 'target': 'b', 'relation': 'possibly_moved_to', 'status': 'inferred', 'time': 1}]}
    viz.Snapshots(tmp_path).save(graph, 'inferred move')
    markup = (tmp_path/'latest.svg').read_text()
    ET.fromstring(markup)
    assert '&lt;script&gt;' in markup and '<script>' not in markup
    assert 'stroke-dasharray' in markup
    assert not (tmp_path/'latest.png').exists()


def test_image_is_bounded_but_json_preserves_full_graph(tmp_path):
    nodes = [{'id': f'path:{i}', 'kind': 'Path', 'data': {'path': f'/workspace/{i}.txt'}} for i in range(60)]
    edges = [{'source': nodes[i]['id'], 'target': nodes[i+1]['id'], 'relation': 'related', 'status': 'observed', 'time': i} for i in range(59)]
    graph = {'nodes': nodes, 'edges': edges}
    view = viz.scene(graph, 'bounded', max_nodes=12)
    assert len(view['nodes']) <= 12 and '/60 nodes' in view['caption']
    viz.Snapshots(tmp_path).save(graph, 'large graph')
    assert len(json.loads((tmp_path/'latest.json').read_text())['nodes']) == 60


def test_render_error_is_diagnostic_not_agent_failure(graph, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise OSError('disk failure')
    monkeypatch.setattr(graph.visualizations, 'save', fail)
    action = graph.record_action('key', {'combo': 'escape'}, 'ok')
    assert 'visualization failed' in caplog.text
    assert graph.db.execute('SELECT kind FROM nodes WHERE id=?', (action,)).fetchone()[0] == 'Action'
    assert graph.db.execute("SELECT count(*) FROM events WHERE kind='visualization_error'").fetchone()[0] == 1
    # Restore before fixture close so its final export is also tested normally.
    monkeypatch.undo()


def test_offline_cli_does_not_modify_database(graph, tmp_path, monkeypatch):
    graph.record_action('key', {'combo': 'cmd+s'}, 'ok')
    path = tmp_path/'state.sqlite'
    before = path.read_bytes()
    monkeypatch.setattr(sys, 'argv', ['graph_visualizer.py', str(path), '--output', str(tmp_path/'export')])
    viz.main()
    assert path.read_bytes() == before
    assert (tmp_path/'export/latest.svg').exists()
    assert json.loads((tmp_path/'export/latest.json').read_text())['reason'] == 'offline export'
