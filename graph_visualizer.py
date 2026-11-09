"""Local SVG/optional PNG views of persisted evidence graphs; never agent inputs.

SVG needs only the standard library. Install the graph-viz extra for PNG.
JSON exports preserve the complete stored graph; images show a labeled bounded view.
"""
from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
import sqlite3
import textwrap
from functools import lru_cache

COLORS = {'Run': '#263a59', 'Action': '#4172b5', 'Observation': '#16877f', 'Inspection': '#16877f',
          'App': '#6958a2', 'Window': '#6958a2', 'Path': '#b36b27', 'FileVersion': '#b36b27', 'GoalCondition': '#538447'}
LANES = [('Context', {'Run', 'App', 'Window'}), ('Actions', {'Action'}),
         ('Evidence', {'Observation', 'Inspection'}), ('Files & versions', {'Path', 'FileVersion'}),
         ('Declared checks', {'GoalCondition'})]


def read_graph(connection: sqlite3.Connection) -> dict:
    nodes = [{'id': id, 'kind': kind, 'data': json.loads(data)}
             for id, kind, data in connection.execute('SELECT id,kind,data FROM nodes ORDER BY rowid')]
    edges = [dict(zip(('source', 'relation', 'target', 'status', 'time'), row))
             for row in connection.execute('SELECT source,relation,target,status,observed_at FROM edges ORDER BY observed_at')]
    return {'nodes': nodes, 'edges': edges}


def label(node):
    data, kind = node['data'], node['kind']
    if kind == 'Run':
        return 'Run ' + node['id'][:12]
    if kind in {'App', 'Window'}:
        return str(data.get('name') or data.get('title') or node['id'])
    if kind == 'Action':
        args = data.get('args', {})
        # Avoid rendering typed document contents; show mechanics rather than private text.
        detail = args.get('combo', '') if data.get('tool') == 'key' else ('text input' if 'text' in args else str(args))
        return f'{data.get("tool", "action")}: {detail}'
    if kind == 'Path':
        parts = Path(data.get('path', node['id'])).parts
        return '/'.join(parts[-2:])
    if kind == 'FileVersion':
        return f'{data.get("size", "?")} bytes · {str(data.get("sha256", ""))[:10]}'
    if kind == 'GoalCondition':
        return f'{data.get("kind", "check")} · {data.get("status", "unknown")}\n{Path(data.get("path", "")).name}'
    if kind == 'Inspection':
        return f'{data.get("kind", "artifact")} · {Path(data.get("result", {}).get("path", "")).name}'
    return node['id'].rsplit(':', 2)[-2:][0] + ' #' + node['id'].rsplit(':', 1)[-1]


def scene(graph: dict, title: str, max_nodes: int = 25):
    if not 1 <= max_nodes <= 100:
        raise ValueError('max_nodes must be between 1 and 100')
    # Retain recent nodes in each category, without letting observation history displace everything.
    active = [e for e in graph['edges'] if e['status'] != 'stale']
    connected = {v for e in active for v in (e['source'], e['target'])}
    candidates = [n for n in graph['nodes'] if n['id'] in connected or n['kind'] == 'Run']
    selected = []
    for kinds in [lane[1] for lane in LANES]:
        pool = [n for n in candidates if n['kind'] in kinds]
        roots = [n for n in pool if n['kind'] == 'Run']
        others = [n for n in pool if n['kind'] != 'Run']
        selected.extend(roots[:1] + others[-(5-len(roots[:1])):])
    selected = selected[:max_nodes]
    ids = {n['id'] for n in selected}
    edges = [e for e in active if e['source'] in ids and e['target'] in ids][-40:]
    positions = {}
    largest = 1
    for column, (_, kinds) in enumerate(LANES):
        group = [n for n in selected if n['kind'] in kinds]
        largest = max(largest, len(group))
        for row, node in enumerate(group):
            positions[node['id']] = (40 + column * 280, 170 + row * 120)
    width, height = 1480, max(600, 250 + largest * 120)
    drawn = []
    for edge in edges:
        sx, sy = positions[edge['source']]
        tx, ty = positions[edge['target']]
        if sx == tx:
            start, end = (sx + 238, sy + 38), (tx + 238, ty + 38)
            bend = 24 + (sum(map(ord, edge['relation'])) % 3) * 10
            controls = ((sx + 238 + bend, sy + 38), (tx + 238 + bend, ty + 38))
        else:
            forward = tx > sx
            start, end = (sx + (238 if forward else 0), sy + 38), (tx + (0 if forward else 238), ty + 38)
            mid = (start[0] + end[0]) / 2
            controls = ((mid, start[1]), (mid, end[1]))
        drawn.append((edge, start, *controls, end))
    return {'graph': graph, 'nodes': selected, 'edges': drawn, 'positions': positions,
            'width': width, 'height': height, 'title': title,
            'caption': f'{len(selected)}/{len(graph["nodes"])} nodes · {len(edges)}/{len(graph["edges"])} edges shown '
                       '· observed/inferred edges · complete history in JSON/SQLite'}


def _lines(node):
    return textwrap.wrap(label(node).replace('\n', ' / '), width=28)[:2] or ['']


def svg(view) -> str:
    def escape(value):
        clean = ''.join(c if ord(c) >= 32 or c in '\n\t\r' else '\ufffd' for c in str(value))
        return html.escape(clean.encode('utf-8', errors='replace').decode(), quote=True)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{view["width"]}" height="{view["height"]}" viewBox="0 0 {view["width"]} {view["height"]}">',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#9aaabd"/></marker></defs>',
             '<rect width="100%" height="100%" fill="#f5f7fb"/>',
             f'<g font-family="Arial, sans-serif"><text x="40" y="46" font-size="25" font-weight="bold" fill="#20314a">{escape(view["title"])}</text>',
             f'<text x="40" y="76" font-size="15" fill="#526479">{escape(view["caption"])}</text>',
             '<text x="40" y="101" font-size="14" fill="#526479">Solid: observed   /   Dashed amber: inferred   /   Stale edges hidden   /   Checks are model-declared, not grades</text>']
    for col, (heading, _) in enumerate(LANES):
        parts.append(f'<text x="{40+col*280}" y="145" font-size="15" font-weight="bold" fill="#526479">{escape(heading.upper())}</text>')
    for edge, a, b, c, d in view['edges']:
        inferred = edge['status'] == 'inferred'
        color = '#cb912b' if inferred else '#9aaabd'
        dash = ' stroke-dasharray="5 4"' if inferred else ''
        parts.append(f'<path d="M {a[0]} {a[1]} C {b[0]} {b[1]} {c[0]} {c[1]} {d[0]} {d[1]}" fill="none" stroke="{color}" stroke-width="1.5"{dash} marker-end="url(#arrow)"/>')
        x, y = (a[0]+3*b[0]+3*c[0]+d[0])/8, (a[1]+3*b[1]+3*c[1]+d[1])/8
        parts.append(f'<text x="{x}" y="{y-6}" text-anchor="middle" font-size="11" fill="#526479" stroke="#f5f7fb" stroke-width="3" paint-order="stroke">{escape(edge["relation"])}</text>')
    for node in view['nodes']:
        x, y = view['positions'][node['id']]
        color = COLORS.get(node['kind'], '#526479')
        parts += [f'<rect x="{x}" y="{y}" width="238" height="78" rx="10" fill="white" stroke="{color}" stroke-width="1.5"/>',
                  f'<text x="{x+12}" y="{y+20}" font-size="11" font-weight="bold" fill="{color}">{escape(node["kind"])}</text>']
        for i, line in enumerate(_lines(node)):
            parts.append(f'<text x="{x+12}" y="{y+43+i*18}" font-size="14" fill="#20314a">{escape(line)}</text>')
    return '\n'.join(parts + ['</g></svg>'])


def png(view) -> bytes | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    from io import BytesIO
    image = Image.new('RGB', (view['width'], view['height']), '#f5f7fb')
    draw = ImageDraw.Draw(image)
    @lru_cache
    def font(size):
        for name in ['/System/Library/Fonts/Supplemental/Arial.ttf', 'DejaVuSans.ttf']:
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                pass
        return ImageFont.load_default(size=size)
    def text(xy, value, size=14, fill='#20314a'):
        draw.text(xy, str(value), font=font(size), fill=fill)
    text((40,20), view['title'], 25)
    text((40,58), view['caption'], 15, '#526479')
    text((40,87), 'Solid: observed  /  Dashed amber: inferred  /  Stale edges hidden  /  Checks are model-declared, not grades', 14, '#526479')
    for col, (heading, _) in enumerate(LANES):
        text((40+col*280,125), heading.upper(), 15, '#526479')
    for edge, a, b, c, d in view['edges']:
        points = []
        for i in range(41):
            t, u = i/40, 1-i/40
            points.append((u**3*a[0]+3*u*u*t*b[0]+3*u*t*t*c[0]+t**3*d[0],
                           u**3*a[1]+3*u*u*t*b[1]+3*u*t*t*c[1]+t**3*d[1]))
        color = '#cb912b' if edge['status'] == 'inferred' else '#9aaabd'
        for i in range(40):
            if edge['status'] != 'inferred' or i%4 < 2:
                draw.line([points[i], points[i+1]], fill=color, width=2)
        angle = math.atan2(d[1]-points[-2][1], d[0]-points[-2][0])
        arrow = [d, (d[0]-8*math.cos(angle-.45), d[1]-8*math.sin(angle-.45)),
                    (d[0]-8*math.cos(angle+.45), d[1]-8*math.sin(angle+.45))]
        draw.polygon(arrow, fill=color)
        x,y = points[20]
        value = edge['relation']
        bounds = draw.textbbox((0,0), value, font=font(11))
        draw.rectangle((x-(bounds[2]+6)/2,y-15,x+(bounds[2]+6)/2,y), fill='#f5f7fb')
        text((x-bounds[2]/2,y-15), value, 11, '#526479')
    for node in view['nodes']:
        x,y = view['positions'][node['id']]
        color = COLORS.get(node['kind'], '#526479')
        draw.rounded_rectangle((x,y,x+238,y+78), radius=10, fill='white', outline=color, width=2)
        text((x+12,y+8), node['kind'], 11, color)
        for i,line in enumerate(_lines(node)):
            text((x+12,y+30+i*18), line)
    out = BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


class Snapshots:
    """Bounded history after logical updates, not after individual SQL statements."""
    def __init__(self, directory: Path, mode='updates', keep=20):
        if mode not in {'off', 'final', 'updates'} or not 1 <= keep <= 200:
            raise ValueError('Visualization mode must be off/final/updates; keep must be 1..200')
        self.directory, self.mode, self.keep = directory, mode, keep
        self.sequence = 0

    def save(self, graph: dict, reason: str, final=False):
        if self.mode == 'off' or (self.mode == 'final' and not final):
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.sequence == 0:
            self.sequence = max((int(p.stem) for p in self.directory.glob('[0-9][0-9][0-9][0-9][0-9][0-9].json')), default=0)
        self.sequence += 1
        title = f'Knowledge graph · {self.sequence:04d} · {reason}'
        view = scene(graph, title)
        data = {'json': json.dumps({'reason': reason, **graph}, indent=2).encode(),
                'svg': svg(view).encode()}
        rendered = png(view)
        if rendered is not None:
            data['png'] = rendered
        else:
            (self.directory/'latest.png').unlink(missing_ok=True)
        for ext, content in data.items():
            numbered = self.directory/f'{self.sequence:06d}.{ext}'
            numbered.write_bytes(content)
            temporary = self.directory/f'latest.{ext}.tmp'
            temporary.write_bytes(content)
            temporary.replace(self.directory/f'latest.{ext}')
        frames = sorted(self.directory.glob('[0-9][0-9][0-9][0-9][0-9][0-9].json'))
        for frame in frames[:-self.keep]:
            for ext in ('json', 'svg', 'png'):
                frame.with_suffix('.'+ext).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Read-only offline rendering cannot modify the run database or call models.
    with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True) as db:
        graph = read_graph(db)
    Snapshots(args.output).save(graph, 'offline export', final=True)


if __name__ == '__main__':
    main()
