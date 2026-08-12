"""Requirements generate their own INCONCLUSIVE reasons, naming the actual value (#2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import pandas as pd
import pytest

from sensor_qaqc.core.checks import Channel, Domain
from sensor_qaqc.core.requirements import MaxGapFraction, MinDuration, MinValidSamples


@dataclass(frozen=True)
class FakeRecord:
    """The smallest thing satisfying RecordView, for exercising requirements."""

    variable: str = "sea_water_temperature"
    series: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    dt: timedelta = timedelta(minutes=6)
    duration: timedelta = timedelta(days=21)
    n_valid: int = 5040
    gap_fraction: float = 0.0


def test_met_requirements_return_none() -> None:
    record = FakeRecord()
    assert MinValidSamples(n=50).unmet_reason(record) is None
    assert MinDuration(duration=timedelta(days=15)).unmet_reason(record) is None
    assert MaxGapFraction(fraction=0.3).unmet_reason(record) is None


def test_unmet_reasons_name_the_requirement_and_the_actual_value() -> None:
    record = FakeRecord(n_valid=34, duration=timedelta(days=3), gap_fraction=0.42)

    reason = MinValidSamples(n=50).unmet_reason(record)
    assert reason == "n_valid=34 < required 50 (MinValidSamples)"

    reason = MinDuration(duration=timedelta(days=15)).unmet_reason(record)
    assert reason is not None
    assert "3 days" in reason
    assert "15 days" in reason
    assert "MinDuration" in reason

    reason = MaxGapFraction(fraction=0.30).unmet_reason(record)
    assert reason == "gap_fraction=0.420 > allowed 0.300 (MaxGapFraction)"


def test_boundaries_count_as_met() -> None:
    # Requirements are floors/ceilings, not strict inequalities: exactly-at
    # the declared value is admissible, so the declaration reads literally.
    record = FakeRecord(n_valid=50, duration=timedelta(days=15), gap_fraction=0.30)
    assert MinValidSamples(n=50).unmet_reason(record) is None
    assert MinDuration(duration=timedelta(days=15)).unmet_reason(record) is None
    assert MaxGapFraction(fraction=0.30).unmet_reason(record) is None


def test_nonsense_declarations_are_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="n >= 1"):
        MinValidSamples(n=0)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        MaxGapFraction(fraction=1.5)


def test_the_vocabulary_enums_are_closed_and_lowercase() -> None:
    assert [d.value for d in Domain] == ["plausibility", "integrity", "coherence"]
    assert "spectral" in {c.value for c in Channel}
    # Channel values are the strings results.json will carry; all lowercase
    # snake so a case typo cannot mint a fake independent channel.
    assert all(c.value == c.value.lower() for c in Channel)
