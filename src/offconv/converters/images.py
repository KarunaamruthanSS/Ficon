"""Image conversion with Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from offconv import safety
from offconv.registry import ConversionError, Options, converter

# HEIC (iPhone photos) needs the optional pillow-heif package.
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC = ["heic"]
    HEIC_PILLOW_NAMES = ["HEIF"]
except ImportError:  # the tool still works, just without HEIC
    HEIC = []
    HEIC_PILLOW_NAMES = []

READ = ["jpg", "png", "webp", "bmp", "tiff", "gif", "ico", *HEIC]
WRITE = ["jpg", "png", "webp", "bmp", "tiff", "gif", "ico", "pdf"]

# What Pillow calls each format.
PILLOW_NAME = {
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
    "gif": "GIF",
    "ico": "ICO",
    "pdf": "PDF",
}

# Pillow picks a decoder by trying its plugins in turn, and it ships with
# plugins for formats this tool does not claim to read. Naming the ones we
# do read keeps a hostile file from being handed to an unrelated decoder.
READABLE_PILLOW_NAMES = [
    "JPEG", "PNG", "WEBP", "BMP", "TIFF", "GIF", "ICO", *HEIC_PILLOW_NAMES,
]

# Formats that cannot store transparency.
NO_ALPHA = {"jpg", "bmp", "pdf"}

# Formats that hold more than one frame. Converting into anything else
# keeps the first frame only, which the user is told about.
ANIMATED = {"gif", "webp", "tiff", "heic"}

# An ICO holds square entries, and the format caps each one at 256 pixels.
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

def _flatten(img: Image.Image) -> Image.Image:
    """Put a transparent image on a white background."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def _too_big(exc: Exception) -> str:
    """Pillow's refusal, with the way round it the user needs to know."""
    return f"image is implausibly large ({exc}); pass --max-pixels to allow it"


def _open_checked(src: Path, options: Options) -> Image.Image:
    """Open an image, refusing anything outside the agreed limits.

    The header is parsed first and the pixel count checked against the
    budget before `load()` is allowed to allocate the pixel data.
    """
    try:
        img = Image.open(src, formats=READABLE_PILLOW_NAMES)
    except UnidentifiedImageError as exc:
        raise ConversionError("not a readable image") from exc
    except Image.DecompressionBombError as exc:
        raise ConversionError(_too_big(exc)) from exc
    except (OSError, ValueError) as exc:
        raise ConversionError(f"cannot read image: {exc}") from exc

    budget = options.max_pixels or safety.DEFAULT_MAX_PIXELS
    safety.check_pixel_budget(img.size, budget)

    try:
        img.load()
    except Image.DecompressionBombError as exc:
        # Pillow's own backstop, for sub-images we cannot measure from
        # the outside: icon entries, the pages of a multi-page TIFF.
        raise ConversionError(_too_big(exc)) from exc
    except UnidentifiedImageError as exc:
        raise ConversionError("not a readable image") from exc
    except (OSError, ValueError, SyntaxError) as exc:
        raise ConversionError(f"image is damaged or truncated: {exc}") from exc
    return img


def _metadata(img: Image.Image, options: Options) -> bytes | None:
    """The EXIF block to write, or None to write none.

    EXIF carries the GPS position, the camera serial number and the
    owner's name. A converted image is usually one about to be sent
    somewhere, so none of it is copied unless --keep-metadata asks.
    """
    if not options.keep_metadata:
        return None
    exif = img.getexif()
    if not exif:
        return None
    return exif.tobytes()


def _note(options: Options, message: str) -> None:
    """Record something the user should know about this conversion.

    `extra` belongs to one file's conversion, not to the batch; see
    cli.convert_one, which gives every file its own copy.
    """
    options.extra.setdefault("notes", []).append(message)


@converter(READ, WRITE)
def convert_image(src: Path, dst: Path, options: Options) -> None:
    target = dst.suffix.lower().lstrip(".")
    if target not in PILLOW_NAME:
        raise ConversionError(f"no image writer for {target or 'that format'}")

    opened = _open_checked(src, options)
    frames = getattr(opened, "n_frames", 1)
    if frames > 1 and target not in ANIMATED:
        _note(options, f"kept frame 1 of {frames}; {target} holds a single image")
    exif = _metadata(opened, options)

    # Phone photos store rotation as a tag; apply it so the result is upright.
    img = ImageOps.exif_transpose(opened) or opened

    if options.resize:
        img.thumbnail(options.resize, Image.Resampling.LANCZOS)

    if target in NO_ALPHA:
        img = _flatten(img)
    elif target == "gif":
        img = img.convert("P", palette=Image.Palette.ADAPTIVE)
    elif img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

    save_args: dict = {}
    if target in ("jpg", "webp"):
        save_args["quality"] = options.quality
    if target in ("jpg", "png"):
        save_args["optimize"] = True
    if target == "ico":
        img = img.convert("RGBA")
        # Entries are square, so the shorter side decides which of the
        # standard sizes fit without inventing detail that is not there.
        shortest = min(img.size)
        save_args["sizes"] = [s for s in ICO_SIZES if s[0] <= shortest] or [ICO_SIZES[0]]
    if target == "pdf":
        save_args["resolution"] = 150.0
    if exif is not None and target in ("jpg", "webp", "png", "tiff"):
        save_args["exif"] = exif

    try:
        img.save(dst, PILLOW_NAME[target], **save_args)
    except (OSError, ValueError) as exc:
        raise ConversionError(f"could not write {target}: {exc}") from exc
    finally:
        opened.close()
