"""Work out what a file really is.

File extensions lie (a .jpg that is really a PNG is common), so the first
bytes of the file are checked against known signatures. The extension is
only used when the content gives no answer.

Signatures are matched strictly. A two-byte guess such as "starts with BM
so it must be a bitmap" sends text files and unrelated binaries into an
image decoder, which is both a wrong answer and a needless parse of
untrusted data, so the declared length inside the header is checked too.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

# Enough for every signature below, plus the slack the PDF spec allows
# before the header.
HEAD_BYTES = 1024

# Different spellings of the same format.
ALIASES = {
    "jpeg": "jpg",
    "jpe": "jpg",
    "tif": "tiff",
    "heif": "heic",
    "htm": "html",
    "text": "txt",
}

# An extension is only a fallback hint, and it ends up in error messages,
# so anything that is not a plain short word is ignored.
_PLAUSIBLE_EXTENSION = re.compile(r"\A[a-z0-9]{1,8}\Z")

_HEIC_BRANDS = frozenset(
    {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"}
)

# A .docx is a zip, and so are .xlsx, .pptx, .odt, .jar and a plain
# archive. The member that settles it is named here.
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OOXML_MARKERS = {"word/document.xml": "docx"}

# Legacy .doc, .xls and .ppt share one OLE2 container header. offconv
# cannot convert them, but naming the format gives a straight answer
# instead of a parser error from deep inside a library.
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def normalise(name: str) -> str:
    """Turn '.JPEG' or 'Jpeg' into 'jpg'."""
    name = name.lower().lstrip(".")
    return ALIASES.get(name, name)


def _is_bmp(head: bytes) -> bool:
    """BMP has only a two-byte magic, so check the rest of the header."""
    if not head.startswith(b"BM") or len(head) < 18:
        return False
    declared_size = int.from_bytes(head[2:6], "little")
    header_size = int.from_bytes(head[14:18], "little")
    # 12, 40, 52, 56, 64, 108 and 124 are the defined DIB header sizes.
    return declared_size >= 26 and header_size in (12, 40, 52, 56, 64, 108, 124)


def _is_ico(head: bytes) -> bool:
    if len(head) < 6 or head[:4] != b"\x00\x00\x01\x00":
        return False
    return int.from_bytes(head[4:6], "little") > 0  # image count


def _from_content(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if _is_ico(head):
        return "ico"
    if _is_bmp(head):
        return "bmp"
    if head[4:8] == b"ftyp" and head[8:12] in _HEIC_BRANDS:
        return "heic"
    # The PDF header is allowed to sit a little way into the file, and
    # real-world PDFs make use of that.
    if b"%PDF-" in head[:HEAD_BYTES]:
        return "pdf"
    if head.startswith(_OLE2_MAGIC):
        return "doc"
    return None


def _from_zip(path: Path) -> str | None:
    """Name the OOXML document inside a zip, if that is what this is.

    Only the central directory is read: the member names are enough to
    tell a Word document from a spreadsheet or an ordinary archive, and
    nothing has to be decompressed to find out. A zip that is not a
    document we handle returns None, so it is reported as unrecognised
    rather than handed to a document parser.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return None
    for marker, format_name in _OOXML_MARKERS.items():
        if marker in names:
            return format_name
    return None


def detect(path: Path) -> str:
    """Return the format of `path` as a short lowercase name.

    An empty string means "no idea", which the caller reports rather than
    passing on to a decoder.
    """
    with open(path, "rb") as f:
        head = f.read(HEAD_BYTES)
    found = _from_content(head)
    if found:
        return found
    if head.startswith(_ZIP_MAGIC):
        found = _from_zip(path)
        if found:
            return found
        # A zip we do not recognise is not a document. Saying so beats
        # falling back to a .docx extension that the content denies.
        return ""
    extension = normalise(path.suffix)
    return extension if _PLAUSIBLE_EXTENSION.match(extension) else ""
