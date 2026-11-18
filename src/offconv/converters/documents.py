"""Document conversion: PDF, DOCX and plain text.

Every library here is optional, in the same way pillow-heif is optional
for images: if it is missing, the conversions that need it are simply not
registered, and `offconv formats` stops offering them. The tool still
runs. `pip install -e ".[docs]"` brings them all in.

DOCX to PDF has two engines, because there is no good single answer:

* LibreOffice, when `soffice` is on PATH, lays the document out with the
  same engine Word users are looking at. Pagination, columns, headers and
  floating shapes all come out right.
* Otherwise the document is read with python-docx and redrawn with
  reportlab. That carries the text, headings, lists, tables and images,
  and reflows everything into a plain single-column page.

The second is a readable approximation, not a replica, so the user is
told on stderr which engine produced their file.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import warnings
import xml.sax.saxutils as saxutils
from pathlib import Path

from offconv import safety
from offconv.registry import ConversionError, ConvertFn, Options, converter

# PDF reading and page counting.
try:
    import pymupdf

    PYMUPDF = True
except ImportError:  # pragma: no cover - exercised by the missing-dep path
    PYMUPDF = False

# PyMuPDF's old name warns the moment it is imported, and pdf2docx still
# imports it that way. The filter is left in place rather than scoped to
# the import below, because in a PyInstaller build the module is pulled in
# by the bundle's own startup, outside any context manager of ours. It is
# matched on the message so that nothing else is silenced with it.
warnings.filterwarnings(
    "ignore",
    message=r".*`?fitz`? API is deprecated.*",
    category=FutureWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r".*`?fitz`? API is deprecated.*",
    category=DeprecationWarning,
)


# PDF to DOCX, which rebuilds the layout rather than dumping the text.
class _DropPdf2Docx(logging.Filter):
    """Keep pdf2docx's running commentary out of offconv's output.

    pdf2docx calls logging.basicConfig() on import and then logs its
    progress through the root logger with logging.info(), so there is no
    named logger to quieten. Filtering by the module the record came
    from drops exactly those messages and leaves every other log, the
    host application's included, alone.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "pdf2docx" not in record.pathname.replace("\\", "/").lower()


try:
    # pdf2docx imports PyMuPDF under its old `fitz` name, which warns on
    # import. offconv says what happened itself, so neither that warning
    # nor pdf2docx's progress log is passed on to the user.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        warnings.simplefilter("ignore", DeprecationWarning)
        from pdf2docx import Converter as Pdf2DocxConverter

    logging.getLogger().addFilter(_DropPdf2Docx())
    PDF2DOCX = True
except ImportError:  # pragma: no cover
    PDF2DOCX = False

# Reading and writing Word documents.
try:
    import docx
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    PYTHON_DOCX = True
except ImportError:  # pragma: no cover
    PYTHON_DOCX = False

# Drawing a PDF when LibreOffice is not there to do it properly.
try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image as RlImage,
    )
    from reportlab.platypus import (
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    REPORTLAB = True
except ImportError:  # pragma: no cover
    REPORTLAB = False


# How long LibreOffice is given before it is assumed to have hung. A
# large document on a slow disk can genuinely take a while; a soffice
# that is waiting on something will never finish.
SOFFICE_TIMEOUT = 180

# Where the text of a page ends and the next begins, in a .txt result.
PAGE_SEPARATOR = "\n\n"

# Plain text is read whole into memory, so it gets a ceiling of its own.
MAX_TEXT_BYTES = 64 * 1024 * 1024

# Tried in order when a text file is not valid UTF-8. latin-1 cannot
# fail, so it is the backstop that guarantees an answer.
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def _note(options: Options, message: str) -> None:
    """Record something the user should know about this conversion.

    `extra` belongs to one file's conversion, not to the batch; see
    cli.convert_one, which gives every file its own copy.
    """
    options.extra.setdefault("notes", []).append(message)


def _page_budget(options: Options) -> int:
    return options.max_pages or safety.DEFAULT_MAX_PAGES


def _read_text(src: Path) -> str:
    """Read a text file, guessing the encoding, refusing a huge one."""
    try:
        size = src.stat().st_size
    except OSError as exc:
        raise ConversionError(f"cannot read text file: {exc}") from exc
    if size > MAX_TEXT_BYTES:
        raise ConversionError(
            f"text file is {size:,} bytes, over the {MAX_TEXT_BYTES:,} byte limit"
        )
    try:
        raw = src.read_bytes()
    except OSError as exc:
        raise ConversionError(f"cannot read text file: {exc}") from exc
    for encoding in TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    # Unreachable: latin-1 decodes any byte sequence. Here for the day
    # someone shortens TEXT_ENCODINGS.
    raise ConversionError("cannot work out the text encoding")


def _write_text(dst: Path, text: str) -> None:
    try:
        dst.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise ConversionError(f"could not write text: {exc}") from exc


def _open_pdf(src: Path, options: Options):
    """Open a PDF and refuse one with more pages than the budget allows.

    The page count comes from the document's index, so this happens
    before any page is parsed or rendered.
    """
    try:
        document = pymupdf.open(src)
    except Exception as exc:  # pymupdf raises several unrelated types
        raise ConversionError(f"not a readable PDF: {exc}") from exc
    if document.needs_pass:
        document.close()
        raise ConversionError("PDF is password protected")
    try:
        safety.check_page_budget(document.page_count, _page_budget(options))
    except ConversionError:
        document.close()
        raise
    return document


# --------------------------------------------------------------------------
# PDF out


def pdf_to_txt(src: Path, dst: Path, options: Options) -> None:
    document = _open_pdf(src, options)
    try:
        pages = []
        for page in document:
            try:
                pages.append(page.get_text())
            except Exception as exc:
                raise ConversionError(f"PDF page {page.number + 1} is damaged: {exc}") from exc
        text = PAGE_SEPARATOR.join(pages)
        if not text.strip():
            _note(
                options,
                "no text layer in this PDF; it is probably a scan, and OCR "
                "is not in this version",
            )
    finally:
        document.close()
    _write_text(dst, text)


def pdf_to_docx(src: Path, dst: Path, options: Options) -> None:
    # Opened and closed only to apply the page budget and the password
    # check before pdf2docx starts its own parse.
    _open_pdf(src, options).close()

    converter_obj = Pdf2DocxConverter(str(src))
    try:
        converter_obj.convert(str(dst))
    except Exception as exc:
        raise ConversionError(f"could not rebuild this PDF as a document: {exc}") from exc
    finally:
        converter_obj.close()
    _note(
        options,
        "a PDF has no paragraphs or styles of its own, so the layout was "
        "rebuilt from the position of the text; expect to tidy it up",
    )


# --------------------------------------------------------------------------
# DOCX in


def _soffice() -> str | None:
    """Find LibreOffice, or None if it is not installed.

    PATH first, then the places the Windows and macOS installers put it,
    since neither adds itself to PATH.
    """
    for name in ("soffice", "soffice.exe"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "LibreOffice/program/soffice.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "LibreOffice/program/soffice.exe",
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _soffice_to_pdf(soffice: str, src: Path, dst: Path) -> None:
    """Convert with LibreOffice in a scratch directory.

    Three things matter here:

    * The source is copied in under a fixed, plain name. soffice reads a
      leading dash as an option, and a user's file name is not ours to
      trust on that.
    * -env:UserInstallation points at a throwaway profile, so this never
      shares state with the user's own LibreOffice, and a second copy
      already running does not make this one refuse to start.
    * The output goes to the scratch directory and is moved afterwards,
      because --outdir names a folder and derives the file name itself.
    """
    with tempfile.TemporaryDirectory(prefix=".offconv-soffice-") as scratch:
        work = Path(scratch)
        staged = work / f"source{src.suffix.lower() or '.docx'}"
        try:
            shutil.copyfile(src, staged)
        except OSError as exc:
            raise ConversionError(f"cannot stage document: {exc}") from exc

        profile = (work / "profile").as_uri()
        command = [
            soffice,
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--invisible",
            f"-env:UserInstallation={profile}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(work),
            str(staged),
        ]
        try:
            finished = subprocess.run(  # noqa: S603 - fixed argv, no shell
                command,
                capture_output=True,
                text=True,
                timeout=SOFFICE_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConversionError(
                f"LibreOffice did not finish within {SOFFICE_TIMEOUT} seconds"
            ) from exc
        except OSError as exc:
            raise ConversionError(f"could not run LibreOffice: {exc}") from exc

        produced = staged.with_suffix(".pdf")
        if finished.returncode != 0 or not produced.is_file():
            detail = (finished.stderr or finished.stdout or "").strip().splitlines()
            reason = detail[-1] if detail else f"exit code {finished.returncode}"
            raise ConversionError(f"LibreOffice could not convert this document: {reason}")
        try:
            shutil.move(str(produced), str(dst))
        except OSError as exc:
            raise ConversionError(f"could not save the PDF: {exc}") from exc


def _styles() -> dict:
    """Paragraph styles for the drawn-by-hand PDF."""
    sheet = getSampleStyleSheet()
    body = ParagraphStyle(
        "OffconvBody",
        parent=sheet["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        spaceAfter=6,
        alignment=TA_LEFT,
    )
    styles = {"body": body}
    for level in range(1, 7):
        styles[f"heading{level}"] = ParagraphStyle(
            f"OffconvHeading{level}",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=max(16 - (level - 1) * 1.5, 11),
            leading=max(20 - (level - 1) * 1.5, 14),
            spaceBefore=10,
            spaceAfter=5,
        )
    styles["mono"] = ParagraphStyle(
        "OffconvMono", parent=body, fontName="Courier", fontSize=9, leading=12
    )
    return styles


def _runs_to_markup(paragraph) -> str:
    """Turn a paragraph's runs into reportlab's little markup dialect.

    Bold, italic and underline survive; font and colour do not. Text is
    XML-escaped first, because a document that contains "a < b" would
    otherwise be read as a broken tag and lose the rest of the line.
    """
    pieces = []
    for run in paragraph.runs:
        text = saxutils.escape(run.text or "")
        if not text:
            continue
        if run.bold:
            text = f"<b>{text}</b>"
        if run.italic:
            text = f"<i>{text}</i>"
        if run.underline:
            text = f"<u>{text}</u>"
        pieces.append(text)
    return "".join(pieces) or saxutils.escape(paragraph.text or "")


def _heading_level(paragraph) -> int:
    """Which heading a paragraph is, or 0 for ordinary text."""
    name = (paragraph.style.name or "").lower()
    if name.startswith("heading"):
        tail = name.replace("heading", "").strip()
        if tail.isdigit():
            return min(int(tail), 6)
        return 1
    if name in ("title", "subtitle"):
        return 1
    return 0


def _is_list(paragraph) -> bool:
    name = (paragraph.style.name or "").lower()
    return "list" in name or name.startswith(("list bullet", "list number"))


def _table_flowable(table, styles: dict):
    """One docx table as a reportlab table, cells reflowed as paragraphs."""
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            text = "<br/>".join(
                _runs_to_markup(para) for para in cell.paragraphs if para.text.strip()
            )
            cells.append(Paragraph(text or "&nbsp;", styles["body"]))
        rows.append(cells)
    if not rows:
        return None
    flowable = Table(rows, hAlign="LEFT")
    flowable.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return flowable


def _images(paragraph, document, scratch: Path, counter: list[int]) -> list:
    """Any pictures anchored in this paragraph, as reportlab flowables.

    The image bytes are written to the scratch directory because
    reportlab wants something it can open by name, and sized to fit the
    text column rather than at their natural pixel size.
    """
    flowables = []
    for blip in paragraph._element.findall(".//{*}blip"):
        embed = blip.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
        )
        if not embed:
            continue
        try:
            part = document.part.related_parts[embed]
            blob = part.blob
        except (KeyError, AttributeError):
            continue
        counter[0] += 1
        name = scratch / f"image{counter[0]}{Path(str(part.partname)).suffix or '.png'}"
        try:
            name.write_bytes(blob)
            picture = RlImage(str(name))
        except Exception:  # noqa: S112 - nothing to log to; see below
            # A picture offconv cannot read is not a reason to lose the
            # rest of the document.
            continue
        usable = A4[0] - 40 * mm
        if picture.imageWidth > usable:
            scale = usable / picture.imageWidth
            picture.drawWidth = usable
            picture.drawHeight = picture.imageHeight * scale
        flowables.extend([Spacer(1, 4), picture, Spacer(1, 6)])
    return flowables


def _blocks(document):
    """Paragraphs and tables of the body, in the order they appear.

    python-docx exposes the two as separate lists, which loses their
    relative order; the body's own XML children keep it.
    """
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            yield DocxParagraph(child, document)
        elif tag == "tbl":
            yield DocxTable(child, document)


def _docx_to_pdf_reportlab(src: Path, dst: Path, options: Options) -> None:
    """Redraw a Word document as a plain single-column PDF."""
    try:
        document = docx.Document(str(src))
    except Exception as exc:
        raise ConversionError(f"not a readable Word document: {exc}") from exc

    styles = _styles()
    story: list = []
    pending_list: list = []
    counter = [0]

    with tempfile.TemporaryDirectory(prefix=".offconv-docx-") as scratch:
        work = Path(scratch)

        def flush_list() -> None:
            # list(...) because ListFlowable keeps the list it is handed,
            # and pending_list is cleared for the next run of bullets.
            if pending_list:
                story.append(
                    ListFlowable(list(pending_list), bulletType="bullet", leftIndent=18)
                )
                story.append(Spacer(1, 4))
                pending_list.clear()

        for block in _blocks(document):
            if isinstance(block, DocxTable):
                flush_list()
                flowable = _table_flowable(block, styles)
                if flowable is not None:
                    story.extend([Spacer(1, 6), flowable, Spacer(1, 8)])
                continue

            markup = _runs_to_markup(block)
            pictures = _images(block, document, work, counter)

            if "\f" in (block.text or ""):
                flush_list()
                story.append(PageBreak())

            if _is_list(block) and markup:
                pending_list.append(ListItem(Paragraph(markup, styles["body"])))
                continue

            flush_list()
            level = _heading_level(block)
            if markup:
                style = styles[f"heading{level}"] if level else styles["body"]
                story.append(Paragraph(markup, style))
            story.extend(pictures)

        flush_list()
        if not story:
            story.append(Paragraph("(this document has no content)", styles["body"]))

        frame = SimpleDocTemplate(
            str(dst),
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            title=src.stem,
            author="",
        )
        try:
            frame.build(story)
        except Exception as exc:
            raise ConversionError(f"could not draw the PDF: {exc}") from exc

    _note(
        options,
        "drawn without LibreOffice, so the text, headings, lists, tables "
        "and pictures are kept but the page layout is reflowed; install "
        "LibreOffice for a faithful copy",
    )


def docx_to_pdf(src: Path, dst: Path, options: Options) -> None:
    safety.check_zip_bomb(src)
    soffice = _soffice()
    if soffice:
        _soffice_to_pdf(soffice, src, dst)
        _note(options, "converted with LibreOffice")
        return
    if not (PYTHON_DOCX and REPORTLAB):
        raise ConversionError(
            "docx to pdf needs either LibreOffice on PATH or "
            'pip install -e ".[docs]"'
        )
    _docx_to_pdf_reportlab(src, dst, options)


def docx_to_txt(src: Path, dst: Path, options: Options) -> None:
    """Pull the words out of a Word document.

    Direct rather than through PDF: the paragraphs are already there to
    be read, and routing it through a renderer would need LibreOffice
    and lose the structure on the way.
    """
    safety.check_zip_bomb(src)
    try:
        document = docx.Document(str(src))
    except Exception as exc:
        raise ConversionError(f"not a readable Word document: {exc}") from exc

    lines: list[str] = []
    for block in _blocks(document):
        if isinstance(block, DocxTable):
            for row in block.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                lines.append("\t".join(cells))
            lines.append("")
        else:
            lines.append(block.text or "")
    _write_text(dst, "\n".join(lines).rstrip("\n") + "\n")


def txt_to_pdf(src: Path, dst: Path, options: Options) -> None:
    """Set a text file as a PDF, in a monospaced font.

    Monospaced because a text file that is worth converting is usually
    one where the spacing means something: a table, a listing, a log.
    """
    text = _read_text(src)
    styles = _styles()
    story: list = []
    for block in text.replace("\r\n", "\n").replace("\r", "\n").split("\f"):
        if story:
            story.append(PageBreak())
        for line in block.split("\n"):
            if line.strip():
                # Leading spaces carry the indentation, and reportlab
                # collapses them unless they are non-breaking.
                stripped = line.lstrip(" ")
                indent = "&nbsp;" * (len(line) - len(stripped))
                story.append(Paragraph(indent + saxutils.escape(stripped), styles["mono"]))
            else:
                story.append(Spacer(1, 8))
    if not story:
        story.append(Paragraph("(this file is empty)", styles["mono"]))

    frame = SimpleDocTemplate(
        str(dst),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=src.stem,
    )
    try:
        frame.build(story)
    except Exception as exc:
        raise ConversionError(f"could not draw the PDF: {exc}") from exc


# --------------------------------------------------------------------------
# Registration
#
# Done by hand rather than with @converter, because which conversions
# exist depends on which optional libraries are installed.

READ: list[str] = []
WRITE: list[str] = []


def _register() -> None:
    """Register what the installed libraries can actually do."""
    pairs: list[tuple[str, str, ConvertFn]] = []

    if PYMUPDF:
        pairs.append(("pdf", "txt", pdf_to_txt))
        if PDF2DOCX:
            pairs.append(("pdf", "docx", pdf_to_docx))
    if PYTHON_DOCX:
        pairs.append(("docx", "txt", docx_to_txt))
    # LibreOffice is looked for at conversion time, not here: it may be
    # installed after offconv, and either engine satisfies this pair.
    if (PYTHON_DOCX and REPORTLAB) or _soffice():
        pairs.append(("docx", "pdf", docx_to_pdf))
    if REPORTLAB:
        pairs.append(("txt", "pdf", txt_to_pdf))

    for source, target, function in pairs:
        converter([source], [target])(function)
        if source not in READ:
            READ.append(source)
        if target not in WRITE:
            WRITE.append(target)


_register()
