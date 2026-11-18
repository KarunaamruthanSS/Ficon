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
