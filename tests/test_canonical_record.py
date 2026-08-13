"""The canonical record is the contract; its constructor owns the grid (#3).

Two failures this file exists to make impossible are recorded in #3 with
their evidence:

- A record whose span is measured after dropping missing rows. The review
  demonstration in ``TIDAL_LINES_REVIEW.md`` (D6) put a 21 d record at
  18.21 d that way and moved every tidal constituent into the wrong
  frequency bin. ``test_a_gappy_parse_keeps_its_true_span`` is that case.
- A sample silently dropped between the file and the analysis. Off-grid
  and duplicate timestamps therefore refuse rather than reindex away.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

import sensor_qaqc.core.records as records_module
from sensor_qaqc.core.records import (
    CanonicalRecord,
    EventType,
    FieldSource,
    LoggedEvent,
    LoggingMode,
    RecordView,
    to_uniform_grid,
)

START = pd.Timestamp("2026-07-11T14:00:00Z")
INTERVAL_S = 600
BASE_SAMPLES = 6
# The D6 demonstration's shape: a 21 d grid at 10 min, 2.8 d of rows absent.
SPAN_SAMPLES = 3025
ABSENT_SAMPLES = 403
FIRST_VALUE, LAST_VALUE = 10.0, 12.0

BASE_PROVENANCE = {
    "variable": FieldSource.SUPPLIED,
    "units": FieldSource.EXTRACTED,
    "interval_s": FieldSource.EXTRACTED,
    "source_timezone_label": FieldSource.EXTRACTED,
    "product": FieldSource.EXTRACTED,
    "serial": FieldSource.EXTRACTED,
    "deployment_number": FieldSource.EXTRACTED,
}


def _grid(n: int, interval_s: int = INTERVAL_S) -> pd.Series:
    index = pd.date_range(START, periods=n, freq=pd.Timedelta(seconds=interval_s), tz="UTC")
    return pd.Series(np.arange(n, dtype=float), index=index)


def _base() -> CanonicalRecord:
    return CanonicalRecord(
        variable="sea_water_temperature",
        units="degF",
        series=_grid(BASE_SAMPLES),
        interval_s=INTERVAL_S,
        source_timezone_label="PDT",
        product="MX2204",
        serial="22506632",
        deployment_number=3,
        provenance=BASE_PROVENANCE,
    )


def _as_view(record: RecordView) -> RecordView:
    """Structural conformance is checked by mypy at this call site."""
    return record


# --- The record is a RecordView, and its derived facts come from the grid. ---


def test_the_canonical_record_satisfies_record_view() -> None:
    view = _as_view(_base())
    assert view.variable == "sea_water_temperature"
    assert view.dt == timedelta(seconds=INTERVAL_S)
    assert view.duration == timedelta(seconds=(BASE_SAMPLES - 1) * INTERVAL_S)
    assert view.n_valid == BASE_SAMPLES
    assert view.gap_fraction == 0.0


def test_dt_is_derived_from_the_declared_interval() -> None:
    # One source of truth: the declared logging interval and the grid it was
    # built on cannot disagree, because there is only one number.
    record = _base()
    assert record.dt == timedelta(seconds=record.interval_s)


def test_deployment_id_is_serial_and_deployment_number() -> None:
    assert _base().deployment_id == "22506632-3"


# --- The grid contract: gaps are NaN in place, the span is never shortened. ---


def test_a_gappy_parse_keeps_its_true_span() -> None:
    # 21 d at 10 min, with 2.8 d of rows absent from the middle - the shape
    # of the D6 demonstration. The grid must still span 21 d and the count
    # of grid points must be the span, not the count of parsed rows.
    full = pd.date_range(
        START, periods=SPAN_SAMPLES, freq=pd.Timedelta(seconds=INTERVAL_S), tz="UTC"
    )
    kept = full.delete(range(1000, 1000 + ABSENT_SAMPLES))
    series = to_uniform_grid(kept, np.zeros(len(kept)), interval_s=INTERVAL_S)

    record = dataclasses.replace(_base(), series=series)
    assert len(record.series) == SPAN_SAMPLES
    assert record.duration == timedelta(seconds=(SPAN_SAMPLES - 1) * INTERVAL_S)
    assert record.n_valid == len(kept)
    assert record.n_valid != len(record.series)
    assert record.gap_fraction == pytest.approx(ABSENT_SAMPLES / SPAN_SAMPLES)


def test_gaps_stay_where_they_were_rather_than_closing_up() -> None:
    index = pd.DatetimeIndex([START, START + pd.Timedelta(seconds=2 * INTERVAL_S)])
    series = to_uniform_grid(index, [FIRST_VALUE, LAST_VALUE], interval_s=INTERVAL_S)
    assert list(series.index) == [START + pd.Timedelta(seconds=k * INTERVAL_S) for k in (0, 1, 2)]
    assert series.iloc[0] == FIRST_VALUE
    assert np.isnan(series.iloc[1])
    assert series.iloc[2] == LAST_VALUE


def test_an_off_grid_timestamp_refuses_rather_than_being_dropped() -> None:
    index = pd.DatetimeIndex([START, START + pd.Timedelta(seconds=INTERVAL_S + 1)])
    with pytest.raises(ValueError, match=r"not on the .*600 s.* grid"):
        to_uniform_grid(index, [10.0, 11.0], interval_s=INTERVAL_S)


def test_duplicate_timestamps_refuse() -> None:
    index = pd.DatetimeIndex([START, START])
    with pytest.raises(ValueError, match="duplicate"):
        to_uniform_grid(index, [10.0, 11.0], interval_s=INTERVAL_S)


def test_unsorted_timestamps_refuse_rather_than_being_sorted() -> None:
    index = pd.DatetimeIndex([START + pd.Timedelta(seconds=INTERVAL_S), START])
    with pytest.raises(ValueError, match="increasing"):
        to_uniform_grid(index, [11.0, 10.0], interval_s=INTERVAL_S)


def test_naive_timestamps_refuse() -> None:
    index = pd.DatetimeIndex(["2026-07-11 07:00", "2026-07-11 07:10"])
    with pytest.raises(ValueError, match="tz-aware UTC"):
        to_uniform_grid(index, [10.0, 11.0], interval_s=INTERVAL_S)


def test_a_mismatched_value_count_refuses() -> None:
    with pytest.raises(ValueError, match="3 timestamps"):
        to_uniform_grid(_grid(3).index, [10.0, 11.0], interval_s=INTERVAL_S)


def test_the_module_has_no_gap_filling_call() -> None:
    # "Never interpolate" is a property of the code, not of a docstring:
    # interpolation manufactures increment autocorrelation of exactly +1.0,
    # which is the statistic #7 measures. Scanned by AST so the prose above
    # can name the thing the code may not do.
    source = inspect.getsource(records_module)
    called = {
        node.attr for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Attribute)
    } | {node.id for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Name)}
    assert not called & {"interpolate", "fillna", "ffill", "bfill", "dropna", "resample"}


# --- The record refuses a grid it did not get to build. ---


def test_an_irregular_index_refuses() -> None:
    series = _grid(4)
    index = series.index.delete(2)
    with pytest.raises(ValueError, match="uniform grid"):
        dataclasses.replace(_base(), series=pd.Series([1.0, 2.0, 3.0], index=index))


def test_an_index_at_the_wrong_interval_refuses() -> None:
    with pytest.raises(ValueError, match="uniform grid"):
        dataclasses.replace(_base(), series=_grid(4, interval_s=300))


def test_a_non_utc_index_refuses() -> None:
    series = _grid(4)
    local = pd.Series(series.to_numpy(), index=series.index.tz_convert("America/Los_Angeles"))
    with pytest.raises(ValueError, match="UTC"):
        dataclasses.replace(_base(), series=local)


def test_a_single_sample_refuses() -> None:
    with pytest.raises(ValueError, match="two samples"):
        dataclasses.replace(_base(), series=_grid(1))


@pytest.mark.parametrize("field_name", ["variable", "units", "source_timezone_label", "serial"])
def test_an_empty_identity_field_refuses(field_name: str) -> None:
    blank: dict[str, Any] = {field_name: "  "}
    with pytest.raises(ValueError, match=f"non-empty {field_name}"):
        dataclasses.replace(_base(), **blank)


def test_a_non_positive_interval_refuses() -> None:
    with pytest.raises(ValueError, match="interval_s"):
        dataclasses.replace(_base(), interval_s=0)


# --- Provenance: every populated field says where it came from. ---


def test_a_populated_field_without_provenance_refuses() -> None:
    with pytest.raises(ValueError, match=r"no provenance.*logging_mode"):
        dataclasses.replace(_base(), logging_mode=LoggingMode.FIXED)


def test_provenance_for_an_unknown_field_refuses() -> None:
    with pytest.raises(ValueError, match=r"'salinity'.*not a field"):
        dataclasses.replace(
            _base(), provenance={**BASE_PROVENANCE, "salinity": FieldSource.SUPPLIED}
        )


def test_provenance_for_an_absent_field_refuses() -> None:
    # The mirror case: claiming a depth was supplied while depth_m is None
    # would put "operator-supplied" in a report for a field nobody supplied.
    with pytest.raises(ValueError, match=r"'depth_m'.*not populated"):
        dataclasses.replace(
            _base(), provenance={**BASE_PROVENANCE, "depth_m": FieldSource.SUPPLIED}
        )


def test_the_provenance_mapping_cannot_be_mutated_after_construction() -> None:
    record = _base()
    with pytest.raises(TypeError):
        record.provenance["units"] = FieldSource.SUPPLIED  # type: ignore[index]


def test_missing_operator_fields_names_what_only_an_operator_can_supply() -> None:
    record = _base()
    assert record.missing_operator_fields == (
        "depth_m",
        "depth_datum",
        "mounting",
        "in_water_start",
        "in_water_end",
    )
    supplied = dataclasses.replace(
        record,
        depth_m=1.5,
        provenance={**BASE_PROVENANCE, "depth_m": FieldSource.SUPPLIED},
    )
    assert "depth_m" not in supplied.missing_operator_fields


# --- Position and the operator window. ---


def test_a_position_missing_one_half_refuses() -> None:
    with pytest.raises(ValueError, match="latitude and longitude"):
        dataclasses.replace(
            _base(),
            latitude=32.87,
            provenance={**BASE_PROVENANCE, "latitude": FieldSource.SUPPLIED},
        )


def test_an_out_of_range_latitude_refuses() -> None:
    with pytest.raises(ValueError, match="latitude"):
        dataclasses.replace(
            _base(),
            latitude=132.0,
            longitude=-117.25,
            provenance={
                **BASE_PROVENANCE,
                "latitude": FieldSource.SUPPLIED,
                "longitude": FieldSource.SUPPLIED,
            },
        )


def test_an_in_water_window_that_ends_before_it_starts_refuses() -> None:
    with pytest.raises(ValueError, match="in_water_start"):
        dataclasses.replace(
            _base(),
            in_water_start=START + pd.Timedelta(hours=1),
            in_water_end=START,
            provenance={
                **BASE_PROVENANCE,
                "in_water_start": FieldSource.SUPPLIED,
                "in_water_end": FieldSource.SUPPLIED,
            },
        )


# --- Events are the audit trail, not a verdict (#3; policy is #7's). ---


def test_an_event_before_the_first_sample_is_kept() -> None:
    # The pristine export's first Host Connected is 2026-07-10 15:26 PDT,
    # the day before logging started. Constraining events to the sample span
    # would discard the launch record.
    early = LoggedEvent(at=START - pd.Timedelta(days=1), event_type=EventType.HOST_CONNECTED)
    record = dataclasses.replace(_base(), events=(early,))
    assert record.events[0].at < record.series.index[0]


def test_a_naive_event_timestamp_refuses() -> None:
    with pytest.raises(ValueError, match="tz-aware UTC"):
        LoggedEvent(at=pd.Timestamp("2026-07-11 07:00"), event_type=EventType.STARTED)


def test_event_types_are_a_closed_vocabulary() -> None:
    # A free string would let "Power Warn" and "power_warn" coexist as two
    # different events in one archive. Members arrive with the parser that
    # produces them (#3 slice 5).
    assert {member.value for member in EventType} == {
        "started",
        "host_connected",
        "end_of_file",
    }


def test_logging_modes_are_a_closed_vocabulary() -> None:
    assert {member.value for member in LoggingMode} == {"fixed"}


def test_the_adr_that_constrains_this_module_exists() -> None:
    adr = Path(__file__).resolve().parents[1] / "docs" / "decisions" / "0007-canonical-record.md"
    assert adr.is_file()
