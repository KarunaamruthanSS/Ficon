# Changelog

## Unreleased

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
