"""Stage 1 smoke tests: the grammar parses, exit codes hold, Windows paths survive.

The full tree-conformance test lands in Stage 2; these cover #1's acceptance
items 4 (unimplemented commands exit 1 with a message, not a traceback) and
7 (a Windows absolute path parses on every path-taking command), plus the
exit-code remap from ADR 0002.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from sensor_qaqc.cli.__main__ import (
    EXIT_NO_RESULT,
    EXIT_PRODUCED,
    build_parser,
    main,
)

# One invocation per leaf command, valid arguments throughout.
LEAF_COMMANDS = [
    ["stations", "discover", "--lat", "32.87", "--lon", "-117.25", "--radius-km", "25"],
    ["stations", "diff"],
    ["stations", "diff", "--site", "la-jolla"],
    ["stations", "update"],
    ["stations", "show", "scripps-pier"],
    ["baseline", "build", "--site", "la-jolla", "--from", "2026-06-01", "--to", "2026-07-01"],
    ["baseline", "show", "la-jolla"],
    ["inspect", "export.xlsx"],
    ["run", "12345678-1"],
    ["run", "12345678-1", "--check", "quantisation", "--check", "spectral_slope"],
    ["report", "render", "runs/2026-08-11-12345678-1"],
    ["report", "render", "runs/2026-08-11-12345678-1", "--pdf"],
    # checks list and checks show gained bodies in #2; tests/test_cli_checks.py
    # owns them now. checks docs stays unimplemented until #11.
    ["checks", "docs", "--out", "docs/checks"],
]

HELP_INVOCATIONS = [
    ["--help"],
    ["stations", "--help"],
    ["baseline", "--help"],
    ["report", "--help"],
    ["checks", "--help"],
    ["run", "--help"],
]

USAGE_ERRORS = [
    [],
    ["stations"],
    ["nonexistent"],
    ["stations", "diff", "--bogus"],
    ["stations", "discover", "--lat", "not-a-number", "--lon", "0", "--radius-km", "1"],
    ["baseline", "build", "--site", "la-jolla"],
]

# The prototype's actual Windows bug: a drive letter mistaken for another
# argument. Assert the parsed value round-trips on every path-taking command.
WINDOWS_PATH = r"C:\Users\coled\HOBOware\export.xlsx"
PATH_COMMANDS = [
    (["inspect", WINDOWS_PATH], "file"),
    (["report", "render", WINDOWS_PATH], "run_folder"),
    (["checks", "docs", "--out", WINDOWS_PATH], "out"),
]


@pytest.mark.parametrize("argv", HELP_INVOCATIONS)
def test_help_exits_zero(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == EXIT_PRODUCED


@pytest.mark.parametrize("argv", LEAF_COMMANDS)
def test_unimplemented_command_exits_1_with_message(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == EXIT_NO_RESULT
    stderr = capsys.readouterr().err
    assert "not implemented yet" in stderr
    assert "Traceback" not in stderr


@pytest.mark.parametrize("argv", USAGE_ERRORS)
def test_usage_error_exits_1_not_2(argv: list[str]) -> None:
    # argparse's default is exit 2, which ADR 0002 reserves for a failed
    # assertion (stations diff on drift). A typo must not read as drift.
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == EXIT_NO_RESULT


@pytest.mark.parametrize(("argv", "attr"), PATH_COMMANDS)
def test_windows_absolute_path_parses(argv: list[str], attr: str) -> None:
    args = build_parser().parse_args(argv)
    assert str(getattr(args, attr)) == WINDOWS_PATH


def test_module_entry_point_help_runs() -> None:
    # The same path the console script takes, minus PATH lookup.
    result = subprocess.run(
        [sys.executable, "-m", "sensor_qaqc.cli", "--help"],
        capture_output=True,
        check=False,
    )
    assert result.returncode == EXIT_PRODUCED
