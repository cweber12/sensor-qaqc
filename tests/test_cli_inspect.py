"""``sensor-qaqc inspect``: the first end-to-end path through the tool (#3).

Everything below runs the real command over the real fixtures. What the report
says is the acceptance for the PRD's "the canonical schema is the contract"
claim, seen from outside: the same command reads a workbook, the same tables
written out as CSV files, and a CSV that states nothing, and reports each one
in the same terms.

Exit codes follow ADR 0002: 0 means a report was produced, not that the record
passed - nothing is gated. A refused checksum gate is 1, because a parse that
cannot be trusted is "the tool could not produce a result".
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from sensor_qaqc.cli.__main__ import EXIT_NO_RESULT, EXIT_PRODUCED, main
from sensor_qaqc.instruments.readers import UnreadableSourceError, select_format
from sensor_qaqc.instruments.sources import load_source_catalogue

REPO_ROOT = Path(__file__).resolve().parents[1]
PRISTINE = REPO_ROOT / "docs" / "data" / "yellow_buoy_temps.xlsx"
EDITED = Path(__file__).resolve().parent / "data" / "yellow_buoy_temps_edited.xlsx"
BUNDLE = Path(__file__).resolve().parent / "data" / "csv_bundle"


def _run(path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(["inspect", str(path)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _bare_csv(path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        csv.writer(handle, lineterminator="\n").writerows(
            [
                ["timestamp", "value"],
                ["2026-07-11T07:00:00", "70.1"],
                ["2026-07-11T07:10:00", "70.3"],
            ]
        )
    return path


# --- The vendor export: a report, and exit 0. ---


def test_inspecting_the_pristine_export_reports_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = _run(PRISTINE, capsys)
    assert code == EXIT_PRODUCED
    assert "all 7 published statistics reproduced" in out
    assert "MX2204 serial 22506632, deployment 3" in out
    assert "interval 600 s, stamps in PDT" in out
    assert "3029 parsed" in out
    assert "n_valid 3029, gap_fraction 0.0000" in out
    assert "5 (end_of_file x1, host_connected x3, started x1)" in out


def test_the_report_names_what_only_an_operator_can_supply(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # inspect names them; it does not ask. Prompting UX is out of scope for
    # #3, and a value invented to get a record built would be recorded with
    # the same provenance as one somebody actually knew.
    _, out, _ = _run(PRISTINE, capsys)
    still_needed = out.split("still needed from an operator:")[1]
    assert "variable" in still_needed
    for name in ("depth_m", "depth_datum", "mounting", "in_water_start", "in_water_end"):
        assert name in still_needed
    # The vendor export states these, so they must not be asked for.
    for stated in ("serial", "interval_s", "units"):
        assert stated not in still_needed


def test_units_are_reported_as_extracted_and_the_variable_as_nobody_s(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, out, _ = _run(PRISTINE, capsys)
    assert "units: degF, extracted" in out
    assert "variable: not stated by any source" in out


# --- The corrupt copy: the report still prints, and the exit code is 1. ---


def test_a_refused_gate_exits_one_and_names_the_mismatches(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = _run(EDITED, capsys)
    assert code == EXIT_NO_RESULT
    # The report is still produced: an operator needs to see what was read.
    assert "5 of 7 published statistics could not be reproduced" in out
    for expected in ("samples", "minimum", "std_dev"):
        assert expected in err
    assert "3022" in err
    assert "3029" in err
    assert "Traceback" not in err


def test_the_blank_rows_it_passed_over_are_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, out, _ = _run(EDITED, capsys)
    assert "7 blank rows skipped in the data table" in out
    assert "994 blank rows skipped in the event table" in out


# --- The same tables in CSV, and a CSV that states nothing. ---


def test_a_csv_bundle_is_recognised_and_gated_like_the_workbook(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = _run(BUNDLE, capsys)
    assert code == EXIT_PRODUCED
    assert "format: hoboconnect_sheets_csv" in out
    assert "all 7 published statistics reproduced" in out
    assert "3029 parsed" in out


def test_a_bare_csv_is_reported_as_ungated_and_mostly_unstated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(_bare_csv(tmp_path / "data.csv"), capsys)
    assert code == EXIT_PRODUCED
    assert "format: generic_csv" in out
    assert "gate is not applicable" in out
    assert "grid: not computed" in out
    still_needed = out.split("still needed from an operator:")[1]
    for name in ("units", "source_timezone_label", "interval_s", "serial", "product"):
        assert name in still_needed


# --- Selection is by what is there, and refusals say what was looked for. ---


def test_a_bundle_is_preferred_over_the_bare_format_that_also_matches() -> None:
    # Both formats match a directory holding data.csv. Reading a bundle as a
    # bare CSV would silently skip the checksum gate on a source that
    # publishes statistics, which is the one outcome that must not happen.
    selected = select_format(BUNDLE, load_source_catalogue())
    assert selected.format_id == "hoboconnect_sheets_csv"


def test_a_lone_csv_selects_the_format_that_needs_no_sidecars(tmp_path: Path) -> None:
    selected = select_format(_bare_csv(tmp_path / "data.csv"), load_source_catalogue())
    assert selected.format_id == "generic_csv"


def test_a_path_that_is_not_there_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(Path("nowhere/absent.xlsx"), capsys)
    assert code == EXIT_NO_RESULT
    assert "nothing at" in err


def test_a_container_nothing_reads_refuses_naming_what_is_known(tmp_path: Path) -> None:
    unreadable = tmp_path / "export.hobo"
    unreadable.write_bytes(b"")
    with pytest.raises(UnreadableSourceError, match=r"\.csv.*\.xlsx|\.xlsx.*\.csv"):
        select_format(unreadable, load_source_catalogue())
