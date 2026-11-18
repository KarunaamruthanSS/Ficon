"""Tests for PDF, DOCX and plain text conversion.

Every library behind these conversions is optional, so each test skips
rather than fails when the one it needs is not installed. The docx-to-pdf
tests pin the engine explicitly: whether LibreOffice happens to be on the
machine running the tests must not change what they assert.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from offconv import safety
from offconv.converters import documents as docs
from offconv.registry import ConversionError, Options

pymupdf = pytest.importorskip("pymupdf", reason="needs the docs extra")


def _pdf_text(path: Path) -> str:
    with pymupdf.open(path) as document:
        return "\n".join(page.get_text() for page in document)


@pytest.fixture
def options() -> Options:
    return Options()


@pytest.fixture
def docx_path(tmp_path: Path) -> Path:
    """A Word document using each feature the reflow has to carry."""
    docx = pytest.importorskip("docx", reason="needs python-docx")
    document = docx.Document()
    document.add_heading("Quarterly Report", level=1)
    paragraph = document.add_paragraph()
    paragraph.add_run("bold").bold = True
    paragraph.add_run(" plain ")
    paragraph.add_run("italic").italic = True
    # Angle brackets and ampersands are markup to reportlab, so a
    # document containing them is the interesting case.
    document.add_paragraph("a < b & c > d")
    document.add_heading("Findings", level=2)
    document.add_paragraph("first bullet", style="List Bullet")
    document.add_paragraph("second bullet", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "top left"
    table.rows[1].cells[1].text = "bottom right"
    document.add_page_break()
    document.add_paragraph("after the break")
    path = tmp_path / "report.docx"
    document.save(str(path))
    return path


@pytest.fixture
def text_path(tmp_path: Path) -> Path:
    path = tmp_path / "notes.txt"
    path.write_text(
        "first line\n    indented line\n\nafter a blank line\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


@pytest.fixture
def pdf_two_pages(tmp_path: Path) -> Path:
    path = tmp_path / "two.pdf"
    document = pymupdf.open()
    for words in ("page one words", "page two words"):
        page = document.new_page()
        page.insert_text((72, 72), words)
    document.save(str(path))
    document.close()
    return path


@pytest.fixture
def no_soffice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the reportlab engine, whatever is installed on this machine."""
    monkeypatch.setattr(docs, "_soffice", lambda: None)


# --------------------------------------------------------------------------
# PDF to text


def test_pdf_to_txt_keeps_the_words(pdf_two_pages: Path, tmp_path: Path, options: Options):
    out = tmp_path / "out.txt"
    docs.pdf_to_txt(pdf_two_pages, out, options)
    text = out.read_text(encoding="utf-8")
    assert "page one words" in text
    assert "page two words" in text


def test_pdf_with_no_text_layer_says_so(tmp_path: Path, png: Path, options: Options):
    """An image-only PDF is a scan, and silence would look like success."""
    from PIL import Image

    scan = tmp_path / "scan.pdf"
    Image.open(png).convert("RGB").save(scan)

    out = tmp_path / "out.txt"
    docs.pdf_to_txt(scan, out, options)
    assert out.read_text(encoding="utf-8").strip() == ""
    assert any("scan" in note for note in options.extra["notes"])


def test_page_budget_refuses_a_long_pdf(pdf_two_pages: Path, tmp_path: Path):
    options = Options(max_pages=1)
    with pytest.raises(ConversionError, match="over the 1 page limit"):
        docs.pdf_to_txt(pdf_two_pages, tmp_path / "out.txt", options)


def test_page_budget_is_checked_before_pages_are_read(
    pdf_two_pages: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The point of the budget is to refuse before doing the work."""
    monkeypatch.setattr(
        pymupdf.Page, "get_text", lambda *a, **k: pytest.fail("a page was read")
    )
    with pytest.raises(ConversionError):
        docs.pdf_to_txt(pdf_two_pages, tmp_path / "out.txt", Options(max_pages=1))


def test_password_protected_pdf_is_refused(tmp_path: Path, options: Options):
    path = tmp_path / "locked.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "secret")
    document.save(
        str(path),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    document.close()
    with pytest.raises(ConversionError, match="password protected"):
        docs.pdf_to_txt(path, tmp_path / "out.txt", options)


def test_a_file_that_is_not_a_pdf_is_refused(tmp_path: Path, options: Options):
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is not really a PDF at all")
    with pytest.raises(ConversionError):
        docs.pdf_to_txt(path, tmp_path / "out.txt", options)


# --------------------------------------------------------------------------
# PDF to DOCX


def test_pdf_to_docx_keeps_the_words(pdf_two_pages: Path, tmp_path: Path, options: Options):
    pytest.importorskip("pdf2docx", reason="needs pdf2docx")
    docx = pytest.importorskip("docx")

    out = tmp_path / "out.docx"
    docs.pdf_to_docx(pdf_two_pages, out, options)
    assert out.is_file()
    text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
    assert "page one words" in text
    # A rebuilt layout is a guess, and the user is told as much.
    assert any("rebuilt" in note for note in options.extra["notes"])


def test_pdf_to_docx_respects_the_page_budget(pdf_two_pages: Path, tmp_path: Path):
    pytest.importorskip("pdf2docx", reason="needs pdf2docx")
    with pytest.raises(ConversionError, match="page limit"):
        docs.pdf_to_docx(pdf_two_pages, tmp_path / "out.docx", Options(max_pages=1))


# --------------------------------------------------------------------------
# DOCX to PDF, drawn by reportlab


def test_docx_to_pdf_reflow_keeps_the_content(
    docx_path: Path, tmp_path: Path, options: Options, no_soffice: None
):
    pytest.importorskip("reportlab", reason="needs reportlab")
    out = tmp_path / "out.pdf"
    docs.docx_to_pdf(docx_path, out, options)

    text = _pdf_text(out)
    for expected in (
        "Quarterly Report",
        "bold",
        "italic",
        "Findings",
        "first bullet",
        "second bullet",
        "top left",
        "bottom right",
        "after the break",
    ):
        assert expected in text, f"{expected!r} missing from the PDF"


def test_reflow_keeps_every_bullet(
    docx_path: Path, tmp_path: Path, options: Options, no_soffice: None
):
    """A bullet list is built up and flushed; both bullets must survive.

    ListFlowable keeps the list it is handed rather than copying it, so
    clearing that list in place silently emptied the finished flowable.
    """
    pytest.importorskip("reportlab", reason="needs reportlab")
    out = tmp_path / "out.pdf"
    docs.docx_to_pdf(docx_path, out, options)
    text = _pdf_text(out)
    assert "first bullet" in text
    assert "second bullet" in text


def test_reflow_escapes_markup_characters(
    docx_path: Path, tmp_path: Path, options: Options, no_soffice: None
):
    """"a < b" must not be read as the start of a tag and swallow the line."""
    pytest.importorskip("reportlab", reason="needs reportlab")
    out = tmp_path / "out.pdf"
    docs.docx_to_pdf(docx_path, out, options)
    assert "a < b & c > d" in _pdf_text(out)


def test_reflow_says_the_layout_is_approximate(
    docx_path: Path, tmp_path: Path, options: Options, no_soffice: None
):
    pytest.importorskip("reportlab", reason="needs reportlab")
    docs.docx_to_pdf(docx_path, tmp_path / "out.pdf", options)
    assert any("LibreOffice" in note for note in options.extra["notes"])


def test_empty_document_still_produces_a_pdf(
    tmp_path: Path, options: Options, no_soffice: None
):
    docx = pytest.importorskip("docx")
    pytest.importorskip("reportlab")
    path = tmp_path / "empty.docx"
    docx.Document().save(str(path))

    out = tmp_path / "out.pdf"
    docs.docx_to_pdf(path, out, options)
    assert out.is_file() and out.stat().st_size > 0


def test_not_a_word_document_is_refused(tmp_path: Path, options: Options, no_soffice: None):
    pytest.importorskip("reportlab")
    path = tmp_path / "pretend.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("hello.txt", "not a word document")
    with pytest.raises(ConversionError, match="not a readable Word document"):
        docs.docx_to_pdf(path, tmp_path / "out.pdf", options)


# --------------------------------------------------------------------------
# DOCX to PDF, handed to LibreOffice


def _fake_soffice(monkeypatch: pytest.MonkeyPatch, outcome: str):
    """Stand in for soffice, recording the command it was given."""
    seen: dict = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 0))
        if outcome == "ok":
            # soffice names the output itself, from the input's stem.
            source = Path(command[-1])
            source.with_suffix(".pdf").write_bytes(b"%PDF-1.7\nfrom libreoffice\n")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "Error: source file could not be loaded")

    monkeypatch.setattr(docs.subprocess, "run", fake_run)
    monkeypatch.setattr(docs, "_soffice", lambda: "/usr/bin/soffice")
    return seen


def test_libreoffice_is_preferred_when_present(
    docx_path: Path, tmp_path: Path, options: Options, monkeypatch: pytest.MonkeyPatch
):
    seen = _fake_soffice(monkeypatch, "ok")
    out = tmp_path / "out.pdf"
    docs.docx_to_pdf(docx_path, out, options)

    assert out.read_bytes().startswith(b"%PDF")
    assert any(note == "converted with LibreOffice" for note in options.extra["notes"])
    command = seen["command"]
    assert "--headless" in command
    assert "--convert-to" in command and "pdf" in command
    # A throwaway profile, so this never touches the user's own
    # LibreOffice or refuses to start because a copy is already running.
    assert any(part.startswith("-env:UserInstallation=") for part in command)
    assert seen["kwargs"]["timeout"] == docs.SOFFICE_TIMEOUT


def test_the_source_name_is_never_passed_through(
    tmp_path: Path, options: Options, monkeypatch: pytest.MonkeyPatch
):
    """A name soffice would read as an option must not reach it.

    The document is staged under a fixed, plain name instead.
    """
    docx = pytest.importorskip("docx")
    awkward = tmp_path / "--convert-to.docx"
    docx.Document().save(str(awkward))

    seen = _fake_soffice(monkeypatch, "ok")
    docs.docx_to_pdf(awkward, tmp_path / "out.pdf", options)
    assert Path(seen["command"][-1]).name == "source.docx"


def test_libreoffice_failure_is_reported(
    docx_path: Path, tmp_path: Path, options: Options, monkeypatch: pytest.MonkeyPatch
):
    _fake_soffice(monkeypatch, "fail")
    with pytest.raises(ConversionError, match="could not be loaded"):
        docs.docx_to_pdf(docx_path, tmp_path / "out.pdf", options)


def test_libreoffice_hanging_is_not_waited_on_forever(
    docx_path: Path, tmp_path: Path, options: Options, monkeypatch: pytest.MonkeyPatch
):
    _fake_soffice(monkeypatch, "timeout")
    with pytest.raises(ConversionError, match="did not finish within"):
        docs.docx_to_pdf(docx_path, tmp_path / "out.pdf", options)


def test_nothing_is_left_behind_when_libreoffice_fails(
    docx_path: Path, tmp_path: Path, options: Options, monkeypatch: pytest.MonkeyPatch
):
    _fake_soffice(monkeypatch, "fail")
    out = tmp_path / "out.pdf"
    with pytest.raises(ConversionError):
        docs.docx_to_pdf(docx_path, out, options)
    assert not out.exists()


# --------------------------------------------------------------------------
# DOCX to text


def test_docx_to_txt_includes_table_cells(docx_path: Path, tmp_path: Path, options: Options):
    pytest.importorskip("docx")
    out = tmp_path / "out.txt"
    docs.docx_to_txt(docx_path, out, options)
    text = out.read_text(encoding="utf-8")
    assert "Quarterly Report" in text
    assert "top left" in text
    assert "bottom right" in text


# --------------------------------------------------------------------------
# Text in


def test_txt_to_pdf_keeps_the_lines(text_path: Path, tmp_path: Path, options: Options):
    pytest.importorskip("reportlab")
    out = tmp_path / "out.pdf"
    docs.txt_to_pdf(text_path, out, options)
    text = _pdf_text(out)
    assert "first line" in text
    assert "indented line" in text


def test_empty_text_file_still_produces_a_pdf(tmp_path: Path, options: Options):
    pytest.importorskip("reportlab")
    path = tmp_path / "nothing.txt"
    path.write_text("", encoding="utf-8")
    out = tmp_path / "out.pdf"
    docs.txt_to_pdf(path, out, options)
    assert out.is_file() and out.stat().st_size > 0


def test_text_that_is_not_utf8_is_still_read(tmp_path: Path):
    """A Windows-1252 file is common and should not be a failure."""
    path = tmp_path / "legacy.txt"
    path.write_bytes("caf\xe9 na\xefve".encode("cp1252"))
    assert "caf" in docs._read_text(path)


def test_a_huge_text_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(docs, "MAX_TEXT_BYTES", 10)
    path = tmp_path / "big.txt"
    path.write_text("x" * 50, encoding="utf-8")
    with pytest.raises(ConversionError, match="over the 10 byte limit"):
        docs._read_text(path)


# --------------------------------------------------------------------------
# Guards shared with the rest of the tool


def test_a_zip_bomb_is_refused_before_it_is_opened(
    tmp_path: Path, options: Options, monkeypatch: pytest.MonkeyPatch
):
    """The refusal must come from the claim, not from unpacking it."""
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "\x00" * (8 * 1024 * 1024))

    monkeypatch.setattr(safety, "MAX_UNPACKED_BYTES", 1024)
    monkeypatch.setattr(docs, "_soffice", lambda: None)
    with pytest.raises(ConversionError, match="byte limit"):
        docs.docx_to_pdf(path, tmp_path / "out.pdf", options)


def test_docx_to_pdf_is_offered_without_libreoffice():
    """LibreOffice may be installed after offconv was.

    The pair is registered on the strength of the reportlab fallback, and
    which engine runs is decided when a file is actually converted.
    """
    from offconv import registry

    assert registry.find_route("docx", "pdf") == [("docx", "pdf")]


# --------------------------------------------------------------------------
# The budgets themselves


def test_page_budget_allows_an_ordinary_document():
    safety.check_page_budget(12, safety.DEFAULT_MAX_PAGES)


def test_page_budget_refuses_too_many_pages():
    with pytest.raises(ConversionError, match="over the 100 page limit"):
        safety.check_page_budget(101, 100)


def test_page_budget_of_zero_means_no_limit():
    safety.check_page_budget(10_000_000, safety.NO_LIMIT)


def test_a_negative_page_count_is_refused():
    safety.check_page_budget(0, 100)
    with pytest.raises(ConversionError, match="negative page count"):
        safety.check_page_budget(-1, 100)


def _zip_of(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, blob in members.items():
            archive.writestr(name, blob)
    return path


def test_an_ordinary_document_passes_the_zip_check(tmp_path: Path):
    path = _zip_of(tmp_path / "fine.docx", {"word/document.xml": b"<document/>"})
    safety.check_zip_bomb(path)


def test_a_zip_that_expands_too_far_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Refused on the size it claims, before anything is decompressed."""
    path = _zip_of(tmp_path / "bomb.docx", {"word/document.xml": bytes(4 * 1024 * 1024)})
    monkeypatch.setattr(safety, "MAX_UNPACKED_BYTES", 1024)
    with pytest.raises(ConversionError, match="byte limit"):
        safety.check_zip_bomb(path)


def test_an_extreme_compression_ratio_is_refused(tmp_path: Path):
    """16MB of zeroes compresses far past the ratio a document needs."""
    path = _zip_of(tmp_path / "ratio.docx", {"word/document.xml": bytes(16 * 1024 * 1024)})
    with pytest.raises(ConversionError, match="zip bomb"):
        safety.check_zip_bomb(path)


def test_a_zip_with_too_many_parts_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(safety, "MAX_ZIP_MEMBERS", 3)
    path = _zip_of(tmp_path / "many.docx", {f"part{n}.xml": b"x" for n in range(5)})
    with pytest.raises(ConversionError, match="part limit"):
        safety.check_zip_bomb(path)


def test_a_tiny_archive_is_not_called_a_bomb(tmp_path: Path):
    """The ratio is meaningless when there is almost nothing to divide by."""
    path = _zip_of(tmp_path / "small.docx", {"word/document.xml": bytes(4096)})
    safety.check_zip_bomb(path)


def test_a_format_nothing_can_be_done_with_points_at_the_extras(tmp_path: Path):
    """A legacy .doc is recognised but has no converter.

    "can do: nothing yet" on its own reads like a missing feature, when
    the usual cause is an optional library that is not installed.
    """
    from offconv.cli import convert_one

    path = tmp_path / "old.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(64))
    with pytest.raises(ConversionError, match="libraries for it are not installed"):
        convert_one(path, "pdf", None, Options(), overwrite=False)


def test_a_damaged_zip_is_reported_not_crashed(tmp_path: Path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"PK\x03\x04 and then nonsense")
    with pytest.raises(ConversionError, match="not a readable document"):
        safety.check_zip_bomb(path)
