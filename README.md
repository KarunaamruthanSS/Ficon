<<<<<<< HEAD
# Ficon
=======
# File-Convertor
>>>>>>> b0a3f74e7585ecff3f3dd3323b9242d7d02e75be

An offline file converter. Files are converted on your own computer and
nothing is uploaded.

The command, the Python package and the built program are all called
<<<<<<< HEAD
`offconv`, so the name you type is not the name of the repository.
=======
`offconv`, which is shorter to type than the repository name.
>>>>>>> b0a3f74e7585ecff3f3dd3323b9242d7d02e75be

This is phase 1: the foundation and image conversion.

## What works now

| From | To |
| --- | --- |
| JPG, PNG, WEBP, BMP, TIFF, GIF, ICO, HEIC | JPG, PNG, WEBP, BMP, TIFF, GIF, ICO, PDF |

- File type is detected from the file's content, not its extension.
- Many files are converted at once; one bad file does not stop the rest.
- Existing files are never overwritten unless you pass `--overwrite`.
- Phone photos come out the right way up, and transparent images get a
  white background when the target cannot store transparency.
- EXIF is dropped, so a converted photo does not carry the GPS position
  of where it was taken. Pass `--keep-metadata` to keep it.
- Files are treated as untrusted input, because a converter mostly reads
  files someone else made. See [SECURITY.md](SECURITY.md).

## Get it

```
<<<<<<< HEAD
git clone https://github.com/KarunaamruthanSS/Ficon.git
cd Ficon
=======
git clone https://github.com/KarunaamruthanSS/File-Convertor.git
cd File-Convertor
>>>>>>> b0a3f74e7585ecff3f3dd3323b9242d7d02e75be
pip install -e ".[heic]"
```

Needs Python 3.10 or later. The `heic` extra adds iPhone photos; leave it
out and everything else still works.

If `offconv` is then "not recognized", pip's scripts folder is not on
your PATH. Either add it, or use the form that never depends on PATH:

```
python -m offconv formats
```

## Use it

```
offconv convert photo.png --to jpg
offconv convert *.png holiday/ --to webp --quality 80 --out converted
offconv convert scan.jpg --to pdf
offconv convert big.jpg --to jpg --resize 1920x1080
offconv formats
```

`--to` takes a **format**, not a file name: `--to png`, not
`--to photo.png`. Use `--out` to choose where results go. The result is
named after the original, so `holiday.jpg --to png` gives `holiday.png`.

| Option | What it does |
| --- | --- |
| `--to FORMAT` | the format to convert to (required) |
| `--out FOLDER` | where results go (default: next to each original) |
| `--quality 1-100` | JPG and WEBP quality (default 90) |
| `--resize WxH` | fit inside those bounds, keeping proportions |
| `--overwrite` | replace existing files instead of numbering the result |
| `--jobs N` | files converted at once (default 4, most 32) |
| `--max-pixels N` | allow images bigger than the default limit |
| `--keep-metadata` | copy EXIF, including GPS, into the result |
| `--quiet` | print only failures |

Exit codes: `0` all converted, `1` at least one file failed, `2` the
command itself was wrong.

### On Windows, in PowerShell

PowerShell does not run programs from the folder you are standing in, so
a bare `offconv.exe` gives "not recognized" even when the file is right
there. Put a path on it:

```
cd C:\path\to\dist
.\offconv.exe convert photo.png --to jpg
```

### Double-clicking the .exe

This is a command line tool, so there is nothing for a double-click to
show. Windows gives a clicked program a console window of its own and
closes it the instant the program exits, which used to mean a flash too
quick to read. It now prints what to do and waits for a key instead, but
the real way to use it is from a terminal you already have open.

### Why a file might be refused

- **"over the N pixel limit"** — the image claims more pixels than the
  default budget allows. A small file can describe an enormous image, and
  decoding it would use all the memory on the machine, so the size is
  checked from the header before anything is decoded. A real scan can be
  that big legitimately: pass `--max-pixels` with a larger number.
- **"destination is a link"** — `--overwrite` would have written through
  a symlink to a file somewhere else. Convert to a different name or use
  `--out`.
- **"unrecognised file type"** — neither the content nor the extension
  identified the file.
- **"already jpg"** — the file is in that format already. Detection goes
  by content, so a PNG misnamed `.jpg` really is a PNG.

### A note on sizes

Converting a JPG to PNG usually makes the file several times larger. PNG
is lossless, so it faithfully preserves the compression artefacts the JPG
already has and gains nothing. For a smaller file, convert to WEBP or
stay with JPG; use PNG when you need lossless or transparency.

## Develop it

```
pip install -e ".[heic,dev]"
pytest
ruff check .
mypy
```

## Build the single .exe

On Windows, run `build_exe.bat` from the project folder (in PowerShell,
`.\build_exe.bat`). The result is `dist\offconv.exe`: one file, no Python
needed on the PC that runs it. On Linux, run `./build.sh` to get
`dist/offconv`.

A Windows .exe can only be built on Windows. The included workflow
(`.github/workflows/build.yml`) lints, type-checks and tests the code,
builds both the Windows .exe and the Linux file, and runs each one, on
every push. Push a tag such as `v0.1.0` and both are attached to a
release with SHA-256 checksums and a build provenance attestation.

Letting CI build is also the better test: a runner has no Python or
Pillow installed, so a binary that forgot to bundle something fails
there and might pass on your own machine.

The build is unsigned, so Windows will warn about it, and a machine with
Smart App Control turned on will refuse to run it at all. That is
expected for a new program; a code-signing certificate is what removes
both.

## How it is organised

```
src/offconv/
    cli.py            command line, batch handling, output naming
    registry.py       table of converters, options, chaining between them
    detect.py         file type detection from the first bytes
    safety.py         limits and path guards for untrusted input
    converters/
        images.py     Pillow-based image conversion
tests/                pytest suite
run.py                entry point for the .exe build
```

## Add a new format

Write a function, decorate it, and import the module in
`converters/__init__.py`. Nothing else changes:

```python
from offconv.registry import converter

@converter(["pdf"], ["txt"])
def pdf_to_txt(src, dst, options):
    ...
```

The function is given the source path, a destination path in a temporary
folder, and the user's options. Raise `ConversionError` with a message
worth showing for anything the user could act on; any other exception is
caught and reported for that one file without stopping the batch. Write
only to the destination path you were given — the result is moved into
place once, after the whole chain has succeeded.

If two converters can be chained (HEIC to PNG, PNG to PDF), the tool
finds the route by itself.

### Known limitations

- Animation is not carried across. Converting a multi-frame GIF or TIFF
  keeps the first frame, and says so on stderr.
- PDF output is one image per file; merging comes with phase 2.
- The result is always named after the original. There is no way yet to
  choose the output file name.

## Roadmap

1. Foundation and images (done)
2. PDF: to DOCX, TXT and images; merge and split (PyMuPDF, pdf2docx)
3. OCR for scanned pages, English (RapidOCR)
4. GUI with drag and drop (PySide6)
5. Optional engines downloaded on demand: FFmpeg, LibreOffice
6. Linux AppImage

## Licence

AGPL-3.0-or-later. See `LICENSE`.
