"""Guards for untrusted input files.

A converter is, by nature, a program that parses files it did not create.
Two things follow from that, and this module holds both:

* A small file can describe an enormous image. A 68-byte PNG can claim
  40000x40000 pixels; decoding it allocates gigabytes. The size is
  therefore checked against a budget straight from the header, before any
  pixel data is read, and going over it is a refusal rather than the
  warning Pillow would print and then carry on past.
* The destination path comes from the user. Writing through a symlink
  would let a converted image land anywhere on the disk, so destinations
  that are links are refused rather than followed.

Documents bring two more of the same shape:

* A .docx is a zip, and a zip can describe far more than it contains. A
  few hundred kilobytes can expand to gigabytes, so the central
  directory is read and the claimed sizes are added up before anything
  is extracted.
* A PDF can declare thousands of pages. Page count is checked against a
  budget before any page is rendered or parsed.
"""

from __future__ import annotations

import os
import warnings
import zipfile
from pathlib import Path

from PIL import Image

from offconv.registry import ConversionError

# Pillow's own soft limit, used as the default budget. Any single real
# photograph is far below it; see --max-pixels to raise it.
DEFAULT_MAX_PIXELS = Image.MAX_IMAGE_PIXELS or 89_478_485

NO_LIMIT = 0

# Budgets for documents. Both are generous for anything a person made on
# purpose, and far below what a file built to exhaust memory asks for.
DEFAULT_MAX_PAGES = 5_000

# A zip that expands to more than this, or by more than this ratio, is
# treated as a bomb rather than a document.
MAX_UNPACKED_BYTES = 1_024 * 1_024 * 1_024  # 1 GiB
MAX_COMPRESSION_RATIO = 200
MAX_ZIP_MEMBERS = 10_000


def apply_pixel_budget(max_pixels: int) -> int:
    """Settle on a pixel budget and line Pillow's own limits up with it.

    Pillow keeps two limits of its own: a soft one that warns and carries
    on, and a hard one at twice that which raises. Both are set from the
    budget here, so that

    * the hard limit still backs us up on images we cannot measure from
      the outside, such as the separate entries in an icon or the pages
      of a multi-page TIFF, and
    * a scan the user deliberately allowed with --max-pixels is not then
      rejected by Pillow's unrelated default.

    The soft warning is silenced because it has been replaced by a
    refusal at the same threshold: without this the user would be told
    twice, once as a warning and once as the actual error.
    """
    budget = DEFAULT_MAX_PIXELS if max_pixels == NO_LIMIT else max_pixels
    Image.MAX_IMAGE_PIXELS = budget
    # Re-asserted on every call rather than once, because a test runner or
    # a host application may have reset the warning filters in between.
    warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)
    return budget


def check_pixel_budget(size: tuple[int, int], max_pixels: int) -> None:
    """Refuse an image whose header claims more pixels than allowed.

    `size` comes from the parsed header, so this runs before the pixel
    data is allocated.
    """
    if max_pixels == NO_LIMIT:
        return
    width, height = size
    if width <= 0 or height <= 0:
        raise ConversionError("image reports an empty size")
    pixels = width * height
    if pixels > max_pixels:
        raise ConversionError(
            f"image is {width}x{height} ({pixels:,} pixels), over the "
            f"{max_pixels:,} pixel limit; pass --max-pixels to allow it"
        )


def refuse_link(path: Path) -> None:
    """Refuse a destination that is a symlink, hardlink or junction.

    Writing to it would modify whatever it points at, somewhere else on
    the disk, which is not what `--overwrite` is meant to permit.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ConversionError(f"cannot inspect destination: {exc}") from exc
    if os.path.islink(path):
        raise ConversionError("destination is a link; refusing to write through it")
    if getattr(info, "st_nlink", 1) > 1:
        raise ConversionError(
            "destination has more than one name on disk; refusing to overwrite it"
        )


def check_page_budget(pages: int, max_pages: int) -> None:
    """Refuse a document that declares more pages than allowed.

    Read from the page index, so this runs before any page is rendered.
    """
    if max_pages == NO_LIMIT:
        return
    if pages < 0:
        raise ConversionError("document reports a negative page count")
    if pages > max_pages:
        raise ConversionError(
            f"document has {pages:,} pages, over the {max_pages:,} page "
            "limit; pass --max-pages to allow it"
        )


def check_zip_bomb(path: Path) -> None:
    """Refuse a zip-backed document that would expand unreasonably.

    Only the central directory is read. The sizes there are the file's
    own claims, which is exactly what is wanted: a bomb is refused on
    the strength of what it asks for, before a single member is
    decompressed and the claim could come true.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ConversionError(f"not a readable document: {exc}") from exc
    except OSError as exc:
        raise ConversionError(f"cannot read document: {exc}") from exc

    if len(members) > MAX_ZIP_MEMBERS:
        raise ConversionError(
            f"document holds {len(members):,} parts, over the "
            f"{MAX_ZIP_MEMBERS:,} part limit"
        )

    unpacked = sum(member.file_size for member in members)
    if unpacked > MAX_UNPACKED_BYTES:
        raise ConversionError(
            f"document expands to {unpacked:,} bytes, over the "
            f"{MAX_UNPACKED_BYTES:,} byte limit"
        )

    packed = sum(member.compress_size for member in members)
    # A tiny archive cannot do damage whatever its ratio, and the ratio
    # is meaningless when there is almost nothing to divide by.
    if packed > 1024 and unpacked > packed * MAX_COMPRESSION_RATIO:
        raise ConversionError(
            f"document expands {unpacked // max(packed, 1)} times over, "
            f"past the {MAX_COMPRESSION_RATIO}x limit; it may be a zip bomb"
        )
