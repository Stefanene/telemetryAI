"""Local screenshot filtering. Never logs OCR text; no model or network access."""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class PrivacyError(RuntimeError):
    """Capture must not be published when requested protection cannot be applied."""


@dataclass(frozen=True)
class PrivacyConfig:
    mode: str = 'off'
    masks: tuple[tuple[float, float, float, float], ...] = ()
    keep: int = 100

    @classmethod
    def from_env(cls):
        try:
            mode = os.environ.get('SCREENSHOT_PRIVACY', 'off').lower()
            if mode not in {'off', 'masks', 'ocr'}:
                raise ValueError()
            raw = json.loads(os.environ.get('SCREENSHOT_MASKS', '[]'))
            if not isinstance(raw, list):
                raise ValueError()
            masks = []
            for rect in raw:
                if not isinstance(rect, list) or len(rect) != 4:
                    raise ValueError()
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in rect):
                    raise ValueError()
                x, y, w, h = rect
                if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1-x and 0 < h <= 1-y):
                    raise ValueError()
                masks.append(tuple(rect))
            keep = int(os.environ.get('SCREENSHOT_KEEP', '100'))
            if keep < 1 or (mode == 'off' and masks):
                raise ValueError()
            return cls(mode, tuple(masks), keep)
        except (ValueError, TypeError):
            raise PrivacyError('Invalid screenshot privacy configuration; capture blocked.') from None

    def summary(self):
        return {'mode': self.mode, 'mask_count': len(self.masks), 'keep': self.keep}


# Deliberately conservative categories. Arbitrary names, addresses, faces and handwriting
# cannot be reliably identified with these patterns; use fixed masks for those regions.
PATTERNS = [
    re.compile(r'\b[A-Z0-9._%+\-]+\s*@\s*[A-Z0-9.\-]+\.[A-Z]{2,}\b', re.I),
    re.compile(r'(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)'),
    re.compile(r'(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\d)'),
    re.compile(r'(?<!\d)(?:\d[ -]?){13,19}(?!\d)'),
    re.compile(r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|AKIA[A-Z0-9]{16})\b'),
    re.compile(r'\b(?:password|passwd|secret|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S+', re.I),
    re.compile(r'\bBearer\s+\S+', re.I),
]


def ocr_boxes(path: Path) -> list[tuple[int, int, int, int]]:
    """Tesseract TSV words grouped by line. Matched spans redact all intersecting words."""
    try:
        result = subprocess.run(['tesseract', str(path), 'stdout', 'tsv'],
                                check=True, capture_output=True, text=True, timeout=15)
        lines = {}
        reader = csv.DictReader(io.StringIO(result.stdout), delimiter='\t', quoting=csv.QUOTE_NONE)
        required = {'level', 'page_num', 'block_num', 'par_num', 'line_num', 'left', 'top', 'width', 'height', 'text'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError()
        for row in reader:
            if row['level'] != '5' or not row['text'].strip():
                continue
            key = tuple(row[k] for k in ('page_num', 'block_num', 'par_num', 'line_num'))
            box = tuple(int(row[k]) for k in ('left', 'top', 'width', 'height'))
            if min(box) < 0 or box[2] == 0 or box[3] == 0:
                raise ValueError()
            lines.setdefault(key, []).append((row['text'], box))
        boxes = []
        for words in lines.values():
            text, spans = '', []
            for word, box in words:
                start = len(text)
                text += word + ' '
                spans.append((start, len(text)-1, box))
            for pattern in PATTERNS:
                for match in pattern.finditer(text):
                    boxes.extend(box for start, end, box in spans if start < match.end() and end > match.start())
        return list(dict.fromkeys(boxes))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError, csv.Error):
        # Never expose subprocess stderr, filenames, or OCR output to the agent/logs.
        raise PrivacyError('Local screenshot OCR unavailable or failed; capture blocked.') from None


def protect(path: Path, config: PrivacyConfig) -> int:
    """Overwrite a private temporary image before publication; dimensions stay unchanged."""
    if config.mode == 'off':
        return 0
    try:
        from PIL import Image, ImageDraw
        with Image.open(path) as source:
            image = source.convert('RGB')
        width, height = image.size
        boxes = [(math.floor(x*width), math.floor(y*height), math.ceil(w*width), math.ceil(h*height))
                 for x, y, w, h in config.masks]
        if config.mode == 'ocr':
            boxes.extend(ocr_boxes(path))
        draw = ImageDraw.Draw(image)
        for x, y, w, h in boxes:
            # Padding covers antialiasing and imperfect OCR word bounds; no reversible blur.
            draw.rectangle((max(0, x-6), max(0, y-6), min(width-1, x+w+6), min(height-1, y+h+6)), fill='black')
        image.save(path, format='JPEG', quality=95)
        return len(boxes)
    except PrivacyError:
        raise
    except Exception:
        raise PrivacyError('Screenshot redaction failed; capture blocked.') from None


def prune(directory: Path, keep: int, current: Path):
    """Bound screen-* files in this directory only; never touch graph images or run logs."""
    paths = sorted((p for p in directory.glob('screen-*.jpg') if p.is_file() and not p.is_symlink()),
                   key=lambda p: p.name, reverse=True)
    others = [p for p in paths if p != current]
    for path in others[max(0, keep-1):]:
        path.unlink(missing_ok=True)
