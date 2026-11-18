# Changelog

## 1.1.0

### Added

- PDF to DOCX and DOCX to PDF, the two conversions this version is for,
  plus PDF to TXT, TXT to PDF and DOCX to TXT. Everything chains, so
  `--to docx` works from a photo as well: HEIC to PNG to PDF to DOCX.
- DOCX to PDF picks its engine when it runs. LibreOffice does it when
  `soffice` is on PATH or in the usual place on Windows or macOS, and the
  result is laid out the way Word would. Without it, python-docx and
  reportlab redraw the document: text, headings, bold and italic, bullet
  lists, tables and inline pictures survive, and the page layout is
  reflowed into one column. The result says which engine ran, because
  only the first is a faithful copy.
- A new `docs` extra holds the libraries for all of this. Like `heic`,
  it is optional: without it the conversions are not registered,
  `offconv formats` does not offer them, and the rest of the tool is
  unaffected.
- `--max-pages`, for documents with more pages than the default budget
  of 5,000.
- DOCX is detected by looking inside the zip for `word/document.xml`,
  rather than trusting the extension. A zip that is not a document it
  recognises is reported as unrecognised instead of being handed to a
  document parser, so a renamed .xlsx or .jar cannot get in that way.
- The pre-2007 .doc format is named when it is seen, so the refusal says
  what the file actually is instead of failing somewhere inside a parser.

### Safety

- A .docx is a zip, and a zip can claim to expand to far more than it
  contains. The central directory is read and the claimed sizes added up
  before anything is extracted, and an archive over 1GiB unpacked, over
  200x its packed size, or holding more than 10,000 parts is refused.
- PDFs are refused on their page count, read from the document index
  before any page is parsed or rendered.
- A password-protected PDF is refused rather than being probed.
- Plain text is read whole, so it has a ceiling of its own at 64MB.
- LibreOffice is run with a throwaway user profile, with the document
  staged under a fixed plain name so that a file called `--convert-to`
  cannot be read as an option, and with a timeout, so a soffice that
  hangs does not hang offconv with it.

### Fixed

- Bullet lists came out of DOCX to PDF empty. reportlab's `ListFlowable`
  keeps the list it is handed rather than copying it, so clearing that
  list to start the next group silently emptied the finished one.
- pdf2docx's progress log and PyMuPDF's `fitz` deprecation notice no
  longer appear in offconv's output. pdf2docx logs through the root
  logger, so it is filtered by the module its records come from, which
  leaves a host application's own logging alone.

### Internal

- CI installs the `docs` extra, so the document conversions are actually
  exercised rather than skipped, and each built binary is made to convert
  a file as well as print its help — the document libraries are the ones
  most likely to be missed by a bundle, and `--help` would not notice.
- The Linux single file is built in CI alongside the Windows .exe, which
  the README had been describing for a while before it was true. Both are
  attested and attached to a tagged release.
- The release job publishes with the GitHub CLI instead of a third-party
  action, so the only actions holding `contents: write` are first-party
  ones, and `.github/dependabot.yml` now exists to watch the decoders and
  the actions. Both were described in the 1.0.0 notes below before they
  were configured.

## 1.0.0

### Safety

- Images are now measured from their header and refused if they claim
  more pixels than the budget allows, before any pixel data is read.
  Pillow on its own only warns across part of that range and decodes the
  file anyway, so a 68-byte PNG claiming 40000x40000 could commit
  gigabytes of memory. `--max-pixels` raises the budget for genuinely
  large scans, and moves Pillow's own limits with it.
- Only the formats offconv claims to read are offered to a decoder, so a
  hostile file cannot reach an unrelated Pillow plugin.
- `--overwrite` refuses a destination that is a symlink or has a second
  name on disk, rather than writing through it to a file elsewhere.
- Output names are claimed with an exclusive create instead of an
  `exists()` check followed by a write, so a file that appears in between
  cannot be destroyed.
- EXIF, including GPS position and camera serial number, is dropped
  unless `--keep-metadata` is passed.
- `--jobs` is capped, since each worker may hold a whole decoded image.
- File type detection no longer calls anything starting with `BM` a
  bitmap; the declared header length is checked too.

### Fixed

- A file named twice, or named alongside the folder containing it, was
  converted once per mention and produced `photo.jpg`, `photo (1).jpg`
  and `photo (2).jpg` from a single original.
- `--jobs 0` crashed with a stack trace. `--quality 9999` was accepted
  silently. `--resize 0x0` failed with "division by zero". All bad
  arguments are now a usage message and exit code 2.
- A failed conversion no longer leaves an empty file where the result
  would have gone.
- Converting a multi-frame GIF or TIFF into a single-image format kept
  frame one silently; it now says so.
- Icon sizes are chosen from the shorter side of the image, so a wide,
  short picture is no longer stretched into a square.
- The image file handle is closed even when EXIF rotation replaced the
  image object.
- `--quiet` was documented but did not exist.
- `--to photo.png` reported "cannot convert jpg to photo.png", echoing a
  file name back as though it were an unknown format. It now says `--to`
  takes a format, suggests the one from the extension, and points at
  `--out` for choosing a folder. Spellings like `.PNG`, `JPEG` and `tif`
  are still accepted.
- Double-clicking the .exe opened a console window that closed before
  anything could be read. It now says what the program is, shows the
  help, and waits for a key — but only when Explorer gave it the window,
  so a terminal, a pipe or a test runner is never made to wait.

### Internal

- Route finding walks an adjacency index instead of rescanning every
  registered pair for every node.
- `Options` validates itself, so a GUI or library caller cannot reach a
  converter with nonsense values.
- Per-file conversion notes no longer share one mutable `extra` dict
  across every worker in a batch.
- `registry.isolated()` lets a test register a format without leaving it
  in the global table for every later test.
- Tests split by subject, and raised from 15 to 76.
- Ruff and mypy configured, and run in CI ahead of the build.
- CI is read-only by default; write access is scoped to the tag-triggered
  release job. Releases are published with the GitHub CLI rather than a
  third-party action, carry SHA-256 checksums, and are attested.
- Dependabot watches Pillow and the CI actions.
