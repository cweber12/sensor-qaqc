"""The record: the minimal view checks see (#2), and the canonical one (#3).

``RecordView`` carries only what the framework needs: the identity key
that selects thresholds (``variable``, a CF ``standard_name``), the
masked series checks compute on, and the scalar facts requirements are
evaluated against. ``CanonicalRecord`` is the concrete thing every
adapter fills and every consumer reads; the conformance battery
constructs synthetic views instead, which is why the protocol exists
separately from the class.

``series`` follows the masking contract (#3, #6): a uniform time grid at
exactly ``dt``, gaps and QC-rejected points as NaN in place - never
dropped, never interpolated. That is why ``n_valid`` exists separately:
significance arithmetic uses ``n_valid``, never ``len()``. (The name is
``series``, not pandas' conventional ``.values``, because ruff's
pandas-vet reads any ``.values`` attribute as the ndarray anti-pattern
and would demand a suppression at every use site.)

The canonical record lives here rather than in ``instruments`` for three
reasons recorded in #3: ``core/synthetic.py`` must construct records and
cannot import ``instruments``; the schema is the vendor-neutral contract
that operator-supplied metadata also fills; and it needs nothing beyond
``core``'s existing allowance. ADR 0007 records the rest of its shape -
native units, the grid contract, and mandatory per-field provenance.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field, fields
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import numpy.typing as npt


class RecordView(Protocol):
    """Structural interface between the framework and any record source."""

    @property
    def variable(self) -> str:
        """CF ``standard_name`` - the key thresholds are resolved under."""
        ...

    @property
    def series(self) -> pd.Series:
        """The observations on a uniform grid at ``dt``, gaps as NaN in place."""
        ...

    @property
    def dt(self) -> timedelta:
        """The sampling interval of the uniform grid."""
        ...

    @property
    def duration(self) -> timedelta:
        """First-to-last span of the grid, gaps included."""
        ...

    @property
    def n_valid(self) -> int:
        """Count of non-NaN observations - the only n statistics may use."""
        ...

    @property
    def gap_fraction(self) -> float:
        """Fraction of grid points that are NaN, in [0, 1]."""
        ...


# A grid needs two points to have a spacing; one sample has no dt to verify.
_MIN_SAMPLES = 2
_MAX_LATITUDE = 90.0
_MAX_LONGITUDE = 180.0


class FieldSource(enum.StrEnum):
    """Where a field's value came from - recorded per field, never inferred.

    #3 splits metadata three ways: authoritative in the file, sometimes in
    the file (position), and never in any file (depth, datum, mounting, the
    in-water window). Only the last is a prompt. Recording the source per
    field is what lets a report say which is which, and what makes "the
    number of prompts shrinks as extractors improve" measurable rather than
    asserted.
    """

    EXTRACTED = "extracted"
    SUPPLIED = "supplied"


class LoggingMode(enum.StrEnum):
    """Normalised logging mode - the adapter maps the vendor string here.

    ``fixed`` is the only member because it is the only mode verified
    against a real export (``Fixed - Normal`` in the pristine HOBOconnect
    workbook). Burst logging exists and matters - after a burst episode the
    next fixed-interval timestamp is computed from the last burst point,
    which is what makes timesteps irregular - but its vendor string is
    unverified, so the member arrives with the export that carries it,
    the same rule ``Channel`` follows.
    """

    FIXED = "fixed"


class EventType(enum.StrEnum):
    """Normalised event-log vocabulary, closed on purpose.

    A free string would let ``Power Warn`` and ``power_warn`` coexist in one
    archive as two different events. The first three are what the pristine
    export's log contains; the rest arrive with the parser that produces them
    and the synthetic sheets that exercise them, because no real export on
    hand has ever logged one.

    What an event means for a verdict is #7's decision, with an injected,
    provenance-carrying policy. Ingest only surfaces them.
    """

    STARTED = "started"
    HOST_CONNECTED = "host_connected"
    END_OF_FILE = "end_of_file"
    POWER_WARN = "power_warn"
    SAFE_SHUTDOWN = "safe_shutdown"
    WATER_DETECT = "water_detect"
    NEW_INTERVAL = "new_interval"


@dataclass(frozen=True)
class LoggedEvent:
    """One entry from the source's event log, in canonical terms."""

    at: pd.Timestamp
    event_type: EventType

    def __post_init__(self) -> None:
        if self.at.tz is None or str(self.at.tz) != "UTC":
            raise ValueError(f"event timestamps must be tz-aware UTC, got {self.at!r}")


def to_uniform_grid(
    timestamps: pd.DatetimeIndex | Sequence[pd.Timestamp],
    values: Sequence[float] | npt.NDArray[np.float64],
    *,
    interval_s: int,
) -> pd.Series:
    """Place parsed samples on the true first-to-last grid, gaps as NaN.

    The grid spans the first to the last parsed timestamp at exactly
    ``interval_s``; missing samples become NaN in place. Nothing is filled
    and nothing is spliced: filling manufactures increment autocorrelation
    of exactly +1.0, the statistic #7 measures, and splicing breaks the
    k*dt lag relationship every spectral method assumes.

    Timestamps that do not land on the grid, repeat, or run backwards are
    refused rather than reindexed away. Dropping one is how a sample
    disappears between the file and the analysis - which is the failure the
    Details checksum gate exists to catch, so the parse must not cause it.
    """
    if interval_s <= 0:
        raise ValueError(f"interval_s must be a positive number of seconds, got {interval_s}")
    index = pd.DatetimeIndex(timestamps)
    if len(index) != len(values):
        raise ValueError(f"got {len(index)} timestamps and {len(values)} values")
    if len(index) < _MIN_SAMPLES:
        raise ValueError(f"a grid needs at least two samples, got {len(index)}")
    if index.tz is None or str(index.tz) != "UTC":
        raise ValueError(f"timestamps must be tz-aware UTC, got tz={index.tz!r}")
    if index.has_duplicates:
        duplicated = index[index.duplicated()]
        raise ValueError(f"duplicate timestamps in the parse: {list(duplicated[:3])}")
    if not index.is_monotonic_increasing:
        raise ValueError("timestamps must be strictly increasing; the parse is out of order")

    step = pd.Timedelta(seconds=interval_s)
    offsets = (index - index[0]) // step
    off_grid = index[0] + offsets * step != index
    if off_grid.any():
        raise ValueError(
            f"timestamp {index[off_grid][0]} is not on the {interval_s} s grid that starts"
            f" at {index[0]}; refusing to drop it"
        )
    grid = pd.date_range(index[0], index[-1], freq=step, tz="UTC")
    return pd.Series(np.asarray(values, dtype=float), index=index).reindex(grid)


# Category 3 of #3's three-way metadata split: no file can supply these, so
# only an operator can. Position is category 2 - in the file sometimes - and
# is reported by its absent provenance rather than by this tuple.
OPERATOR_FIELDS = (
    "depth_m",
    "depth_datum",
    "mounting",
    "in_water_start",
    "in_water_end",
)


@dataclass(frozen=True)
class CanonicalRecord:
    """One record, however it was read: the contract adapters fill (#3).

    ``series`` is in the source's **native unit**, named by ``units`` as a
    UDUNITS-2 symbol; ADR 0007 records why it is not converted at ingest.
    ``interval_s`` is the single source of truth for the grid - ``dt`` is
    derived from it, so a declared interval and the grid it was built on
    cannot disagree.

    ``variable`` is a CF ``standard_name`` and is *supplied*: no export
    states that a logger was in sea water rather than in air, so extraction
    cannot know it. ``units`` is extracted.

    Timestamps are tz-aware UTC. ``source_timezone_label`` keeps the
    export's own declaration (``PDT`` from the ``Date-Time (PDT)`` header)
    as provenance, because an abbreviation is not a zone and the record
    must not pretend it resolved one it was never given.
    """

    variable: str
    units: str
    series: pd.Series
    interval_s: int
    source_timezone_label: str
    product: str
    serial: str
    deployment_number: int
    provenance: Mapping[str, FieldSource]
    firmware: str | None = None
    logging_mode: LoggingMode | None = None
    latitude: float | None = None
    longitude: float | None = None
    depth_m: float | None = None
    depth_datum: str | None = None
    mounting: str | None = None
    in_water_start: pd.Timestamp | None = None
    in_water_end: pd.Timestamp | None = None
    events: tuple[LoggedEvent, ...] = field(default=())

    def __post_init__(self) -> None:
        self._validate_text()
        self._validate_grid()
        self._validate_position()
        self._validate_operator_fields()
        self._validate_provenance()
        # Read-only from here on: a plain dict handed in by a caller stays
        # writable through the record, and provenance that can be edited
        # after construction is provenance nobody can rely on.
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    def _validate_text(self) -> None:
        for name in ("variable", "units", "source_timezone_label", "product", "serial"):
            value = getattr(self, name)
            if not value.strip():
                raise ValueError(f"a canonical record requires a non-empty {name}")
        if self.interval_s <= 0:
            raise ValueError(
                f"interval_s must be a positive number of seconds, got {self.interval_s}"
            )
        if self.deployment_number < 1:
            raise ValueError(f"deployment_number must be >= 1, got {self.deployment_number}")

    def _validate_grid(self) -> None:
        index = self.series.index
        if len(index) < _MIN_SAMPLES:
            raise ValueError(f"a record needs at least two samples, got {len(index)}")
        if index.tz is None or str(index.tz) != "UTC":
            raise ValueError(f"the series index must be tz-aware UTC, got tz={index.tz!r}")
        step = pd.Timedelta(seconds=self.interval_s)
        steps = index[1:] - index[:-1]
        if not (steps == step).all():
            raise ValueError(
                f"the series must be on a uniform grid at dt={self.interval_s} s;"
                f" got steps {sorted(set(steps))[:3]} - build it with to_uniform_grid"
            )

    def _validate_position(self) -> None:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude arrive together or not at all")
        if self.latitude is not None and abs(self.latitude) > _MAX_LATITUDE:
            raise ValueError(f"latitude must be within +/-90 degrees, got {self.latitude}")
        if self.longitude is not None and abs(self.longitude) > _MAX_LONGITUDE:
            raise ValueError(f"longitude must be within +/-180 degrees, got {self.longitude}")

    def _validate_operator_fields(self) -> None:
        if self.depth_m is not None and (not math.isfinite(self.depth_m) or self.depth_m < 0):
            raise ValueError(
                f"depth_m must be a finite depth below the surface, got {self.depth_m}"
            )
        start, end = self.in_water_start, self.in_water_end
        if start is not None and end is not None and start >= end:
            raise ValueError(f"in_water_start {start} is not before in_water_end {end}")

    def _validate_provenance(self) -> None:
        provenanced = {
            f.name for f in fields(self) if f.name not in ("series", "provenance", "events")
        }
        for name in self.provenance:
            if name not in provenanced:
                raise ValueError(f"provenance names {name!r}, which is not a field of the record")
            if getattr(self, name) is None:
                raise ValueError(
                    f"provenance names {name!r}, which is not populated - a source"
                    " for a value nobody supplied would be reported as fact"
                )
        missing = sorted(
            name
            for name in provenanced
            if getattr(self, name) is not None and name not in self.provenance
        )
        if missing:
            raise ValueError(f"no provenance for populated fields: {missing}")

    @property
    def dt(self) -> timedelta:
        return timedelta(seconds=self.interval_s)

    @property
    def deployment_id(self) -> str:
        """``{serial}-{deployment_number}`` - the identity key from #1."""
        return f"{self.serial}-{self.deployment_number}"

    @property
    def duration(self) -> timedelta:
        span: timedelta = (self.series.index[-1] - self.series.index[0]).to_pytimedelta()
        return span

    @property
    def n_valid(self) -> int:
        return int(self.series.notna().sum())

    @property
    def gap_fraction(self) -> float:
        return 1.0 - self.n_valid / len(self.series)

    @property
    def missing_operator_fields(self) -> tuple[str, ...]:
        """Fields no file can ever supply that this record still lacks."""
        return tuple(name for name in OPERATOR_FIELDS if getattr(self, name) is None)
