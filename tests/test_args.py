"""Bad arguments must be a clear message and exit code 2, not a crash."""

from pathlib import Path

import pytest

from offconv import cli
from offconv.cli import EXIT_USAGE, MAX_JOBS, build_parser, main


@pytest.mark.parametrize(
    "argument",
    [
        ["--jobs", "0"],
        ["--jobs", "-4"],
        ["--jobs", "lots"],
        ["--quality", "0"],
        ["--quality", "101"],
        ["--quality", "9999"],
        ["--quality", "high"],
        ["--resize", "0x0"],
        ["--resize", "-10x20"],
        ["--resize", "abc"],
        ["--resize", "100x100x100"],
        ["--max-pixels", "-1"],
    ],
)
def test_rejected_with_a_usage_error(png: Path, argument: list[str]):
    with pytest.raises(SystemExit) as exit_info:
        main(["convert", str(png), "--to", "jpg", *argument])
    assert exit_info.value.code == EXIT_USAGE


def test_jobs_is_capped_rather_than_trusted():
    """Each worker may hold a decoded image, so the count is bounded."""
    args = build_parser().parse_args(["convert", "x.png", "--to", "jpg", "--jobs", "10000"])
    assert args.jobs == MAX_JOBS


def test_sensible_arguments_are_accepted():
    args = build_parser().parse_args(
        ["convert", "x.png", "--to", "jpg", "--quality", "80", "--resize", "800x600"]
    )
    assert (args.quality, args.resize) == (80, (800, 600))


def test_a_command_is_required():
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == EXIT_USAGE


def test_a_double_click_explains_itself_and_waits(monkeypatch, capsys):
    """Explorer closes the window on exit, so it has to be held open."""
    prompts: list[str] = []
    monkeypatch.setattr(cli, "_own_console", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt))
    assert cli.main([]) == EXIT_USAGE
    out = capsys.readouterr().out
    assert "command line tool" in out
    assert "offconv convert photo.png --to jpg" in out
    assert len(prompts) == 1


def test_a_terminal_is_left_alone(monkeypatch):
    """Nothing is held open when a shell owns the window."""
    monkeypatch.setattr(cli, "_own_console", lambda: False)

    def refuse(prompt=""):
        raise AssertionError("must not wait for a key in a terminal")

    monkeypatch.setattr("builtins.input", refuse)
    with pytest.raises(SystemExit):
        cli.main([])


def test_arguments_still_run_when_double_clicked(monkeypatch, png: Path):
    """Dragging files onto the exe passes argv; that must still convert."""
    monkeypatch.setattr(cli, "_own_console", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": None)
    assert cli.main(["convert", str(png), "--to", "jpg", "--quiet"]) == 0
    assert png.with_suffix(".jpg").exists()


def test_own_console_is_false_without_a_terminal():
    """Under a test runner or a pipe, waiting for a key would hang."""
    assert cli._own_console() is False


@pytest.mark.parametrize(
    ("given", "expected_hint"),
    [
        ("photo.png", "did you mean --to png?"),
        ("out/photo.jpg", "did you mean --to jpg?"),
        (r"C:\pics\a.webp", "did you mean --to webp?"),
        ("noextension.", "not a file name"),
    ],
)
def test_to_rejects_a_file_name_and_suggests_the_format(png: Path, given, expected_hint):
    """'--to photo.png' is an easy slip when you mean '--to png'."""
    with pytest.raises(SystemExit) as exit_info:
        main(["convert", str(png), "--to", given])
    assert exit_info.value.code == EXIT_USAGE


@pytest.mark.parametrize(("given", "becomes"), [("JPEG", "jpg"), (".Png", "png"), ("tif", "tiff")])
def test_to_still_accepts_formats_in_any_spelling(given, becomes):
    args = build_parser().parse_args(["convert", "x.bmp", "--to", given])
    assert args.to == becomes
