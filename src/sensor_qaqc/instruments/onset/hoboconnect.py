"""Reading a HOBOconnect workbook export (#3).

Everything here was verified against the recovered original export
(``docs/data/yellow_buoy_temps.xlsx``): three sheets, ``Data`` with an integer
sample number, a naive Excel serial timestamp and the value, ``Details`` as
key/value rows under section headings with every value stored as a *string*,
and ``Events`` as one column per event type. The Google Sheets round-trip that
was mistaken for an export is kept as a corrupt fixture and taught nothing.

This module owns Onset's vocabulary and nothing else: ``Fixed - Normal``
becomes ``fixed``, ``0 hour 10 minutes 0 seconds`` becomes ``600``, ``°F``
becomes the UDUNITS-2 symbol ``degF``. Table shape comes from ``sources.yaml``,
generic row parsing from ``tables`` and the container from ``containers`` - so
this reader serves the workbook and the same three tables written out as CSV
files without knowing which it is reading, and a second vendor with the same
table shapes reuses everything but these words.

Two facts the export states twice are checked against each other, because
agreement is free and disagreement means the parse is wrong: the unit appears
in the Data header and in the Details series declaration, and the zone label
appears in the Data header and on each published sample time. Neither check
overlaps the Details statistics gate, which compares the numbers.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

from sensor_qaqc.core.records import EventType, LoggingMode
from sensor_qaqc.instruments.containers import read_tables
from sensor_qaqc.instruments.extraction import (
    ExtractedMetadata,
    Extraction,
    PublishedStatistics,
    SourceEvent,
)
from sensor_qaqc.instruments.tables import parse_data, parse_details, parse_events

if TYPE_CHECKING:
    from pathlib import Path

    from sensor_qaqc.instruments.sources import SourceFormat
    from sensor_qaqc.instruments.tables import DetailsTable, ParsedEvents

# UDUNITS-2 symbols for the degree signs Onset writes in a column header.
UNIT_SYMBOLS = {"\N{DEGREE SIGN}F": "degF", "\N{DEGREE SIGN}C": "degC"}
# "Fixed - Normal": the mode, then the sampling style. Burst arrives with the
# first export that carries it, together with its LoggingMode member.
LOGGING_MODES = {"Fixed": LoggingMode.FIXED}
INTERVAL = re.compile(
    r"^(?P<hours>\d+)\s*hours?\s+(?P<minutes>\d+)\s*minutes?\s+(?P<seconds>\d+)\s*seconds?$"
)
# "2026/07/11 07:00:00 PDT" - the stamp, then the same label the Data header
# declares. Parsed with the label split off, never with a zone-aware format
# code: %Z accepts an abbreviation and then quietly ignores it.
DETAILS_TIME = "%Y/%m/%d %H:%M:%S"

DEVICE_INFO = "Device Info"
DEPLOYMENT_INFO = "Deployment Info"
SERIES_STATISTICS = "Series Statistics"
LOCATION_OFF = "Off"


class HOBOconnectReader:
    """Reads a HOBOconnect export into an ``Extraction``, whatever holds it.

    The shape is injected rather than imported: the same reader runs against a
    corrected ``sources.yaml`` entry without a code change, which is what makes
    the catalogue the description of the format rather than documentation of it.
    One consequence is that this class serves every entry whose tables are
    Onset's - the workbook and its sheets written out as CSV files - because
    the vendor's words are the only thing it actually knows.
    """

    def __init__(self, source_format: SourceFormat) -> None:
        if source_format.details is None:
            raise ValueError(f"{source_format.format_id} declares no details table shape")
        self._format = source_format
        self._details_spec = source_format.details
        self._events_spec = source_format.events

    @property
    def format_id(self) -> str:
        return self._format.format_id

    def read(self, path: Path) -> Extraction:
        """Parse the source. Nothing is trimmed, masked or converted."""
        loaded = read_tables(self._format, path)
        data = parse_data(loaded.tables["data"], self._format.data, cells=loaded.cells)
        details = parse_details(loaded.tables["details"], self._details_spec)
        logged = (
            parse_events(loaded.tables["events"], self._events_spec, cells=loaded.cells)
            if self._events_spec is not None
            else None
        )

        notes = list(data.notes)
        units = self._units(data.unit)
        self._check_declared_unit(details, units)
        published, published_notes = self._statistics(details, units, data.timezone_label)
        events = self._events(logged, data.timezone_label, notes)
        return Extraction(
            format_id=self.format_id,
            timestamps=data.timestamps,
            values=np.asarray(data.values, dtype=np.float64),
            metadata=self._metadata(details, units, data.timezone_label, notes),
            published=published,
            events=events,
            notes=tuple(notes + published_notes),
        )

    def _events(
        self, logged: ParsedEvents | None, label: str | None, notes: list[str]
    ) -> tuple[SourceEvent, ...]:
        """Normalise the log's column names into the canonical vocabulary."""
        if logged is None:
            return ()
        if logged.timezone_label != label:
            raise ValueError(
                f"the event table declares the zone {logged.timezone_label!r} but the data"
                f" table declares {label!r}; two sheets written in different frames would"
                " shift the log against the samples"
            )
        notes.extend(logged.notes)
        return tuple(
            SourceEvent(at=event.at, event_type=_event_type(event.label)) for event in logged.events
        )

    def _units(self, raw: str | None) -> str:
        if raw is None:
            raise ValueError(
                f"{self.format_id} did not capture a unit from the data header, but this"
                " reader has no other statement of one; the catalogue entry is wrong"
            )
        if raw not in UNIT_SYMBOLS:
            known = ", ".join(sorted(UNIT_SYMBOLS))
            raise ValueError(
                f"the data header declares the unit {raw!r}, which this reader does not"
                f" normalise; it knows: {known}"
            )
        return UNIT_SYMBOLS[raw]

    def _check_declared_unit(self, details: DetailsTable, units: str) -> None:
        if details.series is None:
            raise ValueError("the details table declares no series, so its unit cannot be checked")
        declared = self._format.data.value_column.match(details.series)
        if declared is None:
            raise ValueError(
                f"the details series declaration {details.series!r} does not have the shape"
                " sources.yaml gives a value column"
            )
        series_units = self._units(str(declared.group("unit")))
        if series_units != units:
            raise ValueError(
                f"the data header declares {units} but the details series declares"
                f" {series_units}; the export states the unit twice and the parse cannot"
                " honour both"
            )

    def _metadata(
        self, details: DetailsTable, units: str, label: str | None, notes: list[str]
    ) -> ExtractedMetadata:
        location = details.optional(DEPLOYMENT_INFO, "Location")
        if location is not None and location != LOCATION_OFF:
            # No export with Location switched on has been seen, so its format
            # is unverified: guessing at it would invent a position, and
            # ignoring it would lose one. TODO(verify) against a real export.
            notes.append(
                f"Location is {location!r}; the format of a set Location is unverified,"
                " so no position was extracted - supply one if it is needed"
            )
        return ExtractedMetadata(
            product=details.value(DEVICE_INFO, "Product"),
            serial=details.value(DEVICE_INFO, "Serial Number"),
            deployment_number=_int(
                details.value(DEPLOYMENT_INFO, "Deployment Number"), "Deployment Number"
            ),
            interval_s=_interval_seconds(details.value(DEPLOYMENT_INFO, "Logging Interval")),
            units=units,
            source_timezone_label=label,
            firmware=details.optional(DEVICE_INFO, "Firmware Version"),
            logging_mode=_logging_mode(details.value(DEPLOYMENT_INFO, "Logging Mode")),
        )

    def _statistics(
        self, details: DetailsTable, units: str, label: str | None
    ) -> tuple[PublishedStatistics | None, list[str]]:
        published = details.section(SERIES_STATISTICS)
        if not published:
            return None, [
                (
                    "the details table publishes no series statistics,"
                    " so the checksum gate has nothing to reproduce"
                )
            ]
        return (
            PublishedStatistics(
                samples=_int(published["Samples"], "Samples"),
                maximum=_float(published["Max"], "Max"),
                minimum=_float(published["Min"], "Min"),
                average=_float(published["Avg"], "Avg"),
                std_dev=_float(published["Std Dev"], "Std Dev"),
                first_sample_time=_sample_time(published["First Sample Time"], label),
                last_sample_time=_sample_time(published["Last Sample Time"], label),
                units=units,
            ),
            [],
        )


def _event_type(column: str) -> EventType:
    """Normalise an event column heading into the canonical vocabulary."""
    canonical = "_".join(column.lower().split())
    try:
        return EventType(canonical)
    except ValueError as error:
        known = ", ".join(sorted(member.value for member in EventType))
        raise ValueError(
            f"the event table has a {column!r} column, which normalises to {canonical!r};"
            f" the vocabulary holds: {known}. An unrecognised entry in an audit trail is"
            " refused rather than dropped - growing EventType is a one-line diff"
        ) from error


def _int(raw: str, name: str) -> int:
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"the details value for {name} is {raw!r}, not a whole number") from error


def _float(raw: str, name: str) -> float:
    try:
        return float(raw)
    except ValueError as error:
        raise ValueError(f"the details value for {name} is {raw!r}, not a number") from error


def _interval_seconds(raw: str) -> int:
    matched = INTERVAL.match(raw.strip())
    if matched is None:
        raise ValueError(
            f"the details value for Logging Interval is {raw!r}, which does not have the"
            " shape '<n> hour <n> minutes <n> seconds'"
        )
    hours, minutes, seconds = (int(matched.group(part)) for part in ("hours", "minutes", "seconds"))
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        raise ValueError(f"the details value for Logging Interval is {raw!r}, which is no interval")
    return total


def _logging_mode(raw: str) -> LoggingMode:
    mode = raw.split("-", maxsplit=1)[0].strip()
    if mode not in LOGGING_MODES:
        known = ", ".join(sorted(LOGGING_MODES))
        raise ValueError(
            f"the details value for Logging Mode is {raw!r}; this reader normalises: {known}."
            " A mode arrives with the export that carries it, so its timestamps can be"
            " verified rather than assumed"
        )
    return LOGGING_MODES[mode]


def _sample_time(raw: str, label: str | None) -> datetime:
    stamp, _, declared = raw.rpartition(" ")
    if declared != label:
        raise ValueError(
            f"the published sample time {raw!r} declares the zone {declared!r} but the data"
            f" header declares {label!r}; the export states the zone twice and they disagree"
        )
    try:
        # Naive local by construction: the label is checked above, and
        # assemble is where a local stamp becomes UTC.
        return datetime.strptime(stamp, DETAILS_TIME)  # noqa: DTZ007
    except ValueError as error:
        raise ValueError(f"the published sample time {raw!r} is not a readable stamp") from error
