"""Container-agnostic table parsing: rows in, located values out (#3).

A source is *tables*, not a file. These parsers take rows - tuples of cell
values, whether they came from a workbook sheet or from a CSV reader - and a
shape from ``sources.yaml``. Locating the tables is the adapter's job; nothing
here knows what a sheet is.

Nothing here knows what the values *mean* either. Vendor vocabulary
(``Fixed - Normal``, ``0 hour 10 minutes 0 seconds``, ``°F``) is normalised by
the adapter that owns the vendor, so a second vendor with the same table shape
reuses these parsers without inheriting Onset's words.

The refusals are the point. A row the parser cannot place is refused rather
than skipped, because a sample dropped between the file and the analysis is
the failure #3 exists to prevent - and a parser that shrugs is how it happens.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sensor_qaqc.instruments.containers import TYPED_CELLS

if TYPE_CHECKING:
    import re
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from sensor_qaqc.instruments.containers import CellCoercion
    from sensor_qaqc.instruments.sources import (
        DataTableSpec,
        DetailsTableSpec,
        EventsTableSpec,
    )


class MissingDetailError(LookupError):
    """A details key the reader needs is not in the table."""


@dataclass(frozen=True)
class DetailsTable:
    """Vendor metadata as key/value rows, keyed by (section, key).

    Keyed by the pair rather than by the key alone because sections are how
    the export disambiguates: ``Version`` under ``App Info`` is the app's,
    ``Firmware Version`` under ``Device Info`` is the logger's, and a flat
    namespace would let a future export's collision overwrite one silently.
    """

    entries: Mapping[tuple[str, str], str]
    series: str | None

    def value(self, section: str, key: str) -> str:
        if (section, key) not in self.entries:
            raise MissingDetailError(f"the details table has no {key!r} under {section!r}")
        return self.entries[section, key]

    def optional(self, section: str, key: str) -> str | None:
        return self.entries.get((section, key))

    def section(self, section: str) -> Mapping[str, str]:
        return {key: value for (found, key), value in self.entries.items() if found == section}


@dataclass(frozen=True)
class ParsedEvent:
    """One marked cell of an event table: when, and which column marked it."""

    at: datetime
    label: str


@dataclass(frozen=True)
class ParsedEvents:
    """The raw parse of an event table, in the order the rows carried it."""

    events: tuple[ParsedEvent, ...]
    timezone_label: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class ParsedData:
    """The raw parse of a data table, before any gridding or conversion."""

    sample_numbers: tuple[int, ...]
    timestamps: tuple[datetime, ...]
    values: tuple[float, ...]
    # None wherever the header does not declare the fact - a bare CSV states no
    # unit and no zone, and inventing either is what header_declares exists to
    # make impossible.
    series: str | None
    unit: str | None
    timezone_label: str | None
    notes: tuple[str, ...]


def _cell(row: Sequence[object], position: int) -> object:
    """Return the 1-based ``position`` of a row, or None where the row is short."""
    index = position - 1
    return row[index] if 0 <= index < len(row) else None


def _text(raw: object) -> str | None:
    """Return a cell as trimmed text, or None when it is empty.

    Trailing space is Onset's own - ``'Stop When Memory Fills '`` carries one
    in the vendor file - so stripping happens here, once, rather than at each
    place a value is compared.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def parse_details(rows: Iterable[Sequence[object]], spec: DetailsTableSpec) -> DetailsTable:
    """Read key/value rows grouped under section headings."""
    entries: dict[tuple[str, str], str] = {}
    series: str | None = None
    section: str | None = None
    for row in rows:
        outer = _text(_cell(row, spec.series_column))
        if outer is not None and outer.startswith(spec.series_prefix):
            declared = outer[len(spec.series_prefix) :].strip()
            if series is not None and series != declared:
                raise ValueError(
                    f"the details table declares two series ({series!r}, {declared!r});"
                    " multi-series exports have never been seen and their shape is unverified"
                )
            series = declared
            continue
        heading = _text(_cell(row, spec.section_column))
        if heading is not None:
            section = heading
            continue
        key = _text(_cell(row, spec.key_column))
        if key is None:
            continue
        if section is None:
            raise ValueError(f"details key {key!r} appears before any section heading")
        if (section, key) in entries:
            raise ValueError(f"the details table repeats {key!r} under {section!r}")
        entries[section, key] = _text(_cell(row, spec.value_column)) or ""
    return DetailsTable(entries=entries, series=series)


@dataclass(frozen=True)
class _DataColumns:
    """Where each column is, and what its header declared."""

    number_at: int
    stamp_at: int
    value_at: int
    series: str | None
    unit: str | None
    timezone_label: str | None


def _capture(matched: re.Match[str], name: str) -> str | None:
    return str(matched.group(name)) if name in matched.re.groupindex else None


def _locate(header: Sequence[object], spec: DataTableSpec) -> _DataColumns:
    """Column positions and what the headers declared, or refuse."""
    headers = [_text(cell) for cell in header]
    stamped = [(i, spec.timestamp_column.match(text)) for i, text in enumerate(headers) if text]
    timestamps = [(i, m) for i, m in stamped if m is not None]
    valued = [(i, spec.value_column.match(text)) for i, text in enumerate(headers) if text]
    values = [(i, m) for i, m in valued if m is not None]
    for name, found in (("timestamp", timestamps), ("value", values)):
        if not found:
            raise ValueError(
                f"no {name} column in the header {[h for h in headers if h]};"
                f" the shape in sources.yaml does not match this file"
            )
        if len(found) > 1:
            matched = [headers[i] for i, _ in found]
            raise ValueError(
                f"{len(found)} columns match the {name} shape ({matched});"
                " one series per file is all this format has been verified to hold"
            )
    (stamp_at, stamp_match), (value_at, value_match) = timestamps[0], values[0]
    number_at = -1
    if spec.sample_number_column:
        if spec.sample_number_column not in headers:
            raise ValueError(
                f"no {spec.sample_number_column!r} column in the header {[h for h in headers if h]}"
            )
        number_at = headers.index(spec.sample_number_column)
    return _DataColumns(
        number_at=number_at,
        stamp_at=stamp_at,
        value_at=value_at,
        series=_capture(value_match, "series"),
        unit=_capture(value_match, "unit"),
        timezone_label=_capture(stamp_match, "timezone"),
    )


def parse_data(
    rows: Iterable[Sequence[object]],
    spec: DataTableSpec,
    *,
    cells: CellCoercion = TYPED_CELLS,
) -> ParsedData:
    """Read the observations, refusing any row that cannot be placed."""
    iterator = iter(rows)
    header = _header(iterator, spec.header_row, "data")
    columns = _locate(header, spec)

    numbers: list[int] = []
    stamps: list[datetime] = []
    values: list[float] = []
    blank = 0
    for offset, row in enumerate(iterator, start=spec.header_row + 1):
        number = _cell(row, columns.number_at + 1) if columns.number_at >= 0 else None
        stamp = _cell(row, columns.stamp_at + 1)
        value = _cell(row, columns.value_at + 1)
        if number is None and stamp is None and value is None:
            blank += 1
            continue
        if stamp is None:
            raise ValueError(f"row {offset} of the data table has a value but no timestamp")
        stamps.append(_stamp(offset, stamp, "data", cells))
        values.append(_value(offset, value, cells))
        if columns.number_at >= 0:
            numbers.append(_number(offset, number, numbers, cells))
    notes = (f"{blank} blank rows skipped in the data table",) if blank else ()
    return ParsedData(
        sample_numbers=tuple(numbers),
        timestamps=tuple(stamps),
        values=tuple(values),
        series=columns.series,
        unit=columns.unit,
        timezone_label=columns.timezone_label,
        notes=notes,
    )


def parse_events(
    rows: Iterable[Sequence[object]],
    spec: EventsTableSpec,
    *,
    cells: CellCoercion = TYPED_CELLS,
) -> ParsedEvents:
    """Read the event log, discovering its column set from the header.

    One column per event type, and only types that occurred - so the columns
    are found by name every time. Positions would be read off whichever export
    the parser was written against, and the next one would silently disagree.
    """
    iterator = iter(rows)
    header = _header(iterator, spec.header_row, "event")
    headers = [_text(cell) for cell in header]
    stamped = [(i, spec.timestamp_column.match(text)) for i, text in enumerate(headers) if text]
    matched = [(i, found) for i, found in stamped if found is not None]
    if len(matched) != 1:
        raise ValueError(
            f"{len(matched)} columns match the timestamp shape in the event header"
            f" {[h for h in headers if h]}; exactly one is expected"
        )
    stamp_at, stamp_match = matched[0]
    columns = {
        i: text
        for i, text in enumerate(headers)
        if text and i != stamp_at and text != spec.sample_number_column
    }

    events: list[ParsedEvent] = []
    blank = 0
    for offset, row in enumerate(iterator, start=spec.header_row + 1):
        stamp = _cell(row, stamp_at + 1)
        marks = [(at, _text(_cell(row, at + 1))) for at in columns]
        marked = [(at, mark) for at, mark in marks if mark is not None]
        if stamp is None and not marked:
            blank += 1
            continue
        if stamp is None:
            raise ValueError(f"row {offset} of the event table marks an event but has no timestamp")
        when = _stamp(offset, stamp, "event", cells)
        if not marked:
            raise ValueError(f"row {offset} of the event table has a timestamp but marks no event")
        for at, mark in marked:
            if mark != spec.marker:
                raise ValueError(
                    f"row {offset} of the event table holds {mark!r} under {columns[at]!r}"
                    f" where the marker {spec.marker!r} belongs"
                )
            events.append(ParsedEvent(at=when, label=columns[at]))
    notes = (f"{blank} blank rows skipped in the event table",) if blank else ()
    return ParsedEvents(
        events=tuple(events),
        timezone_label=str(stamp_match.group("timezone")),
        notes=notes,
    )


def _header(iterator: Iterator[Sequence[object]], header_row: int, table: str) -> Sequence[object]:
    """Return the declared header row, consuming everything above it."""
    for position, row in enumerate(iterator, start=1):
        if position == header_row:
            return row
    raise ValueError(f"the {table} table has no row {header_row} to read a header from")


def _stamp(row: int, raw: object, table: str, cells: CellCoercion) -> datetime:
    """Return a cell as a timestamp, in the container's own terms."""
    try:
        converted = cells.timestamp(raw)
    except ValueError as error:
        raise ValueError(
            f"row {row} of the {table} table holds {raw!r}, which is not a timestamp in"
            f" the format this source declares: {error}"
        ) from error
    if not isinstance(converted, datetime):
        raise ValueError(  # noqa: TRY004 - a text date is an ambiguous file, not a caller's type error
            f"row {row} of the {table} table holds {raw!r} where a timestamp belongs;"
            " a date the container did not store as a date is ambiguous, not readable"
        )
    return converted


def _value(row: int, raw: object, cells: CellCoercion) -> float:
    """Return a reading, or NaN where the sample was logged without one."""
    if raw is None:
        return math.nan
    return _number_cell(row, raw, cells)


def _number_cell(row: int, raw: object, cells: CellCoercion) -> float:
    """Return a cell as a number; one that is not is a column read wrongly."""
    try:
        converted = cells.number(raw)
    except ValueError as error:
        raise ValueError(
            f"row {row} of the data table holds {raw!r} where a number belongs"
        ) from error
    if isinstance(converted, bool) or not isinstance(converted, (int, float)):
        # A value cell holding text is a parse that landed in the wrong column,
        # not a caller passing the wrong type - hence ValueError.
        raise ValueError(  # noqa: TRY004
            f"row {row} of the data table holds {raw!r} where a number belongs"
        )
    return float(converted)


def _number(row: int, raw: object, seen: Sequence[int], cells: CellCoercion) -> int:
    """Return the sample number, which must continue the export's own sequence."""
    counted = _number_cell(row, raw, cells)
    if counted != int(counted):
        raise ValueError(f"row {row} of the data table holds {raw!r} where a sample number belongs")
    number = int(counted)
    if seen and number != seen[-1] + 1:
        raise ValueError(
            f"sample number {number} follows {seen[-1]} at row {row}; the export numbers"
            f" samples consecutively, so {seen[-1] + 1} was removed from the file"
        )
    return number
