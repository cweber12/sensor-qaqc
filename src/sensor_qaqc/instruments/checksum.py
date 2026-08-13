"""The checksum gate: reproduce the statistics the vendor published (#3).

The export carries five numbers Onset computed independently of us - Samples,
Max, Min, Avg, Std Dev - plus the first and last sample time. Recomputing them
from our parse checks column selection, unit handling, header offset, timezone
handling and row dropping in one arithmetic pass. It is the highest
value-per-line item in this PRD, and it earns that by being about *our* code:
the vendor's numbers are the control.

**It runs on the raw parse**, before any trim or mask. Details describes
everything the logger recorded, not the subset that survives analysis - the
committed corrupt fixture is a copy of the export with its seven out-of-water
samples trimmed away in a spreadsheet, and gating after a trim would bless
exactly that.

**Tolerance follows from publication, not from taste.** The statistics are
published as 2-decimal *strings*, so any computed value within half of the last
place is the same published number. Comparison is by that tolerance rather than
by ``round()``, whose banker's rounding false-fails on a .xx5 tie. Samples and
the sample times are compared exactly - they are counts and instants, and there
is nothing to round.

**The standard deviation is the population one** (ddof = 0): the statistics
describe the whole record, which is a census rather than a sample of some
larger population. Onset does not say which it uses; at n = 3029 the two differ
by 0.0004, far inside the tolerance, so the choice cannot decide an outcome on
a record of this length. A test pins that inertness rather than assuming it.

**A format that publishes nothing is not a pass.** A bare CSV has no statistics
to reproduce, so the outcome says so explicitly and carries that into the run's
provenance. Silence would be indistinguishable from a gate that ran.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt
    import pandas as pd

    from sensor_qaqc.instruments.extraction import Extraction, PublishedStatistics

# Decimal places the export publishes its statistics to, and the tolerance that
# follows: half of the last place. Derived, so the number cannot drift from the
# fact that justifies it.
PUBLISHED_DECIMALS = 2
PUBLISHED_TOLERANCE = 0.5 * 10.0**-PUBLISHED_DECIMALS


@dataclass(frozen=True)
class StatisticCheck:
    """One published statistic against the one we computed."""

    name: str
    published: str
    computed: str
    agrees: bool

    def __str__(self) -> str:
        verdict = "matches" if self.agrees else "DISAGREES with"
        return f"{self.name}: computed {self.computed} {verdict} published {self.published}"


@dataclass(frozen=True)
class GateOutcome:
    """What the gate did, and why - never a bare pass/fail.

    ``applicable`` is False where the format publishes no statistics; that is
    not a pass, and ``reason`` says so. ``refused`` is True only when the gate
    ran and something disagreed.
    """

    format_id: str
    applicable: bool
    reason: str
    checks: tuple[StatisticCheck, ...]

    @property
    def mismatches(self) -> tuple[StatisticCheck, ...]:
        return tuple(check for check in self.checks if not check.agrees)

    @property
    def refused(self) -> bool:
        return self.applicable and bool(self.mismatches)

    @property
    def report(self) -> str:
        """Every statistic, both numbers, and what it means - for an operator."""
        if not self.applicable:
            return f"{self.format_id}: {self.reason}"
        head = (
            f"{self.format_id}: {len(self.mismatches)} of {len(self.checks)} published"
            f" statistics could not be reproduced from the parse"
            if self.mismatches
            else f"{self.format_id}: all {len(self.checks)} published statistics reproduced"
        )
        return "\n".join([head, *(f"  {check}" for check in self.checks)])


def verify_published_statistics(extraction: Extraction) -> GateOutcome:
    """Reproduce the published statistics from the raw parse, or say why not."""
    published = extraction.published
    if published is None:
        return GateOutcome(
            format_id=extraction.format_id,
            applicable=False,
            reason=(
                "no vendor statistics in this source, so the gate is not applicable;"
                " nothing was verified about the parse"
            ),
            checks=(),
        )
    readings = np.asarray(extraction.values, dtype=np.float64)
    finite = readings[np.isfinite(readings)]
    if finite.size == 0:
        return GateOutcome(
            format_id=extraction.format_id,
            applicable=True,
            reason="the parse produced no readings at all",
            checks=(StatisticCheck("readings", str(published.samples), "0", agrees=False),),
        )
    return GateOutcome(
        format_id=extraction.format_id,
        applicable=True,
        reason="",
        checks=_checks(extraction, published, finite),
    )


def _checks(
    extraction: Extraction,
    published: PublishedStatistics,
    finite: npt.NDArray[np.float64],
) -> tuple[StatisticCheck, ...]:
    samples = len(extraction.timestamps)
    stamps: pd.DatetimeIndex = extraction.timestamps
    return (
        _exact("samples", published.samples, samples),
        _within("maximum", published.maximum, float(finite.max())),
        _within("minimum", published.minimum, float(finite.min())),
        _within("average", published.average, float(finite.mean())),
        # Population, per the module docstring: a census, not a sample.
        _within("std_dev", published.std_dev, float(finite.std(ddof=0))),
        _exact("first_sample_time", published.first_sample_time, stamps[0]),
        _exact("last_sample_time", published.last_sample_time, stamps[-1]),
    )


def _within(name: str, published: float, computed: float) -> StatisticCheck:
    return StatisticCheck(
        name=name,
        published=f"{published:.{PUBLISHED_DECIMALS}f}",
        computed=f"{computed:.{PUBLISHED_DECIMALS + 3}f}",
        agrees=math.isfinite(computed) and abs(computed - published) <= PUBLISHED_TOLERANCE,
    )


def _exact(name: str, published: object, computed: object) -> StatisticCheck:
    return StatisticCheck(
        name=name,
        published=str(published),
        computed=str(computed),
        agrees=bool(published == computed),
    )
