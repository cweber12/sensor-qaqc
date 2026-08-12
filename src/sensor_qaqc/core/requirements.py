"""Requirements are data the runner evaluates before compute (#2).

Never ``if n < 50: return INCONCLUSIVE`` inside a check: a requirement
written as code is invisible to the battery, to ``checks list`` and to
the report. Declared as data, the runner refuses admission *before*
compute and generates the INCONCLUSIVE reason mechanically - naming the
requirement and the actual value - so it cannot be omitted or worded
into vagueness.

The vocabulary grows with the PRDs that need it (#5's ``station_tier``
arrives with the station catalogue). Anything a requirement cannot
express - something only computation reveals - remains a check's right
to return as INCONCLUSIVE from compute, where a reason is mandatory by
construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import timedelta

    from sensor_qaqc.core.records import RecordView


class Requirement(Protocol):
    """One admissibility condition, evaluable against any record view."""

    def unmet_reason(self, record: RecordView) -> str | None:
        """None when met; otherwise the generated INCONCLUSIVE reason."""
        ...


@dataclass(frozen=True)
class MinValidSamples:
    """At least ``n`` non-NaN observations - n_valid, never len() (#3)."""

    n: int

    def __post_init__(self) -> None:
        if self.n < 1:
            msg = f"MinValidSamples requires n >= 1, got {self.n}"
            raise ValueError(msg)

    def unmet_reason(self, record: RecordView) -> str | None:
        if record.n_valid >= self.n:
            return None
        return f"n_valid={record.n_valid} < required {self.n} (MinValidSamples)"


@dataclass(frozen=True)
class MinDuration:
    """The grid spans at least this long, gaps included."""

    duration: timedelta

    def unmet_reason(self, record: RecordView) -> str | None:
        if record.duration >= self.duration:
            return None
        return f"duration={record.duration} < required {self.duration} (MinDuration)"


@dataclass(frozen=True)
class MaxGapFraction:
    """No more than this fraction of the grid is missing."""

    fraction: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.fraction <= 1.0:
            msg = f"MaxGapFraction requires a fraction in [0, 1], got {self.fraction}"
            raise ValueError(msg)

    def unmet_reason(self, record: RecordView) -> str | None:
        if record.gap_fraction <= self.fraction:
            return None
        return (
            f"gap_fraction={record.gap_fraction:.3f} > allowed {self.fraction:.3f} (MaxGapFraction)"
        )
