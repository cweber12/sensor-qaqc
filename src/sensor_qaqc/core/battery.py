"""The conformance battery: automatic, inherited, non-optional (#2, ADR 0006).

Five case classes against every registered check. Each case is guarded
against passing vacuously, because *a check that cannot run is not
evidence of absence* - and a battery case that cannot run is not evidence
of conformance:

1. **Negative controls** (white noise, flatline, ramp, quantised) must
   not PASS - and the control must first be *admissible*, otherwise an
   unmet requirement would satisfy "not PASS" while testing nothing.
2. **Red-noise false alarms**: the AR(1) null is the standard geophysical
   background; white noise is a straw man. A false alarm is a FAIL on the
   null. MARGINAL is measured and reported but not bounded; INCONCLUSIVE
   on the null is a battery failure, never a data point.
3. **Decimation ladder** (6 to 360 min): PASS may degrade to INCONCLUSIVE
   as sampling coarsens; PASS to MARGINAL or FAIL means the check reacts
   to the logging interval rather than to the water.
4. **Gap robustness** (5/15/30 % NaN in place): same tolerance rule,
   relative to the intact record's PASS.
5. **Determinism**: identical inputs, identical results - and the
   positive control itself must reproduce from its seed.

Two tiers (audit on #2): **smoke** (n=20, every PR) asserts only gross
violation - observed FAR <= 3x declared - because twenty draws cannot
measure a 5 % bound; a check three times worse than its bound still
slips a 20-draw test almost half the time. **full** (n>=200, weekly,
``-m battery``) tests the declared bound at an exact-binomial 1 % level
and its measurement *is* the bound's provenance: the bound may not
change without a full run, which puts it under "a number never moves in
a refactoring commit".

Vacuity guarding currently covers the target check's own requirements;
when capability-consuming checks arrive (#8), it extends to provider
chains (recorded in ADR 0006).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sensor_qaqc.core.runner import run_checks
from sensor_qaqc.core.synthetic import (
    NEGATIVE_CONTROLS,
    decimate,
    derive_seed,
    red_noise,
    with_gaps,
)
from sensor_qaqc.core.thresholds import ThresholdTable
from sensor_qaqc.core.verdicts import Verdict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sensor_qaqc.core.checks import Check
    from sensor_qaqc.core.records import RecordView
    from sensor_qaqc.core.registry import Registry
    from sensor_qaqc.core.thresholds import ThresholdLike
    from sensor_qaqc.core.verdicts import CheckResult

SMOKE_REALISATIONS = 20
FULL_REALISATIONS = 200
# Smoke tier: gross violation only. Not a measurement - the label matters.
SMOKE_GROSS_FACTOR = 3.0
# Full tier: exact binomial test at this significance against the declared
# bound. With fixed seeds the outcome is deterministic; alpha sets where
# the tripwire sits, not a flakiness budget.
FULL_ALPHA = 0.01
# 6 min native -> 12, 30, 60, 120, 360 min (#2's ladder).
DECIMATION_FACTORS = (2, 5, 10, 20, 60)
GAP_FRACTIONS = (0.05, 0.15, 0.30)


class BatteryError(Exception):
    """A check failed a battery case - or a case could not run honestly."""


@dataclass(frozen=True)
class FarMeasurement:
    """A measured false-alarm rate; the full tier's instance is provenance."""

    check_id: str
    declared: float
    n_realisations: int
    failures: int
    marginals: int

    @property
    def fail_rate(self) -> float:
        return self.failures / self.n_realisations

    @property
    def marginal_rate(self) -> float:
        return self.marginals / self.n_realisations


def _evaluate(
    registry: Registry,
    check: Check,
    record: RecordView,
    thresholds: Mapping[str, ThresholdLike],
) -> CheckResult:
    """Compute the target's result under real runner semantics (providers included)."""
    table = ThresholdTable({record.variable: thresholds})
    return run_checks(registry, record, table)[check.check_id]


def _require_admissible(check: Check, record: RecordView, control: str) -> None:
    """Fail loudly on a control the check cannot see - it would prove nothing."""
    reasons = [
        reason
        for requirement in check.requirements
        if (reason := requirement.unmet_reason(record)) is not None
    ]
    if reasons:
        msg = (
            f"battery control {control!r} is inadmissible for {check.check_id!r}"
            f" ({'; '.join(reasons)}): an inadmissible control tests nothing"
        )
        raise BatteryError(msg)


def negative_controls(
    registry: Registry, check: Check, thresholds: Mapping[str, ThresholdLike]
) -> None:
    """White noise, flatline, ramp and a quantised series must not PASS."""
    for name, generator in NEGATIVE_CONTROLS.items():
        record = generator(derive_seed(check.check_id, f"negative_{name}", 0))
        _require_admissible(check, record, name)
        result = _evaluate(registry, check, record, thresholds)
        if result.verdict is Verdict.PASS:
            msg = f"{check.check_id!r} PASSed the {name!r} negative control"
            raise BatteryError(msg)


def red_noise_false_alarms(
    registry: Registry,
    check: Check,
    thresholds: Mapping[str, ThresholdLike],
    n_realisations: int,
) -> FarMeasurement:
    """Measure the FAIL rate on the AR(1) null over seeded realisations."""
    failures = 0
    marginals = 0
    for index in range(n_realisations):
        record = red_noise(derive_seed(check.check_id, "red_noise", index))
        _require_admissible(check, record, f"red_noise[{index}]")
        result = _evaluate(registry, check, record, thresholds)
        if result.verdict is Verdict.INCONCLUSIVE:
            msg = (
                f"{check.check_id!r} was INCONCLUSIVE on AR(1) null realisation"
                f" {index} ({result.reason}): an undecidable null leaves the"
                " false-alarm rate unmeasured"
            )
            raise BatteryError(msg)
        if result.verdict is Verdict.FAIL:
            failures += 1
        elif result.verdict is Verdict.MARGINAL:
            marginals += 1
    return FarMeasurement(
        check_id=check.check_id,
        declared=check.false_alarm_bound.value,
        n_realisations=n_realisations,
        failures=failures,
        marginals=marginals,
    )


def assert_smoke_far(measurement: FarMeasurement) -> None:
    """Gross-violation tripwire only; n=20 cannot measure the bound."""
    if measurement.fail_rate > SMOKE_GROSS_FACTOR * measurement.declared:
        msg = (
            f"{measurement.check_id!r}: observed FAR"
            f" {measurement.fail_rate:.3f} over {measurement.n_realisations}"
            f" realisations exceeds {SMOKE_GROSS_FACTOR:g}x the declared"
            f" {measurement.declared} (smoke tier; run the full battery to measure)"
        )
        raise BatteryError(msg)


def assert_full_far(measurement: FarMeasurement) -> None:
    """Exact binomial test of the declared bound at ``FULL_ALPHA``."""
    critical = _binomial_critical(measurement.n_realisations, measurement.declared, FULL_ALPHA)
    if measurement.failures > critical:
        msg = (
            f"{measurement.check_id!r}: {measurement.failures} false alarms in"
            f" {measurement.n_realisations} is inconsistent with the declared"
            f" bound {measurement.declared} (binomial critical count {critical}"
            f" at alpha={FULL_ALPHA}); declare the real rate honestly instead"
        )
        raise BatteryError(msg)


def _binomial_critical(n: int, p: float, alpha: float) -> int:
    """Smallest k with P(X > k) < alpha for X ~ Binomial(n, p). Exact, stdlib."""
    cumulative = 0.0
    for k in range(n + 1):
        cumulative += math.comb(n, k) * p**k * (1.0 - p) ** (n - k)
        if 1.0 - cumulative < alpha:
            return k
    return n


def passing_positive_control(
    registry: Registry, check: Check, thresholds: Mapping[str, ThresholdLike]
) -> RecordView:
    """Return the declared positive control, proven to PASS at native resolution."""
    record = check.positive_control(derive_seed(check.check_id, "positive", 0))
    _require_admissible(check, record, "positive_control")
    result = _evaluate(registry, check, record, thresholds)
    if result.verdict is not Verdict.PASS:
        msg = (
            f"{check.check_id!r}: positive control returned {result.verdict}"
            f" ({result.reason}) at native resolution - the ladders have"
            " nothing to degrade from"
        )
        raise BatteryError(msg)
    return record


def decimation_ladder(
    registry: Registry, check: Check, thresholds: Mapping[str, ThresholdLike]
) -> None:
    """PASS may coarsen into INCONCLUSIVE, never into MARGINAL or FAIL."""
    base = passing_positive_control(registry, check, thresholds)
    for factor in DECIMATION_FACTORS:
        record = decimate(base, factor)
        result = _evaluate(registry, check, record, thresholds)
        if result.verdict in (Verdict.MARGINAL, Verdict.FAIL):
            msg = (
                f"{check.check_id!r}: PASS at native dt degraded to"
                f" {result.verdict} at {factor}x decimation (dt={record.dt}) -"
                " the check is reacting to the logging interval, not the water"
            )
            raise BatteryError(msg)


def gap_robustness(
    registry: Registry, check: Check, thresholds: Mapping[str, ThresholdLike]
) -> None:
    """Missing data may cost conclusiveness, never flip the verdict."""
    base = passing_positive_control(registry, check, thresholds)
    for fraction in GAP_FRACTIONS:
        seed = derive_seed(check.check_id, "gap", round(fraction * 100))
        record = with_gaps(base, fraction, seed)
        result = _evaluate(registry, check, record, thresholds)
        if result.verdict in (Verdict.MARGINAL, Verdict.FAIL):
            msg = (
                f"{check.check_id!r}: PASS on the intact record degraded to"
                f" {result.verdict} at {fraction:.0%} gaps - the check is"
                " reacting to the mask, not the water"
            )
            raise BatteryError(msg)


def determinism(registry: Registry, check: Check, thresholds: Mapping[str, ThresholdLike]) -> None:
    """Identical inputs, identical outputs - including the control itself."""
    seed = derive_seed(check.check_id, "determinism", 0)
    first_record = check.positive_control(seed)
    second_record = check.positive_control(seed)
    if not first_record.series.equals(second_record.series):
        msg = f"{check.check_id!r}: positive control is not reproducible from its seed"
        raise BatteryError(msg)
    first = _evaluate(registry, check, first_record, thresholds)
    second = _evaluate(registry, check, second_record, thresholds)
    if first != second:
        msg = (
            f"{check.check_id!r}: identical input produced different results ({first} vs {second})"
        )
        raise BatteryError(msg)


def run_smoke_battery(
    registry: Registry, check: Check, thresholds: Mapping[str, ThresholdLike]
) -> FarMeasurement:
    """Every case class at PR cadence; FAR asserted at gross-violation only."""
    negative_controls(registry, check, thresholds)
    decimation_ladder(registry, check, thresholds)
    gap_robustness(registry, check, thresholds)
    determinism(registry, check, thresholds)
    measurement = red_noise_false_alarms(registry, check, thresholds, SMOKE_REALISATIONS)
    assert_smoke_far(measurement)
    return measurement


def run_full_battery(
    registry: Registry, check: Check, thresholds: Mapping[str, ThresholdLike]
) -> FarMeasurement:
    """Run the weekly tier; its FarMeasurement is the declared bound's provenance."""
    negative_controls(registry, check, thresholds)
    decimation_ladder(registry, check, thresholds)
    gap_robustness(registry, check, thresholds)
    determinism(registry, check, thresholds)
    measurement = red_noise_false_alarms(registry, check, thresholds, FULL_REALISATIONS)
    assert_full_far(measurement)
    return measurement
