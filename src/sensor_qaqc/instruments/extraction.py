"""The adapter seam: what a reader produces, and the one way it becomes a record.

A reader's whole job is to produce an :class:`Extraction` - the raw parse, the
metadata the file states, the statistics the format publishes (if any) and the
event log, all in the source's own terms. Everything about *becoming* a
canonical record happens once, in :func:`assemble`: localising the timestamps,
the grid, the unit check, and the provenance mapping. That is what makes
"adding a format touches only the adapter layer" true rather than aspirational,
and it is why the canonical schema - not the CLI - is the contract.

**Where a value may come from.** #3 splits metadata three ways and this module
encodes the split as types rather than as a convention:

- Facts the file states (model, serial, deployment number, interval, unit, the
  declared zone label) live on :class:`ExtractedMetadata`. They also appear on
  :class:`SuppliedMetadata`, because a format that states none of them - a bare
  CSV - still has to reach the same canonical shape. The rule is *the file
  wins*: a supplied value the source contradicts is refused, never silently
  preferred, and a supplied value the source agrees with is still recorded as
  extracted. Typing ``MX2204`` by hand where the file says it is strictly worse
  than reading it, because a typo applies the wrong device specs.
- Position is on both, same rule: HOBOconnect has a ``Location`` field and this
  deployment had it ``Off``.
- Depth, datum, mounting and the in-water window are supplied only. No file can
  state them, so nothing extracts them.

Firmware and logging mode are extracted only: an operator typing a firmware
version is inventing provenance, not supplying it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from sensor_qaqc.core.records import (
    OPERATOR_FIELDS,
    CanonicalRecord,
    EventType,
    FieldSource,
    LoggedEvent,
    LoggingMode,
    to_uniform_grid,
)
from sensor_qaqc.instruments.timezones import to_utc

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    import numpy as np
    import numpy.typing as npt
    import pandas as pd

    from sensor_qaqc.instruments.sensors import SensorCatalogue

# Resolved from the source first, from the operator only where it is silent.
RESOLVED_REQUIRED = (
    "product",
    "serial",
    "deployment_number",
    "interval_s",
    "units",
    "source_timezone_label",
)
RESOLVED_OPTIONAL = ("latitude", "longitude")
EXTRACTED_ONLY = ("firmware", "logging_mode")


class IncompleteRecordError(ValueError):
    """The record cannot be built: fields nobody stated and nobody supplied."""


class ConflictingMetadataError(ValueError):
    """A supplied value contradicts what the source states. The file wins."""


@dataclass(frozen=True)
class PublishedStatistics:
    """Statistics the vendor computed independently of us, as published.

    The checksum gate reproduces these from the raw parse (#3 slice 4). They
    are published as 2-decimal strings, so the gate compares within a
    tolerance rather than for equality - which is why they arrive parsed but
    the tolerance lives with the gate, not here.
    """

    samples: int
    maximum: float
    minimum: float
    average: float
    std_dev: float
    # In the source's own frame, like every other stamp on an Extraction: the
    # gate compares them against the parse without either side being moved.
    first_sample_time: datetime
    last_sample_time: datetime
    units: str


@dataclass(frozen=True)
class ExtractedMetadata:
    """What the source itself states. Every field optional: formats differ."""

    product: str | None = None
    serial: str | None = None
    deployment_number: int | None = None
    interval_s: int | None = None
    units: str | None = None
    source_timezone_label: str | None = None
    firmware: str | None = None
    logging_mode: LoggingMode | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class SuppliedMetadata:
    """What an operator provides. ``variable`` is always theirs to state.

    No export says a logger was in sea water rather than in air, so the CF
    ``standard_name`` cannot be extracted - it is the operator's assertion
    about the deployment, and #2 keys thresholds by it.
    """

    variable: str
    product: str | None = None
    serial: str | None = None
    deployment_number: int | None = None
    interval_s: int | None = None
    units: str | None = None
    source_timezone_label: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    depth_m: float | None = None
    depth_datum: str | None = None
    mounting: str | None = None
    in_water_start: pd.Timestamp | None = None
    in_water_end: pd.Timestamp | None = None


@dataclass(frozen=True)
class SourceEvent:
    """One event the source logged, in canonical terms and its own frame.

    The type is canonical because normalising vendor words is the reader's
    job; the timestamp is not yet UTC because resolving a declared local label
    needs the label, which for some formats only an operator can give.
    """

    at: datetime
    event_type: EventType


@dataclass(frozen=True)
class Extraction:
    """One source, parsed: the raw samples and everything the file said.

    ``timestamps``/``values`` are the *raw* parse, before gridding - the
    checksum gate runs on exactly this, because the Details statistics
    describe everything the logger recorded, not the subset that survives any
    later trim or mask.

    **Timestamps stay in the source's own frame**: naive local, with the label
    the source declared carried separately on the metadata. A bare CSV states
    no zone at all, so its label is supplied - and supplied metadata does not
    exist yet when a reader runs. Localising in :func:`assemble` is therefore
    not a preference but the only place both halves are in hand.

    ``notes`` is the channel for anything skipped, empty or unusable: blank
    rows passed over, a field present but in an unverified format. Without it
    a reader's only options are to refuse the file or to stay quiet, and
    staying quiet is how a parse loses something nobody hears about.
    """

    format_id: str
    timestamps: tuple[datetime, ...]
    values: npt.NDArray[np.float64]
    metadata: ExtractedMetadata
    published: PublishedStatistics | None = None
    events: tuple[SourceEvent, ...] = ()
    notes: tuple[str, ...] = ()


class SourceReader(Protocol):
    """A format adapter: file in, extraction out. It builds no record."""

    @property
    def format_id(self) -> str:
        """The ``sources.yaml`` key whose shape this reader implements."""
        ...

    def read(self, path: Path) -> Extraction:
        """Parse the source's tables. Never trims, masks or converts units."""
        ...


def outstanding_fields(extraction: Extraction) -> tuple[str, ...]:
    """Canonical fields this source cannot state, so an operator must.

    What ``inspect`` names rather than asks for: the required facts the source
    left unsaid, plus the ones no file ever carries. This is the number the
    PRD's "prompts shrink as extractors improve" claim is measured by, so it
    is computed from the extraction rather than written down anywhere.
    """
    unsaid = tuple(name for name in RESOLVED_REQUIRED if getattr(extraction.metadata, name) is None)
    return (*unsaid, "variable", *OPERATOR_FIELDS)


def _reconcile(
    extraction: Extraction, supplied: SuppliedMetadata
) -> tuple[dict[str, Any], dict[str, FieldSource]]:
    """Fields either side may state: the file wins, a contradiction refuses."""
    # dict[str, Any] on purpose: the loop is generic so that provenance is
    # produced mechanically rather than hand-written per field, and the record
    # re-validates every value it is handed.
    resolved: dict[str, Any] = {}
    provenance: dict[str, FieldSource] = {}
    conflicts: list[str] = []
    missing: list[str] = []

    for name in RESOLVED_REQUIRED + RESOLVED_OPTIONAL:
        stated = getattr(extraction.metadata, name)
        given = getattr(supplied, name)
        if stated is not None and given is not None and stated != given:
            conflicts.append(f"{name}: supplied {given!r}, but the source states {stated!r}")
        elif stated is not None or given is not None:
            resolved[name] = stated if stated is not None else given
            provenance[name] = FieldSource.EXTRACTED if stated is not None else FieldSource.SUPPLIED
        elif name in RESOLVED_REQUIRED:
            missing.append(name)

    if conflicts:
        raise ConflictingMetadataError(
            "the source contradicts what was supplied - "
            + "; ".join(conflicts)
            + ". The file is authoritative; correct the supplied value."
        )
    if missing:
        raise IncompleteRecordError(
            f"nothing states {missing} and nothing supplied them"
            f" (format {extraction.format_id!r}); the record cannot be built."
        )
    return resolved, provenance


def _resolve(
    extraction: Extraction, supplied: SuppliedMetadata
) -> tuple[dict[str, Any], dict[str, FieldSource]]:
    """Reconcile stated and supplied metadata, recording where each came from."""
    resolved, provenance = _reconcile(extraction, supplied)

    for name in EXTRACTED_ONLY:
        stated = getattr(extraction.metadata, name)
        if stated is not None:
            resolved[name] = stated
            provenance[name] = FieldSource.EXTRACTED

    for name in OPERATOR_FIELDS:
        given = getattr(supplied, name)
        if given is not None:
            resolved[name] = given
            provenance[name] = FieldSource.SUPPLIED

    resolved["variable"] = supplied.variable
    provenance["variable"] = FieldSource.SUPPLIED
    return resolved, provenance


def assemble(
    extraction: Extraction,
    supplied: SuppliedMetadata,
    *,
    sensors: SensorCatalogue,
) -> CanonicalRecord:
    """Turn any extraction plus operator input into the canonical record.

    The catalogue is injected rather than imported so the unit check is
    testable without the packaged file, the same discipline thresholds follow.
    """
    resolved, provenance = _resolve(extraction, supplied)
    spec = sensors.for_product(resolved["product"])
    if resolved["units"] not in spec.native_units.value:
        known = ", ".join(sorted(spec.native_units.value))
        raise ValueError(
            f"the source declares {resolved['units']!r}, which {spec.product} does not"
            f" report; sensors.yaml lists: {known}. Refusing to guess the scale."
        )
    label = resolved["source_timezone_label"]
    series = to_uniform_grid(
        to_utc(extraction.timestamps, label),
        extraction.values,
        interval_s=resolved["interval_s"],
    )
    events = to_utc([event.at for event in extraction.events], label) if extraction.events else []
    return CanonicalRecord(
        series=series,
        events=tuple(
            LoggedEvent(at=when, event_type=event.event_type)
            for event, when in zip(extraction.events, events, strict=True)
        ),
        provenance=provenance,
        **resolved,
    )
