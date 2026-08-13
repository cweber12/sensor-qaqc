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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from sensor_qaqc.instruments.sources import DataTableSpec, DetailsTableSpec


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
class ParsedData:
    """The raw parse of a data table, before any gridding or conversion."""

    sample_numbers: tuple[int, ...]
    timestamps: tuple[datetime, ...]
    values: tuple[float, ...]
    series: str
    unit: str
    timezone_label: str
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


def _locate(header: Sequence[object], spec: DataTableSpec) -> tuple[int, int, int, str, str, str]:
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
    return (
        number_at,
        stamp_at,
        value_at,
        str(value_match.group("series")),
        str(value_match.group("unit")),
        str(stamp_match.group("timezone")),
    )


def parse_data(rows: Iterable[Sequence[object]], spec: DataTableSpec) -> ParsedData:
    """Read the observations, refusing any row that cannot be placed."""
    iterator = iter(rows)
    header: Sequence[object] | None = None
    for position, row in enumerate(iterator, start=1):
        if position == spec.header_row:
            header = row
            break
    if header is None:
        raise ValueError(f"the data table has no row {spec.header_row} to read a header from")
    number_at, stamp_at, value_at, series, unit, label = _locate(header, spec)

    numbers: list[int] = []
    stamps: list[datetime] = []
    values: list[float] = []
    blank = 0
    for offset, row in enumerate(iterator, start=spec.header_row + 1):
        number = _cell(row, number_at + 1) if number_at >= 0 else None
        stamp = _cell(row, stamp_at + 1)
        value = _cell(row, value_at + 1)
        if number is None and stamp is None and value is None:
            blank += 1
            continue
        if stamp is None:
            raise ValueError(f"row {offset} of the data table has a value but no timestamp")
        if not hasattr(stamp, "year"):
            raise ValueError(
                f"row {offset} of the data table holds {stamp!r} where a timestamp belongs;"
                " a date the container did not store as a date is ambiguous, not readable"
            )
        stamps.append(stamp)  # type: ignore[arg-type]
        values.append(_value(offset, value))
        if number_at >= 0:
            numbers.append(_number(offset, number, numbers))
    notes = (f"{blank} blank rows skipped in the data table",) if blank else ()
    return ParsedData(
        sample_numbers=tuple(numbers),
        timestamps=tuple(stamps),
        values=tuple(values),
        series=series,
        unit=unit,
        timezone_label=label,
        notes=notes,
    )


def _value(row: int, raw: object) -> float:
    """Return a reading, or NaN where the sample was logged without one."""
    if raw is None:
        return math.nan
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        # A value cell holding text is a parse that landed in the wrong column,
        # not a caller passing the wrong type - hence ValueError.
        raise ValueError(  # noqa: TRY004
            f"row {row} of the data table holds {raw!r} where a number belongs"
        )
    return float(raw)


def _number(row: int, raw: object, seen: Sequence[int]) -> int:
    """Return the sample number, which must continue the export's own sequence."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw != int(raw):
        raise ValueError(f"row {row} of the data table holds {raw!r} where a sample number belongs")
    number = int(raw)
    if seen and number != seen[-1] + 1:
        raise ValueError(
            f"sample number {number} follows {seen[-1]} at row {row}; the export numbers"
            f" samples consecutively, so {seen[-1] + 1} was removed from the file"
        )
    return number
