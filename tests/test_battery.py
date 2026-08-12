"""A deliberately broken check fails the battery; a sane one passes it (#2).

The acceptance item is literal: every battery case class is proven able
to catch its target failure, using dummy checks built to fail exactly
one way each. The well-behaved dummy measures lag-1 memory against the
value AR(1) physics predicts for the record's dt, so it discriminates
all four negative controls, tracks decimation honestly, and goes
INCONCLUSIVE - with a reason - where the data cannot answer.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from sensor_qaqc.core.battery import (
    DECIMATION_FACTORS,
    FULL_REALISATIONS,
    GAP_FRACTIONS,
    SMOKE_REALISATIONS,
    BatteryError,
    FarMeasurement,
    _binomial_critical,
    assert_full_far,
    assert_smoke_far,
    decimation_ladder,
    determinism,
    gap_robustness,
    negative_controls,
    red_noise_false_alarms,
    run_full_battery,
    run_smoke_battery,
)
from sensor_qaqc.core.checks import Channel, Domain
from sensor_qaqc.core.registry import Registry
from sensor_qaqc.core.requirements import MinValidSamples
from sensor_qaqc.core.synthetic import (
    AR1_TAU,
    BATTERY_DT,
    NEGATIVE_CONTROLS,
    decimate,
    derive_seed,
    red_noise,
    with_gaps,
)
from sensor_qaqc.core.thresholds import Provenance, Threshold
from sensor_qaqc.core.verdicts import CheckResult, Verdict

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from sensor_qaqc.core.checks import Check
    from sensor_qaqc.core.records import RecordView
    from sensor_qaqc.core.requirements import Requirement
    from sensor_qaqc.core.thresholds import ThresholdLike

NO_THRESHOLDS: dict[str, Threshold] = {}
R1_PASS_BAND = 0.15
R1_MARGINAL_BAND = 0.25
R1_CEILING = 0.98


def _memory_band(
    record: RecordView,
    thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - dummy needs none
    capabilities: Mapping[str, object],  # noqa: ARG001 - dummy consumes none
) -> CheckResult:
    """PASS iff lag-1 memory sits where AR(1) physics puts it for this dt."""
    # nunique, not std() == 0.0: a constant series can carry float summation
    # noise (std ~1e-15 for some levels), and NaN autocorr past the guard
    # would decay into an arbitrary verdict plus a numpy divide warning.
    if record.series.dropna().nunique() <= 1:
        return CheckResult(
            verdict=Verdict.INCONCLUSIVE, reason="zero variance: memory is undefined"
        )
    if record.dt > AR1_TAU:
        return CheckResult(
            verdict=Verdict.INCONCLUSIVE,
            reason=f"dt={record.dt} exceeds tau={AR1_TAU}: lag-1 memory unresolvable",
        )
    r1 = float(record.series.autocorr(lag=1))
    expected = math.exp(-record.dt / AR1_TAU)
    metrics = {"r1": r1, "expected_r1": expected}
    if r1 > R1_CEILING:
        return CheckResult(
            verdict=Verdict.FAIL, metrics=metrics, reason="unphysical memory (trend-like)"
        )
    error = abs(r1 - expected)
    if error <= R1_PASS_BAND:
        return CheckResult(verdict=Verdict.PASS, metrics=metrics)
    if error <= R1_MARGINAL_BAND:
        return CheckResult(verdict=Verdict.MARGINAL, metrics=metrics, reason="memory off-band")
    return CheckResult(verdict=Verdict.FAIL, metrics=metrics, reason="memory far off-band")


def _bound(rate: float = 0.05) -> Threshold:
    return Threshold(
        value=rate,
        unit="1",
        provenance=Provenance(source="test dummy", rationale="synthetic acceptance check"),
    )


@dataclass(frozen=True)
class DummyCheck:
    check_id: str = "memory_band"
    domain: Domain = Domain.INTEGRITY
    channel: Channel = Channel.TEMPORAL
    requirements: tuple[Requirement, ...] = (MinValidSamples(n=100),)
    false_alarm_bound: Threshold = field(default_factory=_bound)
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    compute_fn: Callable[
        [RecordView, Mapping[str, ThresholdLike], Mapping[str, object]], CheckResult
    ] = _memory_band

    def positive_control(self, seed: int) -> RecordView:
        return red_noise(seed)

    def compute(
        self,
        record: RecordView,
        thresholds: Mapping[str, ThresholdLike],
        capabilities: Mapping[str, object],
    ) -> CheckResult:
        return self.compute_fn(record, thresholds, capabilities)


def _registered(check: DummyCheck) -> Registry:
    registry = Registry()
    registry.register(check)
    return registry


def test_a_well_behaved_check_passes_the_smoke_battery() -> None:
    check = DummyCheck()
    measurement = run_smoke_battery(_registered(check), check, NO_THRESHOLDS)
    assert measurement.failures == 0


@pytest.mark.battery
def test_a_well_behaved_check_passes_the_full_battery() -> None:
    check = DummyCheck()
    measurement = run_full_battery(_registered(check), check, NO_THRESHOLDS)
    # The measurement is the bound's provenance; it must carry the numbers.
    assert measurement.n_realisations >= 200  # noqa: PLR2004 - the audited floor
    assert measurement.fail_rate <= check.false_alarm_bound.value


def test_a_check_that_passes_white_noise_fails_the_negative_controls() -> None:
    def always_pass(
        record: RecordView,  # noqa: ARG001 - broken on purpose
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - broken on purpose
        capabilities: Mapping[str, object],  # noqa: ARG001 - broken on purpose
    ) -> CheckResult:
        return CheckResult(verdict=Verdict.PASS)

    check = DummyCheck(check_id="always_pass", compute_fn=always_pass)
    with pytest.raises(BatteryError, match="PASSed the 'white_noise'"):
        negative_controls(_registered(check), check, NO_THRESHOLDS)


def test_a_check_reacting_to_the_logging_interval_fails_the_ladder() -> None:
    # MARGINAL, not FAIL, under decimation - pinning the stricter rule the
    # audit adopted: PASS may degrade to INCONCLUSIVE only.
    def interval_reactor(
        record: RecordView,
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - broken on purpose
        capabilities: Mapping[str, object],  # noqa: ARG001 - broken on purpose
    ) -> CheckResult:
        if record.dt == BATTERY_DT:
            return CheckResult(verdict=Verdict.PASS)
        return CheckResult(verdict=Verdict.MARGINAL, reason="not my favourite interval")

    check = DummyCheck(check_id="interval_reactor", compute_fn=interval_reactor)
    with pytest.raises(BatteryError, match="reacting to the logging interval"):
        decimation_ladder(_registered(check), check, NO_THRESHOLDS)


def test_a_check_that_punishes_gaps_fails_gap_robustness() -> None:
    def gap_hater(
        record: RecordView,
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - broken on purpose
        capabilities: Mapping[str, object],  # noqa: ARG001 - broken on purpose
    ) -> CheckResult:
        if record.gap_fraction > 0.0:
            return CheckResult(verdict=Verdict.FAIL, reason="gaps offend me")
        return CheckResult(verdict=Verdict.PASS)

    check = DummyCheck(check_id="gap_hater", compute_fn=gap_hater)
    with pytest.raises(BatteryError, match="reacting to the mask"):
        gap_robustness(_registered(check), check, NO_THRESHOLDS)


def test_a_nondeterministic_check_fails_the_determinism_case() -> None:
    counter = itertools.count()

    def drifting(
        record: RecordView,  # noqa: ARG001 - broken on purpose
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - broken on purpose
        capabilities: Mapping[str, object],  # noqa: ARG001 - broken on purpose
    ) -> CheckResult:
        return CheckResult(verdict=Verdict.PASS, metrics={"draw": float(next(counter))})

    check = DummyCheck(check_id="drifting", compute_fn=drifting)
    with pytest.raises(BatteryError, match="different results"):
        determinism(_registered(check), check, NO_THRESHOLDS)


def test_a_check_exceeding_its_declared_bound_fails_the_smoke_far() -> None:
    # Declares 5 % and FAILs nearly every AR(1) realisation: the honest
    # declaration would be ~1.0, and the smoke tier already catches the lie.
    def far_liar(
        record: RecordView,
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - broken on purpose
        capabilities: Mapping[str, object],  # noqa: ARG001 - broken on purpose
    ) -> CheckResult:
        r1 = float(record.series.autocorr(lag=1))
        if r1 > 0.5:  # noqa: PLR2004 - deliberately trips on every AR(1) draw
            return CheckResult(verdict=Verdict.FAIL, reason="memory detected, panicking")
        return CheckResult(verdict=Verdict.PASS)

    check = DummyCheck(check_id="far_liar", compute_fn=far_liar)
    measurement = red_noise_false_alarms(_registered(check), check, NO_THRESHOLDS, 20)
    assert measurement.fail_rate > 0.5  # noqa: PLR2004 - the lie is gross, not marginal
    with pytest.raises(BatteryError, match="exceeds"):
        assert_smoke_far(measurement)
    with pytest.raises(BatteryError, match="declare the real rate"):
        assert_full_far(measurement)


def test_an_inadmissible_control_is_a_battery_failure_not_a_pass() -> None:
    # The vacuity guard: unmet requirements on a control must fail the
    # battery loudly, never satisfy "must not PASS" silently.
    check = DummyCheck(check_id="never_admissible", requirements=(MinValidSamples(n=10**6),))
    with pytest.raises(BatteryError, match="inadmissible control tests nothing"):
        negative_controls(_registered(check), check, NO_THRESHOLDS)


def test_an_inconclusive_null_is_a_battery_failure() -> None:
    def undecided(
        record: RecordView,  # noqa: ARG001 - broken on purpose
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - broken on purpose
        capabilities: Mapping[str, object],  # noqa: ARG001 - broken on purpose
    ) -> CheckResult:
        return CheckResult(verdict=Verdict.INCONCLUSIVE, reason="cannot decide, ever")

    check = DummyCheck(check_id="undecided", compute_fn=undecided)
    with pytest.raises(BatteryError, match="unmeasured"):
        red_noise_false_alarms(_registered(check), check, NO_THRESHOLDS, 5)


def _records_evaluated_by(
    tier: Callable[[Registry, Check, Mapping[str, ThresholdLike]], FarMeasurement],
    check_id: str,
) -> list[RecordView]:
    """Run ``tier`` under a well-behaved check that records every record it is shown."""
    seen: list[RecordView] = []

    def recording(
        record: RecordView,
        thresholds: Mapping[str, ThresholdLike],
        capabilities: Mapping[str, object],
    ) -> CheckResult:
        seen.append(record)
        return _memory_band(record, thresholds, capabilities)

    # No requirements: the runner short-circuits an unmet requirement to
    # INCONCLUSIVE before compute, which would hide records (the x60 rung
    # has 84 samples) from the spy without the tier skipping anything.
    check = DummyCheck(check_id=check_id, requirements=(), compute_fn=recording)
    tier(_registered(check), check, NO_THRESHOLDS)
    return seen


def _fingerprint(record: RecordView) -> bytes:
    """Byte-exact identity of a seeded record's values; identical NaNs collide, as wanted."""
    fingerprint: bytes = record.series.to_numpy().tobytes()
    return fingerprint


def _assert_every_case_class_evaluated(
    seen: list[RecordView], check_id: str, n_realisations: int
) -> None:
    """All five case classes reached the check, identified by their seeded records.

    Deleting any case-class call from a tier function leaves the suite
    green today (mutation finding B2 on #22): nothing asserted the tiers
    actually orchestrate. Every expected record is reconstructed here from
    the public generators and ``derive_seed``, so a tier that skips a case
    class - or a rung, a fraction, or a realisation - is named exactly.
    """
    counts = Counter(_fingerprint(record) for record in seen)
    positive = red_noise(derive_seed(check_id, "positive", 0))
    expected: dict[str, tuple[RecordView, int]] = {}
    for name, generator in NEGATIVE_CONTROLS.items():
        control = generator(derive_seed(check_id, f"negative_{name}", 0))
        expected[f"negative control {name!r}"] = (control, 1)
    # Each ladder re-proves the positive control at native resolution first.
    expected["positive control at native dt"] = (positive, 2)
    for factor in DECIMATION_FACTORS:
        expected[f"decimation x{factor}"] = (decimate(positive, factor), 1)
    for fraction in GAP_FRACTIONS:
        gapped = with_gaps(positive, fraction, derive_seed(check_id, "gap", round(fraction * 100)))
        expected[f"gaps {fraction:.0%}"] = (gapped, 1)
    # Determinism means the identically-seeded record is judged twice.
    expected["determinism pair"] = (red_noise(derive_seed(check_id, "determinism", 0)), 2)
    for index in range(n_realisations):
        realisation = red_noise(derive_seed(check_id, "red_noise", index))
        expected[f"red noise realisation {index}"] = (realisation, 1)
    wrong = {
        label: {"evaluated": counts[_fingerprint(record)], "required": required}
        for label, (record, required) in expected.items()
        if counts[_fingerprint(record)] != required
    }
    assert not wrong, f"case-class records not evaluated as required: {wrong}"


def test_the_smoke_tier_evaluates_every_case_class() -> None:
    seen = _records_evaluated_by(run_smoke_battery, "smoke_tier_spy")
    _assert_every_case_class_evaluated(seen, "smoke_tier_spy", SMOKE_REALISATIONS)


def test_the_full_tier_evaluates_every_case_class() -> None:
    # Deliberately not battery-marked: the weekly tier's FAR *measurement*
    # is weekly, but its orchestration must be proven at PR cadence -
    # a battery-marked orchestration test is deselected on exactly the
    # runs that would catch the mutation (B2).
    seen = _records_evaluated_by(run_full_battery, "full_tier_spy")
    _assert_every_case_class_evaluated(seen, "full_tier_spy", FULL_REALISATIONS)


def test_the_binomial_critical_count_is_exact_on_hand_checkable_cases() -> None:
    # n=1, p=0.5: P(X > 0) = 0.5. alpha above that stops at k=0; alpha
    # below it must go to k=1.
    assert _binomial_critical(1, 0.5, 0.6) == 0
    assert _binomial_critical(1, 0.5, 0.4) == 1
    # A zero-probability event never exceeds zero.
    assert _binomial_critical(10, 0.0, 0.01) == 0
