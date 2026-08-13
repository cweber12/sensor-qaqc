"""One assembly function turns any extraction into the canonical record (#3).

This is the seam the PRD's "canonical schema is the contract" claim rests on:
a reader's whole job is to produce an ``Extraction``, and everything about
becoming a record - the grid, provenance, the unit check - happens once, here.
No reader exists yet; a stub stands in, which is the point.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from sensor_qaqc.core.records import EventType, FieldSource, LoggingMode
from sensor_qaqc.instruments.extraction import (
    ConflictingMetadataError,
    ExtractedMetadata,
    Extraction,
    IncompleteRecordError,
    SourceEvent,
    SourceReader,
    SuppliedMetadata,
    assemble,
)
from sensor_qaqc.instruments.sensors import MissingSensorError, parse_sensor_catalogue

if TYPE_CHECKING:
    from pathlib import Path

# The source's own frame (PDT) on the left, what assemble must produce on the
# right: localisation is the seam's job, not the reader's.
LOCAL_START = datetime(2026, 7, 11, 7, 0)  # noqa: DTZ001 - naive local, as a source states it
UTC_START = pd.Timestamp("2026-07-11T14:00:00Z")
INTERVAL_S = 600
SENSORS = parse_sensor_catalogue(
    "sensors:\n"
    "  MX2204:\n"
    "    native_units:\n"
    "      value: [degF, degC]\n"
    "      source: a datasheet\n"
    "      rationale: a reason\n"
)


def _local(n: int, *, step: int = INTERVAL_S) -> tuple[datetime, ...]:
    return tuple(LOCAL_START + timedelta(seconds=step * k) for k in range(n))


def _extraction(
    metadata: ExtractedMetadata | None = None,
    *,
    n: int = 4,
    events: tuple[SourceEvent, ...] = (),
) -> Extraction:
    return Extraction(
        format_id="stub",
        timestamps=_local(n),
        values=np.arange(n, dtype=float),
        metadata=metadata if metadata is not None else _extracted(),
        events=events,
    )


def _extracted(**overrides: object) -> ExtractedMetadata:
    fields: dict[str, object] = {
        "product": "MX2204",
        "serial": "22506632",
        "deployment_number": 3,
        "interval_s": INTERVAL_S,
        "units": "degF",
        "source_timezone_label": "PDT",
        "firmware": "62.140",
        "logging_mode": LoggingMode.FIXED,
    }
    fields.update(overrides)
    return ExtractedMetadata(**fields)  # type: ignore[arg-type]


def _supplied(**overrides: object) -> SuppliedMetadata:
    fields: dict[str, object] = {"variable": "sea_water_temperature"}
    fields.update(overrides)
    return SuppliedMetadata(**fields)  # type: ignore[arg-type]


# --- The happy path, and where each field's provenance comes from. ---


def test_assembly_records_which_fields_were_read_and_which_were_typed() -> None:
    record = assemble(_extraction(), _supplied(depth_m=1.5), sensors=SENSORS)

    assert record.variable == "sea_water_temperature"
    assert record.units == "degF"
    assert record.deployment_id == "22506632-3"
    assert record.logging_mode is LoggingMode.FIXED
    assert record.provenance["units"] is FieldSource.EXTRACTED
    assert record.provenance["serial"] is FieldSource.EXTRACTED
    assert record.provenance["variable"] is FieldSource.SUPPLIED
    assert record.provenance["depth_m"] is FieldSource.SUPPLIED
    assert record.missing_operator_fields == (
        "depth_datum",
        "mounting",
        "in_water_start",
        "in_water_end",
    )


def test_the_series_arrives_on_the_grid_with_its_gaps_in_place() -> None:
    stamps = (LOCAL_START, LOCAL_START + timedelta(seconds=2 * INTERVAL_S))
    extraction = Extraction(
        format_id="stub",
        timestamps=stamps,
        values=np.array([70.1, 70.3]),
        metadata=_extracted(),
    )
    record = assemble(extraction, _supplied(), sensors=SENSORS)
    assert len(record.series) == len(stamps) + 1
    assert record.n_valid == len(stamps)
    assert record.gap_fraction == pytest.approx(1 / 3)
    assert record.series.index[0] == UTC_START


def test_events_are_carried_through_and_localised_with_the_samples() -> None:
    # Ingest surfaces the audit trail; what an event means for a verdict is
    # #7's decision, with an injected policy (#3 amendments). The log is
    # resolved with the same label as the samples - two frames in one record
    # would shift the events against the series they explain.
    event = SourceEvent(at=LOCAL_START, event_type=EventType.STARTED)
    record = assemble(_extraction(events=(event,)), _supplied(), sensors=SENSORS)
    assert [logged.event_type for logged in record.events] == [EventType.STARTED]
    assert record.events[0].at == UTC_START


def test_a_source_that_publishes_no_statistics_still_assembles() -> None:
    # The gate is format-conditional: a bare CSV publishes nothing to check
    # against. Assembly must not require what only some formats have.
    assert _extraction().published is None
    assert assemble(_extraction(), _supplied(), sensors=SENSORS).n_valid == 4  # noqa: PLR2004


# --- What the file says wins; what it cannot say must be supplied. ---


def test_every_missing_required_field_is_named_at_once() -> None:
    # Named at once rather than one per run: an operator who is told about
    # one missing field at a time re-runs four times to learn four facts.
    bare = _extracted(product=None, serial=None, units=None, source_timezone_label=None)
    with pytest.raises(IncompleteRecordError) as raised:
        assemble(_extraction(bare), _supplied(), sensors=SENSORS)
    message = str(raised.value)
    for name in ("product", "serial", "units", "source_timezone_label"):
        assert name in message


def test_a_supplied_value_the_file_contradicts_refuses() -> None:
    with pytest.raises(ConflictingMetadataError, match=r"serial.*'99999999'.*'22506632'"):
        assemble(_extraction(), _supplied(serial="99999999"), sensors=SENSORS)


def test_a_supplied_value_the_file_agrees_with_is_still_extracted() -> None:
    record = assemble(_extraction(), _supplied(serial="22506632"), sensors=SENSORS)
    assert record.provenance["serial"] is FieldSource.EXTRACTED


def test_a_field_the_file_is_silent_about_may_be_supplied() -> None:
    # The rule is "never prompt for what the file states", not "never accept
    # an operator's value" - which is what lets a bare CSV reach the same
    # canonical shape as a vendor export (slice 6).
    silent = _extracted(source_timezone_label=None)
    record = assemble(_extraction(silent), _supplied(source_timezone_label="PST"), sensors=SENSORS)
    assert record.source_timezone_label == "PST"
    assert record.provenance["source_timezone_label"] is FieldSource.SUPPLIED


def test_a_position_the_file_carries_beats_a_supplied_one_only_if_they_agree() -> None:
    located = _extracted(latitude=32.87, longitude=-117.25)
    record = assemble(_extraction(located), _supplied(), sensors=SENSORS)
    assert record.provenance["latitude"] is FieldSource.EXTRACTED
    with pytest.raises(ConflictingMetadataError, match="latitude"):
        assemble(_extraction(located), _supplied(latitude=0.0, longitude=0.0), sensors=SENSORS)


# --- The unit is checked against the product's datasheet, not assumed. ---


def test_a_unit_the_product_cannot_report_refuses() -> None:
    with pytest.raises(ValueError, match=r"'degK'.*degC, degF"):
        assemble(_extraction(_extracted(units="degK")), _supplied(), sensors=SENSORS)


def test_an_unknown_product_refuses_rather_than_skipping_the_unit_check() -> None:
    with pytest.raises(MissingSensorError, match="MX1101"):
        assemble(_extraction(_extracted(product="MX1101")), _supplied(), sensors=SENSORS)


# --- The reader interface: a format's whole job is to produce an Extraction. ---


def test_a_reader_satisfying_the_protocol_assembles_end_to_end(tmp_path: Path) -> None:
    class StubReader:
        format_id = "stub"

        def read(self, path: Path) -> Extraction:  # noqa: ARG002 - the stub ignores it
            return _extraction()

    reader: SourceReader = StubReader()
    record = assemble(reader.read(tmp_path / "nothing.xlsx"), _supplied(), sensors=SENSORS)
    assert record.serial == "22506632"
