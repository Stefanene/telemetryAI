"""Bounded, read-only observations. No evaluator imports, task IDs, or fixture answers.

Workspace roots are explicitly supplied by the caller, never inferred from an eval ID.
UI data is untrusted content, not instructions. No collector executes model-supplied code.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_BYTES = 1_000_000
MAX_FILES = 300
MAX_TEXT = 8000
REPO = Path(__file__).resolve().parent


def redact(value):
    """Best-effort minimization, not a guarantee that arbitrary documents contain no secrets."""
    if isinstance(value, dict):
        return {k: ('[redacted]' if re.search(r'password|secret|token|api.?key', k, re.I)
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}', '[redacted]', value)
        return re.sub(r'(?i)((?:password|api[_ -]?key|secret|token)\s*[:=]\s*)\S+',
                      r'\1[redacted]', value)
    return value


def _jxa(script: str, *args):
    proc = subprocess.run(['osascript', '-l', 'JavaScript', '-e', script, *map(str, args)],
                          check=True, capture_output=True, text=True, timeout=5)
    return redact(json.loads(proc.stdout))


def frontmost_app() -> dict:
    return _jxa('''const p=Application('System Events').applicationProcesses.whose({frontmost:true})[0];
JSON.stringify({name:p.name(),bundle_id:p.bundleIdentifier(),pid:p.unixId()});''')


def window_list() -> list[dict]:
    return _jxa('''const p=Application('System Events').applicationProcesses.whose({frontmost:true})[0];
JSON.stringify(p.windows().slice(0,10).map(w=>({app:p.name(),title:w.name(),
bounds:w.position().concat(w.size())})));''')


def ui_tree(app: str | None = None, depth: int = 3) -> dict:
    # Bounds are screen points, deliberately not advertised as screenshot click coordinates.
    return _jxa('''function run(argv) {
const se=Application('System Events'), p=argv[0] ? se.applicationProcesses.byName(argv[0]) :
se.applicationProcesses.whose({frontmost:true})[0]; let count=0;
function read(e,key) {try{return e[key]();}catch(_){return null;}}
function walk(e,d) {
 if (++count>100) return {truncated:true};
 const role=read(e,'role'), subrole=read(e,'subrole');
 if (subrole==='AXSecureTextField') return {role,subrole,value:'[redacted]'};
 const node={role,subrole,label:read(e,'name'),value:read(e,'value'),
 focused:read(e,'focused'),position:read(e,'position'),size:read(e,'size')};
 if(d>0 && count<100) {try{node.children=e.uiElements().slice(0,25).map(c=>walk(c,d-1));}catch(_){}}
 return node;
}
return JSON.stringify({coordinate_space:'screen_points',app:p.name(),
windows:p.windows().slice(0,2).map(w=>walk(w,+argv[1]))});
}''', app or '', max(0, min(depth, 4)))


def system_snapshot() -> dict:
    usage = shutil.disk_usage(Path.home())
    return {'disk_free_gb': round(usage.free / 1e9, 2), 'load_average': list(os.getloadavg())}


def recent_logs(minutes: int = 1, predicate: str | None = None) -> list[str]:
    # Diagnostics only: fixed predicate, bounded subprocess output on disk via temporary file.
    if predicate is not None:
        raise ValueError('Arbitrary log predicates are not exposed to the agent')
    import tempfile
    with tempfile.TemporaryFile() as out:
        app = frontmost_app()['name']
        subprocess.run(['log', 'show', '--last', f'{max(1, min(minutes, 2))}m', '--style', 'compact',
                        '--predicate', 'process == ' + json.dumps(app)], stdout=out, stderr=subprocess.DEVNULL,
                       check=True, timeout=5)
        out.seek(0)
        return redact(out.read(MAX_TEXT).decode(errors='replace').splitlines()[:40])


def snapshot() -> dict:
    result = {'time': time.time()}
    for name, collector in [('frontmost_app', frontmost_app), ('windows', window_list), ('ui', ui_tree)]:
        try:
            result[name] = collector()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result[name] = {'status': 'unavailable', 'error': type(exc).__name__}
    return result


class Workspace:
    """Read only explicitly allowed, non-hidden workspace artifacts; never follow symlinks.

    Roots cannot contain the repository, home, or filesystem root. File reads use O_NOFOLLOW
    and fstat; concurrent changes are detected. Intended for a single-user desktop, not an
    adversarial filesystem sandbox.
    """
    def __init__(self, roots=()):
        self.roots = tuple(Path(p).expanduser().resolve(strict=True) for p in roots)
        for root in self.roots:
            if not root.is_dir() or root == Path.home() or root == Path('/') or root == REPO or REPO.is_relative_to(root) or root.is_relative_to(REPO):
                raise ValueError('Choose a dedicated task workspace outside the repository')

    def path(self, value: str | Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError('Use an absolute workspace path')
        path = Path(os.path.abspath(path))
        root = next((r for r in self.roots if path.is_relative_to(r)), None)
        if root is None:
            raise ValueError('Path is outside allowed workspace roots')
        for part in path.relative_to(root).parts:
            if part.startswith('.') or part.lower().endswith(('.pem', '.key', '.p12')):
                raise ValueError('Hidden or credential files are excluded')
        for ancestor in [path, *path.parents]:
            if ancestor == root:
                break
            if ancestor.is_symlink():
                raise ValueError('Symlinks are excluded')
        return path

    def read(self, value: str | Path) -> bytes:
        path = self.path(value)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
                raise ValueError('Not a regular file or file exceeds read limit')
            data = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(data) > MAX_BYTES or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('File changed during observation')
        current = path.stat()
        if any(getattr(after, k) != getattr(current, k) for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode')):
            raise ValueError('Path changed during observation')
        return data

    @staticmethod
    def _confirm_metadata(path, info):
        current = path.stat()
        if any(getattr(info, k) != getattr(current, k) for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode')):
            raise ValueError('File metadata changed during observation')

    def scan(self) -> dict:
        files, errors, count, truncated, directories = {}, [], 0, False, 0
        def onerror(exc):
            errors.append({'path': str(exc.filename), 'error': type(exc).__name__})
        for root in self.roots:
            for directory, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
                directories += 1
                if directories > MAX_FILES:
                    truncated = True
                    break
                dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory)/d).is_symlink())
                for name in sorted(names):
                    count += 1
                    if count > MAX_FILES:
                        truncated = True
                        break
                    path = Path(directory)/name
                    if name.startswith('.') or name.lower().endswith(('.pem', '.key', '.p12')) or path.is_symlink():
                        continue
                    try:
                        path = self.path(path)
                        info = path.stat()
                        if not stat.S_ISREG(info.st_mode):
                            continue
                        data = self.read(path)
                        self._confirm_metadata(path, info)
                        files[str(path)] = {'size': info.st_size, 'mtime_ns': info.st_mtime_ns,
                                            'device': info.st_dev, 'inode': info.st_ino,
                                            'mode': stat.S_IMODE(info.st_mode),
                                            'sha256': hashlib.sha256(data).hexdigest()}
                    except (OSError, ValueError) as exc:
                        errors.append({'path': str(path), 'error': type(exc).__name__})
                if truncated:
                    break
            if truncated:
                break
        return {'files': files, 'errors': errors, 'complete': not errors and not truncated, 'truncated': truncated}

    def inspect(self, value: str, kind: str = 'text') -> dict:
        path = self.path(value)
        try:
            info = path.stat()
        except FileNotFoundError:
            return {'path': str(path), 'exists': False, 'time': time.time()}
        result = {'path': str(path), 'exists': True, 'directory': path.is_dir(),
                  'mode': stat.S_IMODE(info.st_mode), 'time': time.time()}
        if path.is_dir():
            return result
        data = self.read(path)
        self._confirm_metadata(path, info)
        result.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        if kind == 'metadata':
            return result
        if kind == 'pdf':
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(data), strict=True)
            result.update(page_count=len(reader.pages), text='\n'.join(p.extract_text() or '' for p in reader.pages))
        elif kind == 'rich_text':
            # Read-only conversion from captured bytes avoids parsing an unscoped path.
            proc = subprocess.run(['textutil', '-convert', 'docx', '-stdin', '-stdout'], input=data,
                                  check=True, capture_output=True, timeout=5)
            with zipfile.ZipFile(BytesIO(proc.stdout)) as doc:
                xml = doc.read('word/document.xml')
            tree = ET.fromstring(xml)
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            paragraphs = []
            for p in tree.findall('.//w:body/w:p', ns):
                runs = []
                for run in p.findall('w:r', ns):
                    text = ''.join(t.text or '' for t in run.findall('w:t', ns))
                    def enabled(prop):
                        item = run.find(f'w:rPr/w:{prop}', ns)
                        return item is not None and item.get(f'{{{ns["w"]}}}val', 'true') not in ('0', 'false', 'off')
                    if text:
                        runs.append({'text': text, 'bold': enabled('b'), 'italic': enabled('i')})
                if runs:
                    paragraphs.append(runs)
            result.update(paragraphs=paragraphs, text='\n'.join(''.join(r['text'] for r in p) for p in paragraphs))
        elif kind == 'text':
            result['text'] = data.decode('utf-8')
        else:
            raise ValueError('Unknown inspection kind')
        return result


def file_events(before: dict, after: dict) -> list[dict]:
    """Diff explicit manifests; a timestamp alone cannot establish deletion or identity."""
    events = []
    for path in sorted(before['files'].keys() | after['files'].keys()):
        a, b = before['files'].get(path), after['files'].get(path)
        if a == b:
            continue
        if (b is None and not after['complete']) or (a is None and not before['complete']):
            events.append({'path': path, 'event': 'unknown', 'reason': 'incomplete scan'})
        else:
            events.append({'path': path, 'event': 'created' if a is None else 'deleted' if b is None else 'changed',
                           'before': a, 'after': b})
    return events


def bounded(value):
    """Redact and bound model-visible data; checks use original captured bytes locally."""
    if isinstance(value, dict):
        return {k: bounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [bounded(v) for v in value[:100]]
    if isinstance(value, str):
        text = redact(value)
        return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + '\n[truncated]'
    return value
