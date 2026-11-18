from pathlib import Path

import pytest
from PIL import Image

from offconv import cli
from offconv.cli import EXIT_FAILURES, EXIT_OK, EXIT_USAGE, main
from offconv.detect import detect
from offconv.registry import ConversionError


@pytest.mark.parametrize("target", ["jpg", "webp", "bmp", "tiff", "gif", "ico", "pdf"])
def test_png_to_each_format(png: Path, target: str):
    assert main(["convert", str(png), "--to", target]) == EXIT_OK
    out = png.with_suffix(f".{target}")
    assert out.exists() and out.stat().st_size > 0
    assert detect(out) == target


def test_does_not_overwrite(png: Path):
    main(["convert", str(png), "--to", "jpg"])
    main(["convert", str(png), "--to", "jpg"])
    assert (png.parent / "sample (1).jpg").exists()


def test_overwrite_replaces_the_file(png: Path):
    main(["convert", str(png), "--to", "jpg", "--quality", "95"])
    jpg = png.with_suffix(".jpg")
    before = jpg.read_bytes()
    main(["convert", str(png), "--to", "jpg", "--overwrite", "--quality", "20"])
    assert not (png.parent / "sample (1).jpg").exists()
    assert jpg.read_bytes() != before


def test_resize_keeps_proportions(png: Path):
    main(["convert", str(png), "--to", "jpg", "--resize", "60x60"])
    assert Image.open(png.with_suffix(".jpg")).size == (60, 40)


def test_bad_file_does_not_stop_the_batch(png: Path, tmp_path: Path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    code = main(["convert", str(broken), str(png), "--to", "jpg"])
    assert code == EXIT_FAILURES
    assert png.with_suffix(".jpg").exists()
    assert not broken.with_suffix(".jpg").exists()


def test_a_failed_conversion_leaves_nothing_behind(tmp_path: Path):
    """Not even the empty file used to reserve the output name."""
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    main(["convert", str(broken), "--to", "jpg"])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["broken.png"]


def test_unknown_conversion_is_reported(tmp_path: Path):
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    assert main(["convert", str(text), "--to", "jpg"]) == EXIT_FAILURES


def test_unrecognised_file_is_reported(tmp_path: Path):
    mystery = tmp_path / "blob.weird-extension"
    mystery.write_bytes(b"\x01\x02\x03\x04")
    assert main(["convert", str(mystery), "--to", "jpg"]) == EXIT_FAILURES


def test_same_name_in_one_batch_does_not_collide(png: Path):
    jpg = png.with_suffix(".jpg")
    Image.new("RGB", (10, 10)).save(jpg)
    assert main(["convert", str(png), str(jpg), "--to", "webp"]) == EXIT_OK
    assert png.with_suffix(".webp").exists()
    assert (png.parent / "sample (1).webp").exists()


def test_a_file_named_twice_is_converted_once(png: Path):
    assert main(["convert", str(png), str(png), str(png), "--to", "tiff"]) == EXIT_OK
    assert sorted(p.name for p in png.parent.glob("*.tiff")) == ["sample.tiff"]


def test_a_folder_and_a_file_inside_it_do_not_double_up(png: Path, tmp_path: Path):
    assert main(["convert", str(tmp_path), str(png), "--to", "tiff"]) == EXIT_OK
    assert sorted(p.name for p in tmp_path.glob("*.tiff")) == ["sample.tiff"]


def test_a_wildcard_matching_nothing_is_reported(tmp_path: Path):
    """It falls back to a literal name, which then reports as missing."""
    assert main(["convert", str(tmp_path / "nothing-here-*.png"), "--to", "jpg"]) == EXIT_FAILURES


def test_empty_folder_is_a_usage_error(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["convert", str(empty), "--to", "jpg"]) == EXIT_USAGE


def test_out_folder_is_created(png: Path, tmp_path: Path):
    out = tmp_path / "results" / "nested"
    assert main(["convert", str(png), "--to", "jpg", "--out", str(out)]) == EXIT_OK
    assert (out / "sample.jpg").exists()


def test_claiming_a_name_never_reuses_one(tmp_path: Path):
    """_claim_name creates the file, so a second call cannot win it again."""
    wanted = tmp_path / "result.jpg"
    first = cli._claim_name(wanted)
    second = cli._claim_name(wanted)
    assert first == wanted
    assert second == tmp_path / "result (1).jpg"
    assert first.exists() and second.exists()


def test_a_failed_save_does_not_leave_the_reserved_name(png: Path, monkeypatch):
    """The empty file used to reserve the name has to go back too."""

    def refuse(result, dst):
        raise ConversionError("disk full, say")

    monkeypatch.setattr(cli, "_publish", refuse)
    assert main(["convert", str(png), "--to", "jpg"]) == EXIT_FAILURES
    assert not png.with_suffix(".jpg").exists()
    assert sorted(p.name for p in png.parent.iterdir()) == ["sample.png"]


def test_quiet_reports_only_failures(png: Path, tmp_path: Path, capsys):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\nnope")
    main(["convert", str(png), str(broken), "--to", "jpg", "--quiet"])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "FAIL" in captured.err


def test_frame_loss_is_reported_not_silent(animated_gif: Path, capsys):
    assert main(["convert", str(animated_gif), "--to", "png"]) == EXIT_OK
    assert "kept frame 1 of 3" in capsys.readouterr().err


def test_formats_lists_conversions(capsys):
    assert main(["formats"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "png" in out and "pdf" in out


def test_icon_sizes_come_from_the_shorter_side(tmp_path: Path):
    """A wide, short image must not be blown up to a square icon."""
    source = tmp_path / "wide.png"
    Image.new("RGBA", (400, 20), (0, 0, 255, 255)).save(source)
    assert main(["convert", str(source), "--to", "ico"]) == EXIT_OK
    assert max(Image.open(source.with_suffix(".ico")).size) <= 16
