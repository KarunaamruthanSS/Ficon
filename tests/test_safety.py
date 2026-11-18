"""Tests for the guards that exist because input files are not trusted."""

import os
import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image

from offconv import safety
from offconv.cli import EXIT_FAILURES, EXIT_OK, main
from offconv.converters.images import convert_image
from offconv.registry import ConversionError, Options


def _png_claiming(width: int, height: int) -> bytes:
    """A tiny but valid-looking PNG whose header claims a huge image."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 10))
        + chunk(b"IEND", b"")
    )


def test_a_tiny_file_claiming_a_huge_image_is_refused(tmp_path: Path):
    bomb = tmp_path / "bomb.png"
    bomb.write_bytes(_png_claiming(40_000, 40_000))
    assert bomb.stat().st_size < 1000
    assert main(["convert", str(bomb), "--to", "jpg"]) == EXIT_FAILURES
    assert not bomb.with_suffix(".jpg").exists()


def test_the_budget_is_checked_before_any_pixels_are_read(tmp_path: Path):
    """The refusal comes from the header, so no memory is committed."""
    source = tmp_path / "big.png"
    Image.new("RGB", (2000, 2000)).save(source)
    with pytest.raises(ConversionError, match="pixel limit"):
        convert_image(source, tmp_path / "out.jpg", Options(max_pixels=3_000_000))
    assert not (tmp_path / "out.jpg").exists()


def test_a_large_image_can_be_allowed_on_purpose(tmp_path: Path):
    source = tmp_path / "big.png"
    Image.new("RGB", (2000, 2000)).save(source)
    assert main(["convert", str(source), "--to", "jpg", "--max-pixels", "4000000"]) == EXIT_OK


def test_images_in_pillows_warning_band_are_refused_not_warned(tmp_path: Path, monkeypatch):
    """Pillow only warns between its soft and hard limits; we refuse."""
    monkeypatch.setattr(safety, "DEFAULT_MAX_PIXELS", 3_000_000)
    source = tmp_path / "big.png"
    Image.new("RGB", (2000, 2000)).save(source)
    assert main(["convert", str(source), "--to", "jpg"]) == EXIT_FAILURES


def test_the_budget_moves_pillows_own_limit_too(tmp_path: Path):
    """Otherwise Pillow rejects a scan the user deliberately allowed."""
    assert safety.apply_pixel_budget(500_000_000) == 500_000_000
    assert Image.MAX_IMAGE_PIXELS == 500_000_000


def test_no_budget_given_uses_the_default(tmp_path: Path):
    assert safety.apply_pixel_budget(safety.NO_LIMIT) == safety.DEFAULT_MAX_PIXELS
    assert Image.MAX_IMAGE_PIXELS == safety.DEFAULT_MAX_PIXELS


def test_pillows_hard_limit_still_backs_us_up(tmp_path: Path):
    """The check we make is on the outer size; this covers the rest."""
    source = tmp_path / "big.png"
    Image.new("RGB", (2000, 2000)).save(source)
    Image.MAX_IMAGE_PIXELS = 1000  # as if a sub-image were oversized
    with pytest.raises(ConversionError, match="implausibly large"):
        convert_image(source, tmp_path / "out.jpg", Options(max_pixels=99_000_000))


def test_zero_sized_image_is_refused():
    with pytest.raises(ConversionError, match="empty size"):
        safety.check_pixel_budget((0, 100), 1_000_000)


def test_no_limit_allows_anything():
    safety.check_pixel_budget((100_000, 100_000), safety.NO_LIMIT)


def test_only_the_formats_we_claim_to_read_are_decoded(tmp_path: Path):
    """Pillow would happily try every plugin it ships with."""
    source = tmp_path / "picture.ppm"
    Image.new("RGB", (5, 5)).save(source)
    with pytest.raises(ConversionError, match="not a readable image"):
        convert_image(source, tmp_path / "out.jpg", Options())


def test_metadata_is_dropped_by_default(geotagged_jpg: Path):
    assert main(["convert", str(geotagged_jpg), "--to", "webp"]) == EXIT_OK
    result = Image.open(geotagged_jpg.with_suffix(".webp"))
    assert dict(result.getexif()) == {}


def test_metadata_is_kept_when_asked(geotagged_jpg: Path):
    assert main(["convert", str(geotagged_jpg), "--to", "webp", "--keep-metadata"]) == EXIT_OK
    result = Image.open(geotagged_jpg.with_suffix(".webp"))
    assert dict(result.getexif()).get(0x010F) == "ACME"


def test_a_link_as_destination_is_refused(tmp_path: Path, png: Path):
    """Following it would let --overwrite write anywhere on the disk."""
    secret = tmp_path / "secret.txt"
    secret.write_text("original content")
    link = png.with_suffix(".jpg")
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks needs privileges this host does not grant")
    assert main(["convert", str(png), "--to", "jpg", "--overwrite"]) == EXIT_FAILURES
    assert secret.read_text() == "original content"


def test_refuse_link_passes_a_plain_path(tmp_path: Path):
    safety.refuse_link(tmp_path / "does-not-exist.jpg")
    plain = tmp_path / "plain.jpg"
    plain.write_bytes(b"x")
    safety.refuse_link(plain)


def test_a_second_name_for_the_file_is_refused(tmp_path: Path):
    """A hardlinked destination is the same vector as a symlink."""
    target = tmp_path / "target.jpg"
    target.write_bytes(b"x")
    other = tmp_path / "other.jpg"
    try:
        os.link(target, other)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("hardlinks are not available here")
    with pytest.raises(ConversionError, match="more than one name"):
        safety.refuse_link(target)


def test_overwrite_refuses_a_destination_with_a_second_name(tmp_path: Path, png: Path):
    """End to end: --overwrite must not reach through a link."""
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"original content")
    try:
        os.link(secret, png.with_suffix(".jpg"))
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("hardlinks are not available here")
    assert main(["convert", str(png), "--to", "jpg", "--overwrite"]) == EXIT_FAILURES
    assert secret.read_bytes() == b"original content"


def test_truncated_image_is_a_clean_failure(tmp_path: Path):
    source = tmp_path / "cut.png"
    whole = tmp_path / "whole.png"
    Image.new("RGB", (50, 50)).save(whole)
    source.write_bytes(whole.read_bytes()[: len(whole.read_bytes()) // 2])
    with pytest.raises(ConversionError):
        convert_image(source, tmp_path / "out.jpg", Options())
