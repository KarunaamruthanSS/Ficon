"""Command line interface.

    offconv convert photo.png --to jpg
    offconv convert *.png holiday/ --to webp --quality 80 --out converted
    offconv convert report.pdf --to docx
    offconv formats
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from offconv import __version__, converters, registry, safety  # noqa: F401
from offconv.detect import detect, normalise
from offconv.registry import QUALITY_RANGE, ConversionError, Options

# Each worker may hold a whole decoded image in memory, so the number of
# them is capped rather than taken on trust from --jobs.
MAX_JOBS = 32

# How many "name (n).ext" variants to try before giving up.
MAX_NAME_ATTEMPTS = 10_000

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_USAGE = 2
EXIT_CANCELLED = 130


def _expand(inputs: list[str]) -> list[Path]:
    """Turn the arguments into a list of files.

    Windows does not expand *.png itself, so wildcards are handled here.
    A folder means every file directly inside it. Duplicates are dropped:
    naming a file twice, or naming both a file and the folder holding it,
    should not convert it twice into two differently numbered results.
    """
    files: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        # Compared as text, not resolved: resolve() follows links and
        # touches the disk for every argument, and the point here is only
        # to drop arguments the user repeated.
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            files.append(path)

    for item in inputs:
        matches = [Path(m) for m in glob.glob(item, recursive=True)] or [Path(item)]
        for path in matches:
            if path.is_dir():
                for child in sorted(path.iterdir()):
                    if child.is_file():
                        add(child)
            else:
                add(path)
    return files


def _claim_name(path: Path) -> Path:
    """Reserve a free output name by creating the file, and return it.

    Checking exists() and writing afterwards is two steps, and anything
    may create the file in between: another worker in this batch, another
    copy of offconv, or another program. Creating the file with O_EXCL is
    one step that either wins the name or fails, so a file that was not
    there when we looked cannot be destroyed a moment later.
    """
    for n in range(MAX_NAME_ATTEMPTS):
        candidate = path if n == 0 else path.with_name(f"{path.stem} ({n}){path.suffix}")
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        except OSError as exc:
            raise ConversionError(f"cannot write to {candidate.parent}: {exc}") from exc
        os.close(fd)
        return candidate
    raise ConversionError(f"too many files named like {path.name}")


def _publish(result: Path, dst: Path) -> None:
    """Move a finished conversion into place in one step.

    The temporary folder sits beside the destination, so this is a rename
    within one filesystem: either the finished file is there or the old
    one still is, never half of either. The fallback covers the case
    where that folder could not be used and the two ended up on
    different filesystems, where a rename cannot work.
    """
    try:
        os.replace(result, dst)
    except OSError:
        try:
            shutil.move(str(result), str(dst))
        except OSError as exc:
            raise ConversionError(f"cannot save {dst}: {exc}") from exc


def _scratch_parent(folder: Path) -> Path | None:
    """Where to put the working folder: beside the output if we can."""
    return folder if os.access(folder, os.W_OK) else None


def convert_one(
    src: Path,
    target: str,
    out_dir: Path | None,
    options: Options,
    overwrite: bool,
) -> tuple[Path, list[str]]:
    """Convert one file; return the result path and any notes about it."""
    if not src.is_file():
        raise ConversionError("not a regular file")
    try:
        source = detect(src)
    except OSError as exc:
        raise ConversionError(f"cannot read: {exc}") from exc
    if not source:
        raise ConversionError("unrecognised file type")
    if source == target:
        raise ConversionError(f"already {target}")
    route = registry.find_route(source, target)
    if route is None:
        reachable = registry.targets_for(source)
        if reachable:
            raise ConversionError(
                f"cannot convert {source} to {target} (can do: {', '.join(reachable)})"
            )
        # Nothing at all leads out of this format. Usually that is because
        # the optional libraries for it are not installed, which is worth
        # saying: "nothing yet" on its own reads like a missing feature.
        raise ConversionError(
            f"cannot convert {source} to anything; if offconv should handle "
            f"{source}, the libraries for it are not installed "
            '(pip install -e ".[heic,docs]")'
        )

    folder = out_dir or src.parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConversionError(f"cannot use output folder {folder}: {exc}") from exc

    # Notes belong to this file, so this file gets its own copy of the
    # options; the shared one is read by every worker at the same time.
    local = replace(options, extra={})

    # The whole conversion happens in a temporary folder, and only a
    # finished file is moved out. A failure part way through leaves
    # nothing behind for the user to mistake for a result. The folder is
    # made beside the destination so that moving the result into place is
    # a rename within one filesystem, which cannot half-happen.
    with tempfile.TemporaryDirectory(prefix=".offconv-", dir=_scratch_parent(folder)) as tmp:
        current = src
        for i, (a, b) in enumerate(route):
            step_out = Path(tmp) / f"step{i}.{b}"
            try:
                registry.get(a, b)(current, step_out, local)
            except ConversionError:
                raise
            except Exception as exc:  # one bad file must not stop the batch
                raise ConversionError(str(exc) or type(exc).__name__) from exc
            current = step_out

        dst = folder / f"{src.stem}.{target}"
        if overwrite:
            safety.refuse_link(dst)
            _publish(current, dst)
        else:
            dst = _claim_name(dst)
            try:
                _publish(current, dst)
            except ConversionError:
                # Take the reserved name back; an empty file left sitting
                # there looks like a result that simply came out blank.
                dst.unlink(missing_ok=True)
                raise

    return dst, local.extra.get("notes", [])


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def _jobs(text: str) -> int:
    return min(_positive(text), MAX_JOBS)


def _quality(text: str) -> int:
    low, high = QUALITY_RANGE
    value = _positive(text)
    if not low <= value <= high:
        raise argparse.ArgumentTypeError(f"quality must be from {low} to {high}")
    return value


def _pixels(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 (no limit) or more")
    return value


def _format_name(text: str) -> str:
    """Read --to as a format, and say so when it looks like a file name.

    "--to photo.png" is an easy thing to type when you mean "give me a
    png", and the old message echoed it back as though it were a format
    nobody had heard of.
    """
    # A leading dot is just how people write an extension (".png"); a dot
    # anywhere else, or a path separator, means a file name.
    bare = text.strip().lstrip(".")
    if "." in bare or "/" in bare or "\\" in bare:
        guess = normalise(Path(text.strip()).suffix)
        hint = f"; did you mean --to {guess}?" if guess else ""
        raise argparse.ArgumentTypeError(
            "--to takes a format, such as jpg or png, not a file name"
            f"{hint} Use --out to choose the folder results go in."
        )
    name = normalise(text)
    if not name:
        raise argparse.ArgumentTypeError("--to needs a format, such as jpg")
    return name


def _parse_resize(text: str) -> tuple[int, int]:
    parts = text.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("use WIDTHxHEIGHT, for example 1920x1080")
    try:
        width, height = (int(part) for part in parts)
    except ValueError:
        raise argparse.ArgumentTypeError("use WIDTHxHEIGHT, for example 1920x1080") from None
    if width < 1 or height < 1:
        raise argparse.ArgumentTypeError("width and height must be 1 or more")
    return width, height


def cmd_convert(args: argparse.Namespace) -> int:
    target = args.to
    files = _expand(args.files)
    if not files:
        print("No files to convert.", file=sys.stderr)
        return EXIT_USAGE

    try:
        options = Options(
            quality=args.quality,
            resize=args.resize,
            max_pixels=args.max_pixels,
            max_pages=args.max_pages,
            keep_metadata=args.keep_metadata,
        )
    except ValueError as exc:
        print(f"offconv: {exc}", file=sys.stderr)
        return EXIT_USAGE

    # Set once here, before any worker starts, because Pillow's limit is
    # a global and this is the last single-threaded moment.
    options.max_pixels = safety.apply_pixel_budget(options.max_pixels)
    out_dir = Path(args.out) if args.out else None

    def work(src: Path):
        try:
            dst, notes = convert_one(src, target, out_dir, options, args.overwrite)
            return src, dst, notes, None
        except ConversionError as exc:
            return src, None, [], str(exc)

    failed = 0
    with ThreadPoolExecutor(max_workers=min(args.jobs, len(files))) as pool:
        for src, dst, notes, error in pool.map(work, files):
            if error:
                failed += 1
                print(f"FAIL  {src}: {error}", file=sys.stderr)
            else:
                if not args.quiet:
                    print(f"ok    {src} -> {dst}")
                for note in notes:
                    print(f"      note: {note}", file=sys.stderr)

    done = len(files) - failed
    if not args.quiet:
        print(f"\n{done} converted, {failed} failed.")
    return EXIT_FAILURES if failed else EXIT_OK


def cmd_formats(args: argparse.Namespace) -> int:
    for src in registry.sources():
        print(f"{src:6} -> {', '.join(registry.targets_for(src))}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="offconv", description="Convert files offline. Nothing is uploaded."
    )
    parser.add_argument("--version", action="version", version=f"offconv {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    conv = sub.add_parser("convert", help="convert one or more files")
    conv.add_argument("files", nargs="+", help="files, folders or wildcards like *.png")
    conv.add_argument(
        "--to", required=True, type=_format_name, help="target format, for example jpg"
    )
    conv.add_argument("--out", help="folder for the results (default: next to each original)")
    conv.add_argument(
        "--quality", type=_quality, default=90, help="JPG/WEBP quality 1-100 (default 90)"
    )
    conv.add_argument(
        "--resize", type=_parse_resize, help="fit inside WIDTHxHEIGHT, keeping proportions"
    )
    conv.add_argument("--overwrite", action="store_true", help="replace existing files")
    conv.add_argument(
        "--jobs",
        type=_jobs,
        default=4,
        help=f"files converted at once (default 4, most {MAX_JOBS})",
    )
    conv.add_argument(
        "--max-pixels",
        type=_pixels,
        default=0,
        help=(
            "refuse images bigger than this many pixels (default "
            f"{safety.DEFAULT_MAX_PIXELS:,}; 0 keeps the default, raise it for giant scans)"
        ),
    )
    conv.add_argument(
        "--max-pages",
        type=_pixels,
        default=0,
        help=(
            "refuse documents with more pages than this (default "
            f"{safety.DEFAULT_MAX_PAGES:,}; 0 keeps the default)"
        ),
    )
    conv.add_argument(
        "--keep-metadata",
        action="store_true",
        help="copy EXIF, including GPS position, into the result (dropped by default)",
    )
    conv.add_argument("--quiet", action="store_true", help="only report failures")
    conv.set_defaults(func=cmd_convert)

    fmt = sub.add_parser("formats", help="list supported conversions")
    fmt.set_defaults(func=cmd_formats)
    return parser


def _own_console() -> bool:
    """True when this process is the only thing using its console window.

    Explorer gives a double-clicked program a console of its own and
    destroys it the moment the program exits, so the output flashes past
    unread. Started from a terminal, the shell is attached to the same
    console and the window outlives us, so nothing needs holding open.

    Both tests have to pass: a console with one process, and a real
    terminal on standard input. That keeps this from ever firing under a
    test runner or a redirected pipe, where waiting for a key would hang.
    """
    if sys.platform != "win32":
        return False
    try:
        if not sys.stdin.isatty():
            return False
        import ctypes

        buffer = (ctypes.c_uint * 2)()
        attached = ctypes.windll.kernel32.GetConsoleProcessList(buffer, 2)
    except Exception:  # no console, no ctypes, an unusual host
        return False
    return bool(attached <= 1)


def _hold_window_open() -> None:
    """Keep a double-clicked window up long enough to read."""
    with contextlib.suppress(EOFError, KeyboardInterrupt):
        input("\nPress Enter to close this window . . . ")


def _explain_to_a_double_click() -> int:
    """What to show someone who opened the program by clicking it."""
    print("offconv is a command line tool, so there is nothing to see here.")
    print("Open a terminal in this folder and give it something to do:\n")
    print("    offconv formats")
    print("    offconv convert photo.png --to jpg")
    print("    offconv convert *.heic --to jpg --out converted\n")
    build_parser().print_help()
    return EXIT_USAGE


def _run(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    command: Callable[[argparse.Namespace], int] = args.func
    try:
        return command(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return EXIT_CANCELLED
    except OSError as exc:  # a full disk, a read-only folder, a bad path
        print(f"offconv: {exc}", file=sys.stderr)
        return EXIT_FAILURES


def main(argv: list[str] | None = None) -> int:
    clicked = _own_console() and not (argv if argv is not None else sys.argv[1:])
    if clicked:
        try:
            return _explain_to_a_double_click()
        finally:
            _hold_window_open()
    try:
        return _run(argv)
    finally:
        # Also covers the usage message argparse exits on, which would
        # otherwise be the one thing a clicker never gets to read.
        if _own_console():
            _hold_window_open()


if __name__ == "__main__":
    sys.exit(main())
