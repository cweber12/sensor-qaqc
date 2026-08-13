"""A second container, and a format that states nothing (#3, acceptance 3).

The bundle fixtures are the pristine workbook's own three sheets written out as
CSV files (`scripts/derive_csv_fixtures.py`, run once, hash-pinned). That makes
the strongest available assertion: the CSV bundle must ingest to *the same
canonical record* the workbook produces - same samples, same statistics, same
events - through the same Onset reader, which never learns which container it
was handed.

The bare CSV is the other end. It states no unit, no zone, no interval and no
identity, so the same assembly function must refuse until an operator supplies
them, and the gate must report itself not applicable rather than silent.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sensor_qaqc.instruments.checksum import verify_published_statistics
from sensor_qaqc.instruments.extraction import (
    IncompleteRecordError,
    SuppliedMetadata,
    assemble,
)
from sensor_qaqc.instruments.generic_csv import GenericCsvReader
from sensor_qaqc.instruments.onset.hoboconnect import HOBOconnectReader
from sensor_qaqc.instruments.sensors import load_sensor_catalogue
from sensor_qaqc.instruments.sources import load_source_catalogue

if TYPE_CHECKING:
    from sensor_qaqc.core.records import CanonicalRecord
    from sensor_qaqc.instruments.extraction import Extraction

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = REPO_ROOT / "docs" / "data" / "yellow_buoy_temps.xlsx"
BUNDLE = Path(__file__).resolve().parent / "data" / "csv_bundle"
SAMPLES = 3029
BARE_ROWS = 3


def _supplied(**overrides: object) -> SuppliedMetadata:
    fields: dict[str, object] = {"variable": "sea_water_temperature"}
    fields.update(overrides)
    return SuppliedMetadata(**fields)  # type: ignore[arg-type]


def _record(format_id: str, path: Path) -> CanonicalRecord:
    reader = HOBOconnectReader(load_source_catalogue().for_format(format_id))
    return assemble(reader.read(path), _supplied(), sensors=load_sensor_catalogue())


# --- The same tables in a different container reach the same record. ---


def test_the_csv_bundle_ingests_to_the_same_record_as_the_workbook() -> None:
    from_xlsx = _record("hoboconnect_xlsx", WORKBOOK)
    from_csv = _record("hoboconnect_sheets_csv", BUNDLE)

    assert from_csv.series.equals(from_xlsx.series)
    assert from_csv.events == from_xlsx.events
    for field in ("variable", "units", "interval_s", "deployment_id", "n_valid", "gap_fraction"):
        assert getattr(from_csv, field) == getattr(from_xlsx, field)


def test_pointing_at_the_data_file_finds_its_siblings() -> None:
    # A bundle is a set of files, so either the directory or the data file
    # names it - an operator should not have to know which we wanted.
    reader = HOBOconnectReader(load_source_catalogue().for_format("hoboconnect_sheets_csv"))
    assert len(reader.read(BUNDLE / "data.csv").timestamps) == SAMPLES


def test_the_gate_runs_on_the_bundle_because_its_details_table_came_too() -> None:
    # The gate follows the metadata, not the file type.
    reader = HOBOconnectReader(load_source_catalogue().for_format("hoboconnect_sheets_csv"))
    outcome = verify_published_statistics(reader.read(BUNDLE))
    assert outcome.applicable
    assert not outcome.refused


def test_a_declared_table_that_is_absent_refuses(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text(
        (BUNDLE / "data.csv").read_text(encoding="utf-8"), encoding="utf-8", newline=""
    )
    reader = HOBOconnectReader(load_source_catalogue().for_format("hoboconnect_sheets_csv"))
    with pytest.raises(ValueError, match=r"details.csv"):
        reader.read(tmp_path / "data.csv")


def test_a_stamp_outside_the_declared_format_refuses(tmp_path: Path) -> None:
    # No inference: a source declares the format its stamps are written in, so
    # 11/07/2026 is not quietly read as the 7th of November.
    _write(tmp_path / "data.csv", [["timestamp", "value"], ["11/07/2026 07:00", "70.1"]])
    reader = GenericCsvReader(load_source_catalogue().for_format("generic_csv"))
    with pytest.raises(ValueError, match="not a timestamp in the format"):
        reader.read(tmp_path / "data.csv")


# --- A source that states nothing: every fact supplied, and the gate says so. ---


def _bare(path: Path) -> Path:
    _write(
        path,
        [
            ["timestamp", "value"],
            ["2026-07-11T07:00:00", "70.1"],
            ["2026-07-11T07:10:00", "70.3"],
            ["2026-07-11T07:20:00", "70.2"],
        ],
    )
    return path


def _write(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)


def _read_bare(path: Path) -> Extraction:
    return GenericCsvReader(load_source_catalogue().for_format("generic_csv")).read(path)


def test_a_bare_csv_extracts_the_samples_and_nothing_else(tmp_path: Path) -> None:
    extraction = _read_bare(_bare(tmp_path / "data.csv"))
    assert len(extraction.timestamps) == BARE_ROWS
    metadata = extraction.metadata
    assert metadata.units is None
    assert metadata.source_timezone_label is None
    assert metadata.interval_s is None
    assert metadata.serial is None


def test_a_bare_csv_reports_the_gate_as_not_applicable(tmp_path: Path) -> None:
    outcome = verify_published_statistics(_read_bare(_bare(tmp_path / "data.csv")))
    assert not outcome.applicable
    assert not outcome.refused
    assert "no vendor statistics" in outcome.reason


def test_a_bare_csv_refuses_assembly_until_every_missing_fact_is_supplied(
    tmp_path: Path,
) -> None:
    extraction = _read_bare(_bare(tmp_path / "data.csv"))
    with pytest.raises(IncompleteRecordError) as raised:
        assemble(extraction, _supplied(), sensors=load_sensor_catalogue())
    for name in ("units", "source_timezone_label", "interval_s", "serial", "product"):
        assert name in str(raised.value)


def test_a_bare_csv_reaches_the_canonical_record_once_an_operator_speaks(
    tmp_path: Path,
) -> None:
    extraction = _read_bare(_bare(tmp_path / "data.csv"))
    record = assemble(
        extraction,
        _supplied(
            product="MX2204",
            serial="22506632",
            deployment_number=3,
            interval_s=600,
            units="degF",
            source_timezone_label="PDT",
            depth_m=1.5,
        ),
        sensors=load_sensor_catalogue(),
    )
    assert record.n_valid == BARE_ROWS
    assert record.units == "degF"
    assert str(record.series.index[0]) == "2026-07-11 14:00:00+00:00"
    # Everything the file could not state is marked as the operator's word.
    assert {record.provenance[name] for name in ("units", "serial", "interval_s")} == {"supplied"}
