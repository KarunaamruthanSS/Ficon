# Security

## Reporting a problem

Report a vulnerability privately through GitHub's **Security → Report a
vulnerability** form on this repository. Please do not open a public
issue for something exploitable. A first reply should take no more than
a few days.

## What this program is exposed to

offconv exists to parse files its user did not create: a download, an
email attachment, a photo from someone else's phone. Those files are
treated as hostile input. The decoders themselves (Pillow, and libheif
through pillow-heif) are the largest part of the attack surface, which is
why the dependency floor is a current version and why Dependabot watches
it.

## The guards that are in place

| Guard | Where | What it stops |
| --- | --- | --- |
| Pixel budget checked from the file header, before decoding | `safety.check_pixel_budget` | A small file that claims a huge image, exhausting memory. Pillow alone only warns in part of that range. |
| Pillow's own limits moved to match the budget | `safety.apply_pixel_budget` | Sub-images we cannot measure from outside: icon entries, TIFF pages. |
| Decoder allowlist | `images.READABLE_PILLOW_NAMES` | A hostile file reaching a Pillow plugin for a format this tool never claimed to read. |
| Strict content signatures, with the declared header length checked | `detect` | A text file or unrelated binary being sent to an image decoder on a two-byte guess. |
| Output names claimed with `O_CREAT|O_EXCL` | `cli._claim_name` | Destroying a file that appeared between the check and the write, including from a parallel worker. |
| Link destinations refused | `safety.refuse_link` | `--overwrite` writing through a symlink or hardlink to a file elsewhere on the disk. |
| Conversion done in a temporary folder, published with one `os.replace` | `cli.convert_one` | A half-written file being left where the user will mistake it for a result. |
| Worker count capped | `cli.MAX_JOBS` | `--jobs 100000` turning the pixel budget into a hundred thousand times the memory. |
| EXIF dropped unless `--keep-metadata` | `images._metadata` | GPS position, camera serial and owner name travelling with a file about to be shared. |

## Limits worth knowing

- A decoder bug is still a decoder bug. These guards bound the damage a
  malformed file can do to memory and to the filesystem; they do not make
  Pillow memory-safe. Keep the dependencies current.
- offconv does not sandbox the decoders. Converting something you have
  real reason to distrust is better done in a container or a VM.
- Released binaries are built in CI and carry a SHA-256 checksum and a
  build provenance attestation. Verify them with
  `gh attestation verify offconv.exe --repo KarunaamruthanSS/Ficon`.
- The Windows build is unsigned, so SmartScreen will warn about it. That
  is expected, and it also means a download cannot be told apart from a
  tampered copy by signature alone — use the checksum.
