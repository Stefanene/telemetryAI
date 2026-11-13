"""Independent graders: prove correct artifacts pass and plausible mistakes fail."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "desktop_reliability", Path(__file__).parents[1] / "evals/desktop/reliability.py")
reliability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reliability)

TASKS = ["exact_save", "preserve_formatting", "replace_stale_output", "duplicate_names",
         "move_with_stale_editor", "pdf_export", "blocked_destination"]


def make_pdf(path, text):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    lines = ["BT /F1 12 Tf 40 700 Td"]
    for line in text.splitlines():
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines.append(f"({escaped}) Tj 0 -20 Td")
    stream.set_data(("\n".join(lines) + "\nET").encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as f:
        writer.write(f)


def complete(task, root):
    r = reliability
    if task == "exact_save":
        (root / "final.txt").write_text(r.EXACT)
    elif task == "preserve_formatting":
        if not shutil.which("textutil"):
            pytest.skip("semantic RTF grading requires macOS textutil")
        (root / "brief.rtf").write_bytes(r.rich_document("1200"))
    elif task == "replace_stale_output":
        (root / "report.txt").write_text(r.UPDATED)
    elif task == "duplicate_names":
        (root / "incoming/notes.txt").write_text(r.TARGET_UPDATED)
    elif task == "move_with_stale_editor":
        (root / "incoming/notes.txt").rename(root / "reports/notes.txt")
        (root / "reports/notes.txt").write_text(r.MOVED_UPDATED)
    elif task == "pdf_export":
        make_pdf(root / "export.pdf", r.PDF_TEXT)
    elif task == "blocked_destination":
        (root / "fallback/report.txt").write_text(r.FALLBACK)


@pytest.fixture(params=TASKS)
def case(request, tmp_path):
    task = request.param
    reliability.setup_task(task, tmp_path, open_apps=False)
    yield task, tmp_path
    reliability.cleanup_task(task, tmp_path)


def test_correct_outcomes_pass(case):
    task, root = case
    complete(task, root)
    assert reliability.grade_task(task, root)[0]


def test_no_op_does_not_pass(case):
    task, root = case
    assert not reliability.grade_task(task, root)[0]


def test_collateral_changes_fail(case):
    task, root = case
    complete(task, root)
    (root / "unrelated.txt").write_text("overwritten")
    assert not reliability.grade_task(task, root)[0]


@pytest.mark.parametrize("mistake", ["wrong_path", "partial", "extra_text", "changed_decoy"])
def test_exact_save_rejects_plausible_errors(tmp_path, mistake):
    r = reliability
    r.setup_task("exact_save", tmp_path, open_apps=False)
    (tmp_path / "final.txt").write_text(r.EXACT)
    if mistake == "wrong_path":
        (tmp_path / "final.txt").rename(tmp_path / "final-copy.txt")
    elif mistake == "partial":
        (tmp_path / "final.txt").write_text("Reference: 42\n")
    elif mistake == "extra_text":
        (tmp_path / "final.txt").write_text(r.EXACT + "Unrequested text\n")
    else:
        (tmp_path / "final-old.txt").write_text("edited")
    assert not r.grade_task("exact_save", tmp_path)[0]


def test_stale_file_and_separate_updated_copy_fail(tmp_path):
    r = reliability
    r.setup_task("replace_stale_output", tmp_path, open_apps=False)
    (tmp_path / "report-copy.txt").write_text(r.UPDATED)
    assert not r.grade_task("replace_stale_output", tmp_path)[0]


def test_edited_same_name_decoy_fails(tmp_path):
    r = reliability
    r.setup_task("duplicate_names", tmp_path, open_apps=False)
    (tmp_path / "archive/notes.txt").write_text(r.TARGET_UPDATED)
    assert not r.grade_task("duplicate_names", tmp_path)[0]
    (tmp_path / "incoming/notes.txt").write_text(r.TARGET_UPDATED)
    assert not r.grade_task("duplicate_names", tmp_path)[0]


@pytest.mark.parametrize("mistake", ["archive_edited", "source_recreated"])
def test_move_rejects_stale_editor_writes(tmp_path, mistake):
    r = reliability
    r.setup_task("move_with_stale_editor", tmp_path, open_apps=False)
    complete("move_with_stale_editor", tmp_path)
    (tmp_path / ("archive/notes.txt" if mistake == "archive_edited" else "incoming/notes.txt")).write_text(r.MOVED_UPDATED)
    assert not r.grade_task("move_with_stale_editor", tmp_path)[0]


@pytest.mark.parametrize("mistake", ["plain_text", "missing_bold", "missing_italic", "collateral_text"])
def test_rich_edit_rejects_formatting_or_content_loss(tmp_path, mistake):
    if not shutil.which("textutil"):
        pytest.skip("requires macOS textutil")
    r = reliability
    r.setup_task("preserve_formatting", tmp_path, open_apps=False)
    data = r.rich_document("1200")
    if mistake == "plain_text":
        data = b"Project brief\nBudget: 1200\nInternal use only"
    elif mistake == "missing_bold":
        data = data.replace(b"\\b ", b"")
    elif mistake == "missing_italic":
        data = data.replace(b"\\i ", b"")
    else:
        data = data.replace(b"Internal use only", b"Public document")
    (tmp_path / "brief.rtf").write_bytes(data)
    assert not r.grade_task("preserve_formatting", tmp_path)[0]


@pytest.mark.parametrize("mistake", ["renamed_text", "truncated_pdf", "blank_pdf", "wrong_content", "wrong_path"])
def test_pdf_export_checks_structure_content_and_path(tmp_path, mistake):
    r = reliability
    r.setup_task("pdf_export", tmp_path, open_apps=False)
    path = tmp_path / "export.pdf"
    if mistake == "renamed_text":
        path.write_text(r.PDF_TEXT)
    elif mistake == "truncated_pdf":
        path.write_bytes(b"%PDF-1.7\ninvalid\n%%EOF\n")
    elif mistake == "blank_pdf":
        writer = pytest.importorskip("pypdf").PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with path.open("wb") as f:
            writer.write(f)
    else:
        make_pdf(path, "old report" if mistake == "wrong_content" else r.PDF_TEXT)
        if mistake == "wrong_path":
            path.rename(tmp_path / "export-copy.pdf")
    assert not r.grade_task("pdf_export", tmp_path)[0]


def test_recovery_cannot_pass_by_changing_permissions(tmp_path):
    r = reliability
    r.setup_task("blocked_destination", tmp_path, open_apps=False)
    try:
        complete("blocked_destination", tmp_path)
        (tmp_path / "protected").chmod(0o755)
        assert not r.grade_task("blocked_destination", tmp_path)[0]
    finally:
        r.cleanup_task("blocked_destination", tmp_path)
    assert (tmp_path / "protected").stat().st_mode & 0o777 == 0o755


def test_completion_claims_are_reviewed_independently(tmp_path):
    assert reliability.completion_review(tmp_path, False)["false_completion"] is None
    (tmp_path / "claim_review.json").write_text('{"claimed_success": true}')
    assert reliability.completion_review(tmp_path, False)["false_completion"] is True
    assert reliability.completion_review(tmp_path, True)["false_completion"] is False
    (tmp_path / "claim_review.json").write_text('{"claimed_success": false}')
    assert reliability.completion_review(tmp_path, False)["false_completion"] is False
    (tmp_path / "claim_review.json").write_text('{"claimed_success": "yes"}')
    with pytest.raises(ValueError, match="boolean"):
        reliability.completion_review(tmp_path, False)


def test_task_categories_explicitly_identify_sanity_checks():
    tasks = json.loads((Path(__file__).parents[1] / "evals/desktop/tasks.json").read_text())
    assert len({t["id"] for t in tasks}) == len(tasks)
    new = {t["id"]: t for t in tasks if "fixture" in t and t["category"] != "final"}
    assert set(new) == set(TASKS)
    assert new["exact_save"]["category"] == "sanity"
    assert all(new[t]["category"] == "challenge" for t in TASKS if t != "exact_save")
