"""Body of ``sensor-qaqc inspect`` (#3, ADR 0002).

``inspect`` runs on a file straight off a logger, before any deployment entry
exists, so it asks nobody for anything: it reports what the source states, what
the checksum gate made of it, and **names** the canonical fields only an
operator can supply. Prompting is not this command's job, and inventing a
value to get a record built would defeat the point of recording provenance
per field.

Exit codes follow ADR 0002. A refused checksum gate is exit 1 - not because
the record failed a check, but because the parse could not be trusted, which
is "the tool could not produce a result". The report still prints: an operator
needs to see which statistics disagreed, and the mismatches go to stderr as
well so a cron line can capture the reason without parsing stdout.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from sensor_qaqc.core.records import to_uniform_grid
from sensor_qaqc.instruments.checksum import verify_published_statistics
from sensor_qaqc.instruments.extraction import outstanding_fields
from sensor_qaqc.instruments.readers import reader_for
from sensor_qaqc.instruments.sources import load_source_catalogue
from sensor_qaqc.instruments.timezones import to_utc

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from sensor_qaqc.instruments.extraction import Extraction

# ADR 0002, named locally rather than imported from __main__, which imports
# this module to wire the handler.
_EXIT_PRODUCED = 0
_EXIT_NO_RESULT = 1


def render(path: Path, extraction: Extraction, gate_report: str) -> str:
    """Render the whole report: what the source said, and what it did not."""
    metadata = extraction.metadata
    lines = [
        f"source: {path.as_posix()}",
        f"format: {extraction.format_id}",
        "",
        gate_report,
        "",
        (
            f"logger: {_or_unstated(metadata.product)} serial {_or_unstated(metadata.serial)}"
            f", deployment {_or_unstated(metadata.deployment_number)}"
            f", firmware {_or_unstated(metadata.firmware)}"
        ),
        (
            f"logging: mode {_or_unstated(metadata.logging_mode)}"
            f", interval {_or_unstated(metadata.interval_s)} s"
            f", stamps in {_or_unstated(metadata.source_timezone_label)}"
        ),
        (
            "variable: not stated by any source - the operator's to declare"
            f" (units: {_or_unstated(metadata.units)}, extracted)"
        ),
        f"position: {_position(extraction)}",
        *_span(extraction),
        f"events: {_events(extraction)}",
    ]
    if extraction.notes:
        lines += ["notes:", *(f"  - {note}" for note in extraction.notes)]
    lines += [
        "still needed from an operator:",
        *(f"  - {name}" for name in outstanding_fields(extraction)),
    ]
    return "\n".join(lines)


def _or_unstated(value: object) -> str:
    return "not stated" if value is None else str(value)


def _position(extraction: Extraction) -> str:
    metadata = extraction.metadata
    if metadata.latitude is None or metadata.longitude is None:
        return "not stated by this source - supply it if a check needs one"
    return f"{metadata.latitude}, {metadata.longitude}"


def _events(extraction: Extraction) -> str:
    if not extraction.events:
        return "none logged"
    counted: dict[str, int] = {}
    for event in extraction.events:
        counted[event.event_type.value] = counted.get(event.event_type.value, 0) + 1
    summary = ", ".join(f"{name} x{count}" for name, count in sorted(counted.items()))
    return f"{len(extraction.events)} ({summary})"


def _span(extraction: Extraction) -> list[str]:
    """Return the parse, then the grid it lands on - or why it cannot be built."""
    stamps = extraction.timestamps
    label = extraction.metadata.source_timezone_label
    lines = [
        (f"samples: {len(stamps)} parsed, {stamps[0]} to {stamps[-1]} ({_or_unstated(label)})")
        if stamps
        else "samples: none parsed"
    ]
    interval = extraction.metadata.interval_s
    if interval is None or label is None:
        lines.append(
            "grid: not computed - it needs the logging interval and the zone label,"
            " and this source states neither"
        )
        return lines
    readings = extraction.values
    series = to_uniform_grid(to_utc(stamps, label), readings, interval_s=interval)
    valid = int(series.notna().sum())
    span = series.index[-1] - series.index[0]
    lines.append(
        f"grid: {len(series)} points at {interval} s over {span}"
        f", n_valid {valid}, gap_fraction {1.0 - valid / len(series):.4f}"
    )
    return lines


def inspect_command(args: argparse.Namespace) -> int:
    """Parse the source at ``args.file``, gate it, and report."""
    path: Path = args.file
    try:
        reader = reader_for(path, load_source_catalogue())
        extraction = reader.read(path)
        outcome = verify_published_statistics(extraction)
        report = render(path, extraction, outcome.report)
    except (ValueError, LookupError, OSError) as error:
        # Every refusal in ingest is one of these, and each one already says
        # what it could not do; the exit code says the tool produced nothing.
        sys.stderr.write(f"sensor-qaqc: {error}\n")
        return _EXIT_NO_RESULT
    print(report)
    if outcome.refused:
        sys.stderr.write(
            "sensor-qaqc: the parse does not reproduce the statistics this source"
            f" publishes:\n{chr(10).join(f'  {m}' for m in outcome.mismatches)}\n"
        )
        return _EXIT_NO_RESULT
    return _EXIT_PRODUCED
