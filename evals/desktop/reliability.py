"""Fixtures and independent outcome checks for desktop reliability tasks.

No model calls or GUI actions during grading. App launch is setup-only and can
be disabled for offline tests. All task data stays in the supplied sandbox.
"""

import json
import stat
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

EXACT = "TelemetryAI desktop evaluation\nStatus: ready\nReference: 42\n"
OLD = "Weekly report\nStatus: draft\nTotal: 100\n"
UPDATED = "Weekly report\nStatus: approved\nTotal: 125\n"
TARGET = "Project: Orion\nStatus: draft\n"
TARGET_UPDATED = "Project: Orion\nStatus: approved\n"
DECOY = "Project: Vega\nStatus: draft\n"
MOVED = "Meeting notes\nDecision: proceed\n"
MOVED_UPDATED = MOVED + "Owner: Ryan\n"
PDF_TEXT = "GraphOS export validation\nReference: Telem-PDF-7391\nStatus: approved"
FALLBACK = "Recovery report\nReference: Telem-RECOVERY-82\n"


def rich_document(budget="1000") -> bytes:
    return (r"{\rtf1\ansi\deff0{\fonttbl{\f0 Helvetica;}}"
            r"\f0\fs24\b Project brief\b0\par "
            f"Budget: {budget}" + r"\par \i Internal use only\i0}").encode()


def _write(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content if isinstance(content, bytes) else content.encode())


def setup_task(task_id: str, root: Path, *, open_apps=True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _write(root, "unrelated.txt", "Keep this file unchanged.\n")
    opened = None
    if task_id == "exact_save":
        _write(root, "final-old.txt", "Do not edit this draft.\n")
    elif task_id == "preserve_formatting":
        _write(root, "brief.rtf", rich_document())
        opened = root / "brief.rtf"
    elif task_id == "replace_stale_output":
        _write(root, "report.txt", OLD)
    elif task_id == "duplicate_names":
        _write(root, "incoming/notes.txt", TARGET)
        _write(root, "archive/notes.txt", DECOY)
    elif task_id == "move_with_stale_editor":
        _write(root, "incoming/notes.txt", MOVED)
        _write(root, "archive/notes.txt", MOVED)
        (root / "reports").mkdir()
        opened = root / "archive/notes.txt"
    elif task_id == "pdf_export":
        _write(root, "source.txt", PDF_TEXT + "\n")
        opened = root / "source.txt"
    elif task_id == "blocked_destination":
        _write(root, "protected/keep.txt", "Protected original.\n")
        (root / "fallback").mkdir()
        (root / "protected/keep.txt").chmod(0o444)
        (root / "protected").chmod(0o555)
    else:
        raise ValueError(f"unknown reliability task: {task_id}")
    if open_apps:
        subprocess.run(["osascript", "-e", 'tell application "TextEdit" to quit saving no'],
                       check=True, capture_output=True, timeout=30)
        if opened:
            subprocess.run(["osascript", "-e", 'on run argv\n'
                            'tell application "TextEdit"\nactivate\n'
                            'open POSIX file (item 1 of argv)\nend tell\nend run', str(opened)],
                           check=True, capture_output=True, timeout=30)


def cleanup_task(task_id: str, root: Path) -> None:
    if task_id == "blocked_destination" and (root / "protected").is_dir():
        (root / "protected").chmod(0o755)
        if (root / "protected/keep.txt").is_file():
            (root / "protected/keep.txt").chmod(0o644)


def _matches(root, path, content):
    file = root / path
    return (file.is_file() and not file.is_symlink()
            and file.read_bytes() == (content if isinstance(content, bytes) else content.encode()))


def _rich_runs(path):
    # TextEdit's native converter preserves semantic runs; do not compare raw
    # RTF bytes, since a legitimate save may rewrite RTF control words/fonts.
    data = subprocess.run(["textutil", "-convert", "docx", "-stdout", str(path)],
                          capture_output=True, check=True, timeout=20).stdout
    with zipfile.ZipFile(BytesIO(data)) as doc:
        tree = ET.fromstring(doc.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in tree.findall(".//w:body/w:p", ns):
        runs = []
        for run in paragraph.findall(".//w:r", ns):
            text = "".join(t.text or "" for t in run.findall("w:t", ns))
            def enabled(prop):
                node = run.find(f"w:rPr/w:{prop}", ns)
                return node is not None and node.get(f"{{{ns['w']}}}val", "true") not in ("0", "false", "off")
            if text:
                runs.append((text, enabled("b"), enabled("i")))
        if runs:
            paragraphs.append(runs)
    return paragraphs


def grade_task(task_id: str, root: Path) -> tuple[bool, str]:
    """Return pass + a diagnostic, independent of the agent's claimed success."""
    try:
        passed = _grade(task_id, root)
    except ImportError as exc:
        # A missing grader dependency is an infrastructure error, not an agent failure.
        raise RuntimeError("PDF grading requires uv sync --extra desktop-eval --group dev") from exc
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile, ET.ParseError) as exc:
        return False, f"Invalid or unreadable artifact: {type(exc).__name__}: {exc}"
    return passed, "All required outcomes verified." if passed else "Output or preservation checks failed."


def _grade(task_id, root):
    if not _matches(root, "unrelated.txt", "Keep this file unchanged.\n"):
        return False
    if task_id == "exact_save":
        return _matches(root, "final.txt", EXACT) and _matches(root, "final-old.txt", "Do not edit this draft.\n")
    if task_id == "preserve_formatting":
        path = root / "brief.rtf"
        if not path.is_file() or path.is_symlink() or not path.read_bytes().startswith(b"{\\rtf"):
            return False
        paragraphs = _rich_runs(path)
        return (["".join(r[0] for r in p) for p in paragraphs]
                == ["Project brief", "Budget: 1200", "Internal use only"]
                and all(r[1] for r in paragraphs[0]) and all(r[2] for r in paragraphs[2]))
    if task_id == "replace_stale_output":
        return _matches(root, "report.txt", UPDATED)
    if task_id == "duplicate_names":
        return _matches(root, "incoming/notes.txt", TARGET_UPDATED) and _matches(root, "archive/notes.txt", DECOY)
    if task_id == "move_with_stale_editor":
        return (_matches(root, "reports/notes.txt", MOVED_UPDATED)
                and not (root / "incoming/notes.txt").exists()
                and _matches(root, "archive/notes.txt", MOVED))
    if task_id == "pdf_export":
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
        path = root / "export.pdf"
        if not path.is_file() or path.is_symlink() or not path.read_bytes().startswith(b"%PDF-"):
            return False
        try:
            reader = PdfReader(path, strict=True)
            text = " ".join((page.extract_text() or "") for page in reader.pages)
            return (len(reader.pages) == 1 and " ".join(text.split()) == " ".join(PDF_TEXT.split())
                    and _matches(root, "source.txt", PDF_TEXT + "\n"))
        except PyPdfError:
            return False
    if task_id == "blocked_destination":
        return (_matches(root, "fallback/report.txt", FALLBACK)
                and _matches(root, "protected/keep.txt", "Protected original.\n")
                and sorted(p.name for p in (root / "protected").iterdir()) == ["keep.txt"]
                and stat.S_IMODE((root / "protected").stat().st_mode) == 0o555
                and stat.S_IMODE((root / "protected/keep.txt").stat().st_mode) == 0o444)
    raise ValueError(f"unknown reliability task: {task_id}")


def completion_review(run_dir: Path, passed: bool) -> dict:
    """Optional human annotation; never infer success claims from keyword hits."""
    path = run_dir / "claim_review.json"
    if not path.exists():
        return {"claimed_success": None, "false_completion": None}
    review = json.loads(path.read_text())
    claimed = review["claimed_success"]
    if type(claimed) is not bool:
        raise ValueError("claim_review.json claimed_success must be a boolean")
    return {"claimed_success": claimed, "false_completion": claimed and not passed}
