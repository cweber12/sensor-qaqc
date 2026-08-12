"""Admissibility before compute, capability wiring, nothing gated (#2)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from sensor_qaqc.core.checks import Channel, Domain
from sensor_qaqc.core.registry import Registry, UnknownCapabilityError
from sensor_qaqc.core.requirements import MinValidSamples
from sensor_qaqc.core.runner import CapabilityCycleError, UndeclaredEmissionError, run_checks
from sensor_qaqc.core.thresholds import (
    MissingThresholdsError,
    Provenance,
    Threshold,
    ThresholdTable,
)
from sensor_qaqc.core.verdicts import CheckResult, Verdict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sensor_qaqc.core.records import RecordView
    from sensor_qaqc.core.requirements import Requirement
    from sensor_qaqc.core.thresholds import ThresholdLike

EFOLD = Threshold(
    value=1.0,
    unit="h",
    provenance=Provenance(source="test", rationale="synthetic"),
)
TABLE = ThresholdTable({"sea_water_temperature": {"efold_floor_h": EFOLD}})


@dataclass(frozen=True)
class FakeRecord:
    variable: str = "sea_water_temperature"
    values: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    dt: timedelta = timedelta(minutes=6)
    duration: timedelta = timedelta(days=21)
    n_valid: int = 5040
    gap_fraction: float = 0.0


ComputeFn = Callable[
    ["RecordView", "Mapping[str, ThresholdLike]", "Mapping[str, object]"], CheckResult
]


def _pass(
    record: RecordView,  # noqa: ARG001 - default compute
    thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - default compute
    capabilities: Mapping[str, object],  # noqa: ARG001 - default compute
) -> CheckResult:
    return CheckResult(verdict=Verdict.PASS)


@dataclass(frozen=True)
class FakeCheck:
    check_id: str = "fake_check"
    domain: Domain = Domain.INTEGRITY
    channel: Channel = Channel.SPECTRAL
    requirements: tuple[Requirement, ...] = ()
    false_alarm_bound: Threshold = field(
        default_factory=lambda: Threshold(
            value=0.05,
            unit="1",
            provenance=Provenance(source="test", rationale="synthetic"),
        )
    )
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    compute_fn: ComputeFn = _pass

    def positive_control(self, seed: int) -> RecordView:  # noqa: ARG002 - fake
        return FakeRecord()

    def compute(
        self,
        record: RecordView,
        thresholds: Mapping[str, ThresholdLike],
        capabilities: Mapping[str, object],
    ) -> CheckResult:
        return self.compute_fn(record, thresholds, capabilities)


def _registry(*checks: FakeCheck) -> Registry:
    registry = Registry()
    for check in checks:
        registry.register(check)
    return registry


def test_every_check_gets_a_result_and_thresholds_are_injected() -> None:
    seen: list[Mapping[str, ThresholdLike]] = []

    def observing(
        record: RecordView,  # noqa: ARG001 - observing thresholds only
        thresholds: Mapping[str, ThresholdLike],
        capabilities: Mapping[str, object],  # noqa: ARG001 - observing thresholds only
    ) -> CheckResult:
        seen.append(thresholds)
        return CheckResult(verdict=Verdict.FAIL)

    registry = _registry(
        FakeCheck(check_id="alpha", compute_fn=observing),
        FakeCheck(check_id="beta"),
    )
    results = run_checks(registry, FakeRecord(), TABLE)

    # Nothing is gated: alpha's FAIL did not stop beta.
    assert [*results] == ["alpha", "beta"]
    assert results["alpha"].verdict is Verdict.FAIL
    assert results["beta"].verdict is Verdict.PASS
    assert seen == [{"efold_floor_h": EFOLD}]


def test_an_unknown_variable_refuses_before_any_check_runs() -> None:
    ran: list[str] = []

    def recording(
        record: RecordView,  # noqa: ARG001 - recording invocation only
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - recording invocation only
        capabilities: Mapping[str, object],  # noqa: ARG001 - recording invocation only
    ) -> CheckResult:
        ran.append("ran")
        return CheckResult(verdict=Verdict.PASS)

    registry = _registry(FakeCheck(compute_fn=recording))
    with pytest.raises(MissingThresholdsError):
        run_checks(registry, FakeRecord(variable="sea_water_salinity"), TABLE)
    assert ran == []


def test_an_unmet_requirement_is_inconclusive_and_compute_never_runs() -> None:
    ran: list[str] = []

    def recording(
        record: RecordView,  # noqa: ARG001 - recording invocation only
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - recording invocation only
        capabilities: Mapping[str, object],  # noqa: ARG001 - recording invocation only
    ) -> CheckResult:
        ran.append("ran")
        return CheckResult(verdict=Verdict.PASS)

    check = FakeCheck(requirements=(MinValidSamples(n=50),), compute_fn=recording)
    results = run_checks(_registry(check), FakeRecord(n_valid=34), TABLE)

    assert ran == []
    result = results["fake_check"]
    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.reason == "n_valid=34 < required 50 (MinValidSamples)"


def test_consumers_run_after_providers_and_see_only_what_they_consume() -> None:
    def providing(
        record: RecordView,  # noqa: ARG001 - providing only
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - providing only
        capabilities: Mapping[str, object],  # noqa: ARG001 - providing only
    ) -> CheckResult:
        return CheckResult(verdict=Verdict.PASS, provides={"spectral_estimate": [1.0, 2.0]})

    received: list[Mapping[str, object]] = []

    def consuming(
        record: RecordView,  # noqa: ARG001 - consuming only
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - consuming only
        capabilities: Mapping[str, object],
    ) -> CheckResult:
        received.append(capabilities)
        return CheckResult(verdict=Verdict.PASS)

    # Consumer registered first: execution order must still defer it.
    registry = _registry(
        FakeCheck(check_id="tidal_lines", consumes=("spectral_estimate",), compute_fn=consuming),
        FakeCheck(check_id="spectral_slope", provides=("spectral_estimate",), compute_fn=providing),
        FakeCheck(check_id="bystander"),
    )
    results = run_checks(registry, FakeRecord(), TABLE)

    assert [*results] == ["spectral_slope", "tidal_lines", "bystander"]
    assert received == [{"spectral_estimate": [1.0, 2.0]}]
    assert all(result.verdict is Verdict.PASS for result in results.values())


def test_an_inconclusive_provider_makes_its_consumer_inconclusive() -> None:
    provider = FakeCheck(
        check_id="spectral_slope",
        provides=("spectral_estimate",),
        requirements=(MinValidSamples(n=50),),  # unmet: provider cannot run
    )
    consumer = FakeCheck(check_id="tidal_lines", consumes=("spectral_estimate",))
    results = run_checks(_registry(provider, consumer), FakeRecord(n_valid=34), TABLE)

    result = results["tidal_lines"]
    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.reason is not None
    assert "'spectral_estimate'" in result.reason
    assert "'spectral_slope'" in result.reason


def test_a_provider_that_ran_but_did_not_emit_is_named() -> None:
    provider = FakeCheck(check_id="spectral_slope", provides=("spectral_estimate",))
    consumer = FakeCheck(check_id="tidal_lines", consumes=("spectral_estimate",))
    results = run_checks(_registry(provider, consumer), FakeRecord(), TABLE)

    assert results["spectral_slope"].verdict is Verdict.PASS
    result = results["tidal_lines"]
    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.reason is not None
    assert "did not emit" in result.reason


def test_emitting_an_undeclared_capability_is_an_error_not_a_verdict() -> None:
    def rogue(
        record: RecordView,  # noqa: ARG001 - rogue emission
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - rogue emission
        capabilities: Mapping[str, object],  # noqa: ARG001 - rogue emission
    ) -> CheckResult:
        return CheckResult(verdict=Verdict.PASS, provides={"surprise": 1})

    with pytest.raises(UndeclaredEmissionError, match="surprise"):
        run_checks(_registry(FakeCheck(compute_fn=rogue)), FakeRecord(), TABLE)


def test_a_capability_cycle_is_an_error() -> None:
    registry = _registry(
        FakeCheck(check_id="alpha", provides=("a",), consumes=("b",)),
        FakeCheck(check_id="beta", provides=("b",), consumes=("a",)),
    )
    with pytest.raises(CapabilityCycleError, match=r"alpha.*beta"):
        run_checks(registry, FakeRecord(), TABLE)


def test_consuming_an_unprovided_capability_is_an_error() -> None:
    registry = _registry(FakeCheck(consumes=("spectral_estimate",)))
    with pytest.raises(UnknownCapabilityError, match="spectral_estimate"):
        run_checks(registry, FakeRecord(), TABLE)


def test_a_crashing_compute_propagates_rather_than_becoming_a_verdict() -> None:
    def crashing(
        record: RecordView,  # noqa: ARG001 - crashing on purpose
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG001 - crashing on purpose
        capabilities: Mapping[str, object],  # noqa: ARG001 - crashing on purpose
    ) -> CheckResult:
        msg = "a bug, not a verdict"
        raise ZeroDivisionError(msg)

    with pytest.raises(ZeroDivisionError):
        run_checks(_registry(FakeCheck(compute_fn=crashing)), FakeRecord(), TABLE)


def test_multiple_unmet_requirements_are_all_named() -> None:
    check = FakeCheck(
        requirements=(MinValidSamples(n=50), MinValidSamples(n=100)),
    )
    results = run_checks(_registry(check), FakeRecord(n_valid=10), TABLE)
    reason = results["fake_check"].reason
    assert reason is not None
    assert "required 50" in reason
    assert "required 100" in reason
