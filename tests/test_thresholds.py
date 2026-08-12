"""Provenance is unconstructable-without, floors only tighten, variables never fall back (#2)."""

from __future__ import annotations

import dataclasses
from typing import Any, cast

import pytest

import sensor_qaqc.core.thresholds
from sensor_qaqc.core.thresholds import (
    MaxOfFloors,
    MissingThresholdsError,
    Provenance,
    Threshold,
    ThresholdTable,
)

PHYSICAL = Threshold(
    value=1.0,
    unit="h",
    provenance=Provenance(source="physical argument", rationale="coastal decorrelation floor"),
)
DATASHEET = Threshold(
    value=0.58,
    unit="h",
    provenance=Provenance(source="MX2204 datasheet", rationale="derived from t90"),
)


@pytest.mark.parametrize(("source", "rationale"), [("", "why"), ("src", ""), ("  ", "why")])
def test_provenance_requires_source_and_rationale(source: str, rationale: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        Provenance(source=source, rationale=rationale)


def test_a_threshold_cannot_exist_without_provenance() -> None:
    # No unspecified variant: provenance is a required constructor argument.
    with pytest.raises(TypeError):
        Threshold(value=1.0, unit="h")  # type: ignore[call-arg]


def test_a_none_provenance_is_rejected_at_runtime() -> None:
    # Issue #21: mypy flags the literal None, but the runtime must refuse
    # too - the invariant cannot rest on the type checker alone.
    with pytest.raises(TypeError, match="provenance"):
        Threshold(value=1.0, unit="h", provenance=None)  # type: ignore[arg-type]


def test_replace_cannot_strip_provenance() -> None:
    # dataclasses.replace re-runs __post_init__; this pins that it stays true.
    with pytest.raises(TypeError, match="provenance"):
        dataclasses.replace(PHYSICAL, provenance=cast("Any", None))


def test_an_any_typed_none_provenance_is_rejected() -> None:
    # The YAML-shaped route (#5/#6): an empty provenance key parses to None
    # typed as Any, which mypy cannot see through - only a runtime guard
    # catches it.
    parsed: dict[str, Any] = {"value": 1.0, "unit": "h", "provenance": None}
    with pytest.raises(TypeError, match="provenance"):
        Threshold(value=parsed["value"], unit=parsed["unit"], provenance=parsed["provenance"])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_threshold_values_must_be_finite(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        Threshold(value=value, unit="1", provenance=PHYSICAL.provenance)


def test_threshold_requires_a_unit() -> None:
    with pytest.raises(ValueError, match="unit"):
        Threshold(value=1.0, unit=" ", provenance=PHYSICAL.provenance)


def test_max_of_floors_takes_the_tightest_floor() -> None:
    # The recorded concrete case: the datasheet floor (~0.58 h) is more
    # permissive than the physical floor (~1.0 h) and must not win.
    combined = MaxOfFloors(floors=(DATASHEET, PHYSICAL))
    assert combined.value == PHYSICAL.value
    assert combined.governing is PHYSICAL
    assert combined.provenance is PHYSICAL.provenance
    assert combined.unit == "h"


def test_max_of_floors_keeps_every_constituent_visible() -> None:
    combined = MaxOfFloors(floors=(DATASHEET, PHYSICAL))
    assert combined.floors == (DATASHEET, PHYSICAL)


def test_max_of_floors_tie_goes_to_the_earliest_floor() -> None:
    other = Threshold(
        value=1.0,
        unit="h",
        provenance=Provenance(source="other", rationale="same value, listed later"),
    )
    assert MaxOfFloors(floors=(PHYSICAL, other)).governing is PHYSICAL


def test_max_of_floors_rejects_mixed_units_and_emptiness() -> None:
    minutes = Threshold(value=60.0, unit="min", provenance=DATASHEET.provenance)
    with pytest.raises(ValueError, match="share a unit"):
        MaxOfFloors(floors=(PHYSICAL, minutes))
    with pytest.raises(ValueError, match="at least one"):
        MaxOfFloors(floors=())


def test_there_is_deliberately_no_min_of_floors() -> None:
    # Combining floors by minimum is the move that silently weakens a check.
    assert not hasattr(sensor_qaqc.core.thresholds, "MinOfFloors")


def test_lookup_by_variable_returns_that_variable_only() -> None:
    table = ThresholdTable({"sea_water_temperature": {"efold_floor_h": PHYSICAL}})
    assert table.variables == {"sea_water_temperature"}
    assert table.for_variable("sea_water_temperature")["efold_floor_h"] is PHYSICAL


def test_an_unknown_variable_refuses_naming_what_exists() -> None:
    table = ThresholdTable({"sea_water_temperature": {"efold_floor_h": PHYSICAL}})
    with pytest.raises(
        MissingThresholdsError,
        match=r"'sea_water_salinity'.*sea_water_temperature.*Refusing",
    ):
        table.for_variable("sea_water_salinity")


def test_an_empty_table_still_names_the_refusal() -> None:
    with pytest.raises(MissingThresholdsError, match="none"):
        ThresholdTable({}).for_variable("sea_water_temperature")
