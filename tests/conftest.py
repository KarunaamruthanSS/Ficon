"""Shared fixtures.

The converter registry is global, so every test runs inside a snapshot of
it. Without that, a test that registers a made-up format leaves it in the
table and the next test sees it in `offconv formats`.
"""

from pathlib import Path

import pytest
from PIL import Image

from offconv import registry


@pytest.fixture(autouse=True)
def clean_registry():
    with registry.isolated():
        yield


@pytest.fixture(autouse=True)
def restore_pillow_limit():
    """Pillow's pixel limit is global, and --max-pixels moves it."""
    saved = Image.MAX_IMAGE_PIXELS
    try:
        yield
    finally:
        Image.MAX_IMAGE_PIXELS = saved


@pytest.fixture
def png(tmp_path: Path) -> Path:
    """A small half-transparent PNG."""
    path = tmp_path / "sample.png"
    Image.new("RGBA", (120, 80), (200, 30, 30, 128)).save(path)
    return path


@pytest.fixture
def animated_gif(tmp_path: Path) -> Path:
    path = tmp_path / "moving.gif"
    frames = [
        Image.new("RGB", (20, 20), colour).convert("P")
        for colour in ((255, 0, 0), (0, 255, 0), (0, 0, 255))
    ]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    return path


@pytest.fixture
def geotagged_jpg(tmp_path: Path) -> Path:
    """A JPEG carrying the kind of EXIF a phone camera writes."""
    path = tmp_path / "holiday.jpg"
    image = Image.new("RGB", (60, 40), (10, 20, 30))
    exif = image.getexif()
    exif[0x010F] = "ACME"  # Make
    exif[0x8825] = {}  # GPS IFD
    image.save(path, exif=exif)
    return path
