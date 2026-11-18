# Ficon

An offline file converter. Files are converted on your own computer and
nothing is uploaded.

The command, the Python package and the built program are all called
`offconv`, so the name you type is not the name of the repository.

This is phase 2: images, and documents to and from PDF.

## What works now

| From | To |
| --- | --- |
| JPG, PNG, WEBP, BMP, TIFF, GIF, ICO, HEIC | JPG, PNG, WEBP, BMP, TIFF, GIF, ICO, PDF |
| PDF | DOCX, TXT |
| DOCX | PDF, TXT |
| TXT | PDF |

Conversions chain, so anything that reaches PDF also reaches DOCX and
TXT: `offconv convert photo.heic --to docx` goes HEIC to PNG to PDF to
DOCX by itself. Run `offconv formats` for the full table on your
machine, which depends on which extras you installed.

- File type is detected from the file's content, not its extension.
- Many files are converted at once; one bad file does not stop the rest.
- Existing files are never overwritten unless you pass `--overwrite`.
- Phone photos come out the right way up, and transparent images get a
  white background when the target cannot store transparency.
- EXIF is dropped, so a converted photo does not carry the GPS position
  of where it was taken. Pass `--keep-metadata` to keep it.
- Files are treated as untrusted input, because a converter mostly reads
  files someone else made. See [SECURITY.md](SECURITY.md).
- DOCX to PDF uses LibreOffice when it is installed, and falls back to
  drawing the page itself when it is not. Which one ran is printed with
  the result, because only the first is a faithful copy.

## Get it

```
git clone https://github.com/KarunaamruthanSS/Ficon.git
cd Ficon
pip install -e ".[heic,docs]"
```

Needs Python 3.10 or later. Both extras are optional and independent:
`heic` adds iPhone photos, `docs` adds PDF, DOCX and TXT. Leave either
out and everything else still works — `offconv formats` only ever offers
what is actually installed.

The `docs` extra is big, around 300MB, because PyMuPDF and pdf2docx
bring OpenCV and, on PyMuPDF 2.x, ML layout models that offconv does not
use. For a smaller install, add `pip install "pymupdf<2"` afterwards.

For a faithful DOCX to PDF conversion, install
[LibreOffice](https://www.libreoffice.org/) as well; offconv finds it on
PATH, or in the usual place on Windows and macOS. Without it, DOCX to
PDF still works, reflowed rather than reproduced.

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
offconv convert report.pdf --to docx
offconv convert contract.docx --to pdf
offconv convert *.pdf --to txt --out extracted
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
| `--max-pages N` | allow documents with more pages than the default limit |
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
- **"the libraries for it are not installed"** — the file was recognised,
  but the optional extra that converts it is missing. Install it with
  `pip install -e ".[heic,docs]"`.
- **"already jpg"** — the file is in that format already. Detection goes
  by content, so a PNG misnamed `.jpg` really is a PNG.
- **"over the N page limit"** — the PDF declares more pages than the
  default budget. Pass `--max-pages` with a larger number.
- **"it may be a zip bomb"** — a .docx is a zip, and this one claims to
  expand to far more than it contains. Nothing was unpacked.
- **"PDF is password protected"** — offconv does not ask for passwords.
  Remove the protection in a PDF reader first.
- **"cannot convert doc to pdf"** — that is the pre-2007 Word format,
  which is a different thing entirely from .docx. Open it in Word or
  LibreOffice and save it as .docx first.

### A note on sizes

Converting a JPG to PNG usually makes the file several times larger. PNG
is lossless, so it faithfully preserves the compression artefacts the JPG
already has and gains nothing. For a smaller file, convert to WEBP or
stay with JPG; use PNG when you need lossless or transparency.

## Develop it

```
pip install -e ".[heic,docs,dev]"
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
(`.github/workflows/build.yml`) lints, type-checks and tests the code on
Windows, Linux and macOS across Python 3.10 to 3.13, then builds both the
Windows .exe and the Linux file and makes each one convert a file. That
happens on every push to `main` and every pull request. Push a tag such
as `v1.1.0` and both binaries are attached to a release with SHA-256
checksums and a build provenance attestation.

Letting CI build is also the better test: a runner has no Python, Pillow
or PyMuPDF installed, so a binary that forgot to bundle something fails
there and might pass on your own machine. That is why the built file is
made to convert a document and not just print its help — the document
libraries are the ones most likely to be left out of a bundle.

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
        documents.py  PDF, DOCX and TXT, with the two DOCX-to-PDF engines
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
- PDF output from an image is one image per file; merging and splitting
  are still to come.
- The result is always named after the original. There is no way yet to
  choose the output file name.
- Without LibreOffice, DOCX to PDF is a reflow: text, headings, bold and
  italic, bullet lists, tables and inline pictures survive, but columns,
  headers and footers, floating shapes and the original pagination do
  not. The result says which engine ran.
- PDF to DOCX rebuilds paragraphs from where the text sits on the page,
  because a PDF has no paragraphs of its own. Expect to tidy it up.
- A scanned PDF has no text to extract. Converting one to TXT says so
  and produces an empty file; OCR is phase 3.

## Roadmap

1. Foundation and images (done)
2. PDF to and from DOCX and TXT (done); merge and split still to come
3. OCR for scanned pages, English (RapidOCR)
4. GUI with drag and drop (PySide6)
5. Optional engines downloaded on demand: FFmpeg, LibreOffice
6. Linux AppImage

## Licence

AGPL-3.0-or-later. See `LICENSE`.
