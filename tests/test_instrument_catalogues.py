"""`sources.yaml` and `sensors.yaml` are package data with a checked schema (#3).

Both ship inside the wheel and are resolved through package resources, never
through a path relative to ``__file__``: the latter works in a source checkout
and fails in an installed wheel, which is the one place a user meets it.

The schema is validated on load rather than at first use. A regex that does
not compile, or that lacks the named group the parser reads, would otherwise
surface as an unrelated error three slices later, in the parser rather than in
the file that is wrong.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import pytest

from sensor_qaqc.instruments.sensors import (
    MissingSensorError,
    load_sensor_catalogue,
    parse_sensor_catalogue,
)
from sensor_qaqc.instruments.sources import load_source_catalogue, parse_source_catalogue

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DATA = ("sources.yaml", "sensors.yaml")


# --- Package data resolves the way an installed wheel resolves it. ---


@pytest.mark.parametrize("name", PACKAGE_DATA)
def test_the_catalogue_resolves_through_package_resources(name: str) -> None:
    resource = importlib.resources.files("sensor_qaqc.instruments").joinpath(name)
    assert resource.read_text(encoding="utf-8").strip()


def test_every_package_data_file_is_named_in_the_wheel_assertion() -> None:
    # The wheel *inspection* runs in ci.yml's build job (CLAUDE.md records
    # that deviation). This test is the drift guard on it: package data that
    # nobody added to that list ships untested, and the failure only shows up
    # for a user installing from PyPI.
    package_root = REPO_ROOT / "src" / "sensor_qaqc"
    data_files = sorted(
        path.relative_to(package_root.parent).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and path.suffix != ".py" and "__pycache__" not in path.parts
    )
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    unasserted = [name for name in data_files if f'"{name}"' not in ci]
    assert not unasserted, f"package data not asserted in the wheel check: {unasserted}"


# --- sensors.yaml: datasheet facts, each carrying its citation. ---


def test_the_packaged_sensor_catalogue_knows_the_deployed_logger() -> None:
    catalogue = load_sensor_catalogue()
    spec = catalogue.for_product("MX2204")
    assert "degF" in spec.native_units.value
    assert spec.native_units.provenance.source.strip()


def test_an_unknown_product_refuses_naming_what_exists() -> None:
    catalogue = load_sensor_catalogue()
    with pytest.raises(MissingSensorError, match=r"'MX9999'.*MX2204"):
        catalogue.for_product("MX9999")


def test_a_fact_without_a_citation_refuses() -> None:
    with pytest.raises(ValueError, match="rationale"):
        parse_sensor_catalogue(
            "sensors:\n  MX2204:\n    native_units:\n      value: [degF]\n      source: a manual\n"
        )


def test_a_fact_nothing_reads_refuses_rather_than_being_ignored() -> None:
    # ADR 0005 discipline applied to data: a value arrives in the commit whose
    # code reads it. A silently ignored key would let an unread - and so
    # unverified - datasheet number sit in the file looking authoritative.
    with pytest.raises(ValueError, match="resolution_degc"):
        parse_sensor_catalogue(
            "sensors:\n"
            "  MX2204:\n"
            "    resolution_degc:\n"
            "      value: 0.01\n"
            "      source: a manual\n"
            "      rationale: a reason\n"
        )


# --- sources.yaml: file shape, never physics. ---


def test_the_packaged_source_catalogue_describes_the_hoboconnect_export() -> None:
    catalogue = load_source_catalogue()
    source = catalogue.for_format("hoboconnect_xlsx")
    assert source.container == "xlsx"
    assert source.tables == {"data": "Data", "events": "Events", "details": "Details"}
    assert source.data.timestamp_column.match("Date-Time (PDT)")
    unit = source.data.value_column.match("Tidbit 1 , °F")
    assert unit is not None
    assert unit.group("unit") == "°F"


def test_the_timestamp_pattern_captures_the_declared_zone_label() -> None:
    # #3: the label is parsed from the column header, never assumed. A pattern
    # that matched the header without capturing it would let "PDT" become a
    # constant somewhere downstream.
    catalogue = load_source_catalogue()
    matched = catalogue.for_format("hoboconnect_xlsx").data.timestamp_column.match(
        "Date-Time (PDT)"
    )
    assert matched is not None
    assert matched.group("timezone") == "PDT"


def test_an_unknown_format_refuses_naming_what_exists() -> None:
    catalogue = load_source_catalogue()
    with pytest.raises(LookupError, match=r"'star_oddi_csv'.*hoboconnect_xlsx"):
        catalogue.for_format("star_oddi_csv")


def test_a_pattern_missing_its_named_group_refuses() -> None:
    with pytest.raises(ValueError, match="unit"):
        parse_source_catalogue(_source_yaml(value_column="^(?P<series>.+) , (.+)$"))


def test_a_pattern_that_does_not_compile_refuses() -> None:
    with pytest.raises(ValueError, match="value_column"):
        parse_source_catalogue(_source_yaml(value_column="^(?P<unit>.+"))


def test_an_undeclared_container_refuses() -> None:
    with pytest.raises(ValueError, match="container"):
        parse_source_catalogue(_source_yaml(container="parquet"))


def _source_yaml(
    *,
    container: str = "xlsx",
    value_column: str = "^(?P<series>.+) , (?P<unit>.+)$",
) -> str:
    return (
        "formats:\n"
        "  hoboconnect_xlsx:\n"
        f"    container: {container}\n"
        "    tables:\n"
        "      data: Data\n"
        "    data:\n"
        "      header_row: 1\n"
        "      sample_number_column: '#'\n"
        "      timestamp_column: '^Date-Time \\((?P<timezone>.+)\\)$'\n"
        f"      value_column: '{value_column}'\n"
    )
