import zipfile
from pathlib import Path

from offconv.detect import detect, normalise


def test_detects_by_content_not_extension(png: Path):
    wrong = png.with_name("really_a_png.jpg")
    png.rename(wrong)
    assert detect(wrong) == "png"


def test_aliases():
    assert normalise(".JPEG") == "jpg"
    assert normalise("tif") == "tiff"


def test_text_starting_with_bm_is_not_a_bitmap(tmp_path: Path):
    """A two-byte magic alone would send this into an image decoder."""
    path = tmp_path / "notes.txt"
    path.write_bytes(b"BM is my initials, and this is a plain text file.")
    assert detect(path) == "txt"


def test_short_ico_magic_alone_is_not_an_icon(tmp_path: Path):
    path = tmp_path / "thing.bin"
    path.write_bytes(b"\x00\x00\x01\x00\x00\x00" + b"junk" * 8)
    assert detect(path) == "bin"


def test_real_bitmap_is_detected(tmp_path: Path):
    from PIL import Image

    path = tmp_path / "pic.bmp"
    Image.new("RGB", (8, 8)).save(path)
    assert detect(path) == "bmp"


def test_pdf_header_may_sit_a_little_way_in(tmp_path: Path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"\r\n   %PDF-1.7\nrest of the file")
    assert detect(path) == "pdf"


def test_implausible_extension_gives_no_answer(tmp_path: Path):
    path = tmp_path / "data.this-is-not-an-extension"
    path.write_bytes(b"no signature here")
    assert detect(path) == ""


def test_docx_is_found_by_what_is_inside_the_zip(tmp_path: Path):
    path = tmp_path / "report.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    assert detect(path) == "docx"


def test_a_zip_that_is_not_a_document_gives_no_answer(tmp_path: Path):
    """Falling back to the extension here would hand a .docx parser a zip."""
    path = tmp_path / "pretend.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("holiday.jpg", "not really")
    assert detect(path) == ""


def test_a_spreadsheet_is_not_mistaken_for_a_document(tmp_path: Path):
    path = tmp_path / "sums.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    assert detect(path) == ""


def test_legacy_doc_is_named_rather_than_guessed(tmp_path: Path):
    """offconv cannot convert it, so it should say so in those terms."""
    path = tmp_path / "old.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
    assert detect(path) == "doc"


def test_a_renamed_text_file_falls_back_to_its_extension(tmp_path: Path):
    """There is no signature to go on, so the name is the only evidence.

    The converter then refuses it as unreadable, which is the right
    answer arrived at one step later.
    """
    path = tmp_path / "notes.docx"
    path.write_bytes(b"I renamed a text file and hoped for the best.")
    assert detect(path) == "docx"
