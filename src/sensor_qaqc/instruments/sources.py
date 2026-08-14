"""The format catalogue: where each export keeps its tables and columns (#3).

A source is *tables*, not a file - a data table, an optional events table and
an optional details table - so the same Details parser serves a workbook sheet
and a CSV sidecar, and the adapter's job is only to locate them.

Shape lives here; physics does not. The catalogue says which column carries
the timestamp and which carries the value; it says nothing about what the
value means, what range it may take, or what the unit implies. That split is
what makes adding a format an adapter-layer change.

Patterns are compiled and their named groups checked at load, not at first
use. A regex missing its ``unit`` group would otherwise surface as an
AttributeError inside a parser, pointing at the code rather than at the file
that is wrong.
"""

from __future__ import annotations

import importlib.resources
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

# Grown by the adapter that reads the new container.
KNOWN_CONTAINERS = frozenset({"xlsx", "csv"})
# Containers whose cells are text, so a timestamp format must be declared: a
# typed cell needs none, and inferring one is how a day becomes a month for
# the twelve days of the year where both readings parse.
TEXT_CONTAINERS = frozenset({"csv"})
# Facts a data header can state for itself, and the pattern group each is read
# from. `header_declares` must agree with the patterns exactly: a format
# cannot claim a fact it does not capture, nor capture one it did not declare.
DECLARABLE_FACTS = {"timezone": "timestamp_column", "unit": "value_column"}


class UnknownFormatError(LookupError):
    """No adapter shape for the requested format; the run must refuse."""


@dataclass(frozen=True)
class DataTableSpec:
    """Where the observations live in the data table."""

    header_row: int
    sample_number_column: str
    timestamp_column: re.Pattern[str]
    value_column: re.Pattern[str]
    header_declares: frozenset[str]


@dataclass(frozen=True)
class EventsTableSpec:
    """Where the event log lives, and how its dynamic columns are read.

    ``dynamic_columns`` is not decoration: the export writes one column per
    event *type* and only for types that occurred, so a parser addressing
    fixed positions reads the wrong column on any log unlike the one it was
    written against.
    """

    header_row: int
    sample_number_column: str
    timestamp_column: re.Pattern[str]
    marker: str
    dynamic_columns: bool


@dataclass(frozen=True)
class DetailsTableSpec:
    """Where the vendor's key/value metadata rows live. Columns are 1-based."""

    layout: str
    section_column: int
    key_column: int
    value_column: int
    series_column: int
    series_prefix: str


@dataclass(frozen=True)
class SourceFormat:
    """One export format's shape."""

    format_id: str
    description: str
    container: str
    tables: Mapping[str, str]
    data: DataTableSpec
    timestamp_format: str | None = None
    events: EventsTableSpec | None = None
    details: DetailsTableSpec | None = None


class SourceCatalogue:
    """Format shapes by id, with no default and no fallback."""

    def __init__(self, by_format: Mapping[str, SourceFormat]) -> None:
        self._by_format = dict(by_format)

    @property
    def formats(self) -> frozenset[str]:
        return frozenset(self._by_format)

    def for_format(self, format_id: str) -> SourceFormat:
        if format_id not in self._by_format:
            known = ", ".join(sorted(self._by_format)) or "none"
            raise UnknownFormatError(
                f"no source shape for format {format_id!r}; the catalogue knows: {known}."
            )
        return self._by_format[format_id]


def _pattern(format_id: str, table: str, key: str, raw: object) -> re.Pattern[str]:
    try:
        return re.compile(str(raw))
    except re.error as error:
        raise ValueError(f"{format_id}.{table}.{key} is not a valid regex: {error}") from error


def _check_declared(
    format_id: str, declares: frozenset[str], patterns: Mapping[str, re.Pattern[str]]
) -> None:
    """Check that the declared facts and the capture groups are one set."""
    unknown = sorted(declares - set(DECLARABLE_FACTS))
    if unknown:
        raise ValueError(
            f"{format_id}.data.header_declares names {unknown};"
            f" a header can declare: {sorted(DECLARABLE_FACTS)}"
        )
    for fact, key in DECLARABLE_FACTS.items():
        captured = fact in patterns[key].groupindex
        if fact in declares and not captured:
            raise ValueError(
                f"{format_id}.data declares {fact!r} but {key} does not capture it by name;"
                " the parser reads the value off the group, never off a position"
            )
        if fact not in declares and captured:
            raise ValueError(
                f"{format_id}.data captures {fact!r} in {key} without declaring it;"
                " a fact extracted but undeclared is one nobody reviewed"
            )


def _data_spec(format_id: str, raw: Mapping[str, object]) -> DataTableSpec:
    patterns = {
        key: _pattern(format_id, "data", key, raw.get(key))
        for key in ("timestamp_column", "value_column")
    }
    declared = raw.get("header_declares")
    if not isinstance(declared, list):
        # A malformed catalogue is a bad value in a file a human edits, not a
        # caller handing this function the wrong type.
        raise ValueError(  # noqa: TRY004
            f"{format_id}.data must declare what its header states as a list"
            f" (empty for a header that states nothing), got {declared!r}"
        )
    declares = frozenset(str(fact) for fact in declared)
    _check_declared(format_id, declares, patterns)
    return DataTableSpec(
        header_row=_positive_int(format_id, "data.header_row", raw.get("header_row")),
        sample_number_column=str(raw.get("sample_number_column", "")),
        timestamp_column=patterns["timestamp_column"],
        value_column=patterns["value_column"],
        header_declares=declares,
    )


def _events_spec(format_id: str, raw: Mapping[str, object]) -> EventsTableSpec:
    marker = str(raw.get("marker", ""))
    if not marker.strip():
        raise ValueError(f"{format_id}.events needs the marker its cells carry")
    return EventsTableSpec(
        header_row=_positive_int(format_id, "events.header_row", raw.get("header_row")),
        sample_number_column=str(raw.get("sample_number_column", "")),
        timestamp_column=_pattern(
            format_id, "events", "timestamp_column", raw.get("timestamp_column")
        ),
        marker=marker,
        dynamic_columns=bool(raw.get("dynamic_columns", False)),
    )


def _details_spec(format_id: str, raw: Mapping[str, object]) -> DetailsTableSpec:
    layout = str(raw.get("layout", ""))
    if layout != "key_value":
        raise ValueError(f"{format_id}.details.layout must be 'key_value', got {layout!r}")
    prefix = str(raw.get("series_prefix", ""))
    if not prefix.strip():
        raise ValueError(f"{format_id}.details needs the prefix its series declaration carries")
    return DetailsTableSpec(
        layout=layout,
        section_column=_positive_int(
            format_id, "details.section_column", raw.get("section_column")
        ),
        key_column=_positive_int(format_id, "details.key_column", raw.get("key_column")),
        value_column=_positive_int(format_id, "details.value_column", raw.get("value_column")),
        series_column=_positive_int(format_id, "details.series_column", raw.get("series_column")),
        series_prefix=prefix,
    )


def _timestamp_format(format_id: str, container: str, raw: object) -> str | None:
    """Return the strptime format a text container needs, or refuse."""
    declared = str(raw) if raw is not None else None
    if container in TEXT_CONTAINERS and not declared:
        raise ValueError(
            f"{format_id} is a {container} container, whose cells are text, so it must"
            " declare the timestamp_format its stamps are written in"
        )
    if container not in TEXT_CONTAINERS and declared:
        raise ValueError(
            f"{format_id} declares a timestamp_format, but a {container} cell already"
            " carries its type; the declaration would be read by nobody"
        )
    return declared


def _positive_int(format_id: str, key: str, raw: object) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        raise ValueError(f"{format_id}.{key} must be a 1-based position, got {raw!r}")
    return raw


def _format(format_id: str, raw: Mapping[str, object]) -> SourceFormat:
    container = str(raw.get("container", ""))
    if container not in KNOWN_CONTAINERS:
        raise ValueError(
            f"{format_id}.container is {container!r}; known containers are"
            f" {sorted(KNOWN_CONTAINERS)}. A container arrives with the adapter that reads it."
        )
    tables = raw.get("tables")
    if not isinstance(tables, dict) or "data" not in tables:
        raise ValueError(f"{format_id}.tables must locate at least the data table, got {tables!r}")
    data = raw.get("data")
    if not isinstance(data, dict) or not {"timestamp_column", "value_column"} <= set(data):
        raise ValueError(
            f"{format_id}.data must say where the timestamp and the value live, got {data!r}"
        )
    events = raw.get("events")
    details = raw.get("details")
    return SourceFormat(
        format_id=format_id,
        description=str(raw.get("description", "")),
        container=container,
        tables={str(name): str(where) for name, where in tables.items()},
        data=_data_spec(format_id, data),
        timestamp_format=_timestamp_format(format_id, container, raw.get("timestamp_format")),
        events=_events_spec(format_id, events) if isinstance(events, dict) else None,
        details=_details_spec(format_id, details) if isinstance(details, dict) else None,
    )


def parse_source_catalogue(text: str) -> SourceCatalogue:
    """Build a catalogue from YAML text, refusing anything under-specified."""
    document = yaml.safe_load(text)
    if not isinstance(document, dict) or "formats" not in document:
        raise ValueError("sources.yaml must be a mapping with a top-level 'formats' key")
    formats = document["formats"]
    if not isinstance(formats, dict) or not formats:
        raise ValueError("sources.yaml declares no formats")
    return SourceCatalogue({str(name): _format(str(name), raw) for name, raw in formats.items()})


def load_source_catalogue() -> SourceCatalogue:
    """Read the packaged catalogue - through resources, never through __file__."""
    resource = importlib.resources.files("sensor_qaqc.instruments").joinpath("sources.yaml")
    return parse_source_catalogue(resource.read_text(encoding="utf-8"))
