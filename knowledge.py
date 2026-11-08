"""Run-local evidence graph backed by SQLite. Runtime never reads evaluation results.

Cross-run retrieval is deliberately disabled: no online learning from held-out evaluations.
Relations say 'observed after', not 'caused by'. A path is not a document identity.
"""
from __future__ import annotations

import json
from functools import wraps
from threading import RLock
import sqlite3
import time
from pathlib import Path

import telemetry

GRAPH_DIR = Path(__file__).parent / 'knowledge'


def synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


class Graph:
    def __init__(self, path: Path, run_id: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.run_id = run_id
        self.db.executescript('''
CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, kind TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS edges(source TEXT, relation TEXT, target TEXT,
 status TEXT, observed_at REAL, PRIMARY KEY(source,relation,target));
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, kind TEXT, data TEXT, observed_at REAL);
''')
        self.previous_action = None
        self.node(run_id, 'Run', {'started': time.time()})

    @synchronized
    def node(self, id: str, kind: str, data: dict):
        self.db.execute('INSERT OR REPLACE INTO nodes VALUES(?,?,?)',
                        (id, kind, json.dumps(telemetry.bounded(data))))
        self.db.commit()
        return id

    @synchronized
    def edge(self, source: str, relation: str, target: str, status='observed'):
        self.db.execute('INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?)',
                        (source, relation, target, status, time.time()))
        self.db.commit()

    @synchronized
    def event(self, kind: str, data: dict) -> str:
        cursor = self.db.execute('INSERT INTO events(kind,data,observed_at) VALUES(?,?,?)',
                                 (kind, json.dumps(telemetry.bounded(data)), time.time()))
        self.db.commit()
        return f'{self.run_id}:{kind}:{cursor.lastrowid}'

    @synchronized
    def record_action(self, tool: str, args: dict, result: str):
        id = self.event('action', {'tool': tool, 'args': args, 'transport_result': result})
        self.node(id, 'Action', {'tool': tool, 'args': args, 'transport_result': result})
        self.edge(self.run_id, 'performed', id)
        if self.previous_action:
            self.edge(self.previous_action, 'followed_by', id)
        self.previous_action = id
        # All earlier state observations become historical, not current evidence.
        self.db.execute("UPDATE edges SET status='stale' WHERE relation IN ('current_version','frontmost','visible_window')")
        self.db.commit()
        return id

    @synchronized
    def observe(self, ui: dict, manifest: dict, changes: list):
        id = self.event('observation', {'ui': ui, 'manifest': manifest, 'changes': changes})
        self.node(id, 'Observation', {'time': ui.get('time'), 'complete': manifest['complete']})
        self.edge(self.run_id, 'observed', id)
        if self.previous_action:
            self.edge(id, 'observed_after', self.previous_action)
        self.db.execute("UPDATE edges SET status='stale' WHERE relation IN ('current_version','frontmost','visible_window')")
        app = ui.get('frontmost_app', {})
        if app.get('bundle_id'):
            app_id = f'app:{app["bundle_id"]}:{app.get("pid")}'
            self.node(app_id, 'App', app)
            self.edge(self.run_id, 'frontmost', app_id)
        windows = ui.get('windows', [])
        for n, window in enumerate(windows if isinstance(windows, list) else []):
            win = self.node(f'{id}:window:{n}', 'Window', window)
            self.edge(self.run_id, 'visible_window', win)
            self.edge(id, 'supports', win)
            # Deliberately no window->file association based only on a shared basename.
        for path, info in manifest['files'].items():
            file_id = self.node(f'path:{path}', 'Path', {'path': path})
            version = self.node(f'version:{path}:{info["sha256"]}:{info["mtime_ns"]}', 'FileVersion', info)
            self.edge(file_id, 'current_version', version)
            self.edge(id, 'supports', version)
        # Potential moves are explicitly inferred; identical content/inode is not definitive.
        deleted = [c for c in changes if c['event'] == 'deleted']
        created = [c for c in changes if c['event'] == 'created']
        for a in deleted:
            for b in created:
                old, new = a['before'], b['after']
                if (old['device'], old['inode'], old['sha256']) == (new['device'], new['inode'], new['sha256']):
                    self.edge(f'path:{a["path"]}', 'possibly_moved_to', f'path:{b["path"]}', 'inferred')
        self.db.commit()
        return id

    @synchronized
    def inspection(self, result: dict, kind: str):
        id = self.event('inspection', {'kind': kind, 'result': result})
        self.node(id, 'Inspection', {'kind': kind, 'result': result})
        self.edge(self.run_id, 'observed', id)
        return id

    @synchronized
    def record_run(self, outcome: dict):
        self.event('agent_outcome', outcome)  # claim, not an independent grade

    @synchronized
    def context(self, limit=60) -> dict:
        rows = self.db.execute('''SELECT source,relation,target,status,observed_at FROM edges
WHERE status != 'stale' AND relation IN ('current_version','frontmost','visible_window','possibly_moved_to','performed','followed_by')
ORDER BY observed_at DESC LIMIT ?''', (limit,)).fetchall()
        ids = {v for r in rows for v in (r[0], r[2])}
        nodes = []
        for id in sorted(ids):
            row = self.db.execute('SELECT kind,data FROM nodes WHERE id=?', (id,)).fetchone()
            if row:
                nodes.append({'id': id, 'kind': row[0], 'data': json.loads(row[1])})
        return {'nodes': nodes, 'relations': [dict(zip(('source','relation','target','status','time'), r)) for r in rows],
                'note': 'Observed relationships only; possible moves are inferred. No basename establishes document identity.'}

    @synchronized
    def close(self):
        self.db.close()


def record_eval(row: dict, run_dir: Path) -> None:
    """Write analysis beside the grader artifacts; Graph never opens this file or directory."""
    (run_dir / 'evaluation_analysis.json').write_text(json.dumps(row, indent=2) + '\n')


def related_context(task: str, limit: int = 5) -> str:
    """Disabled until a frozen, provenance-audited development memory is available."""
    return ''
