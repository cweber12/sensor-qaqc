"""Nothing registers without its conformance facts; providers are unique (#2)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from sensor_qaqc.core.checks import Channel, Domain
from sensor_qaqc.core.registry import (
    RegistrationError,
    Registry,
    UnknownCapabilityError,
    UnknownCheckError,
)
from sensor_qaqc.core.thresholds import Provenance, Threshold
from sensor_qaqc.core.verdicts import CheckResult, Verdict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sensor_qaqc.core.records import RecordView
    from sensor_qaqc.core.requirements import Requirement
    from sensor_qaqc.core.thresholds import ThresholdLike


@dataclass(frozen=True)
class FakeRecord:
    variable: str = "sea_water_temperature"
    values: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    dt: timedelta = timedelta(minutes=6)
    duration: timedelta = timedelta(days=21)
    n_valid: int = 5040
    gap_fraction: float = 0.0


def _bound(rate: float = 0.05, unit: str = "1") -> Threshold:
    return Threshold(
        value=rate,
        unit=unit,
        provenance=Provenance(source="test", rationale="synthetic check"),
    )


@dataclass(frozen=True)
class FakeCheck:
    check_id: str = "fake_check"
    domain: Domain = Domain.INTEGRITY
    channel: Channel = Channel.SPECTRAL
    requirements: tuple[Requirement, ...] = ()
    false_alarm_bound: Threshold = field(default_factory=_bound)
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()

    def positive_control(self, seed: int) -> RecordView:  # noqa: ARG002 - fake
        return FakeRecord()

    def compute(
        self,
        record: RecordView,  # noqa: ARG002 - fake
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG002 - fake
        capabilities: Mapping[str, object],  # noqa: ARG002 - fake
    ) -> CheckResult:
        return CheckResult(verdict=Verdict.PASS)


def test_registration_preserves_landing_order() -> None:
    registry = Registry()
    landing_order = ["beta", "alpha"]
    for check_id in landing_order:
        registry.register(FakeCheck(check_id=check_id))
    assert [check.check_id for check in registry] == landing_order
    assert registry.ids() == {"alpha", "beta"}
    assert len(registry) == len(landing_order)
    assert registry.get("alpha").check_id == "alpha"


def test_an_unknown_check_id_is_named_with_what_exists() -> None:
    registry = Registry()
    registry.register(FakeCheck(check_id="quantisation"))
    with pytest.raises(UnknownCheckError, match=r"'spectral_slope'.*quantisation"):
        registry.get("spectral_slope")


@pytest.mark.parametrize(
    "check_id",
    [
        "integrity.quantisation",  # domain-qualified: couples the id to a directory
        "Quantisation",
        "has space",
        "9starts_with_digit",
        "trailing_",
        "double__underscore",
        "",
    ],
)
def test_ids_must_be_flat_lowercase_snake(check_id: str) -> None:
    with pytest.raises(RegistrationError, match="flat lowercase snake"):
        Registry().register(FakeCheck(check_id=check_id))


def test_duplicate_ids_are_refused() -> None:
    registry = Registry()
    registry.register(FakeCheck())
    with pytest.raises(RegistrationError, match="already registered"):
        registry.register(FakeCheck())


@pytest.mark.parametrize("rate", [0.0, 1.0, -0.1, 1.5])
def test_a_false_alarm_bound_must_be_a_rate(rate: float) -> None:
    check = FakeCheck(false_alarm_bound=_bound(rate=rate))
    with pytest.raises(RegistrationError, match="not a rate"):
        Registry().register(check)


def test_a_false_alarm_bound_must_be_dimensionless() -> None:
    # 5 (percent) and 0.05 (rate) must not be confusable; unit "1" is the rule.
    check = FakeCheck(false_alarm_bound=_bound(rate=0.05, unit="percent"))
    with pytest.raises(RegistrationError, match="dimensionless"):
        Registry().register(check)


def test_a_bound_cannot_be_declared_without_provenance() -> None:
    # The bound is a threshold like any other; provenance is structural.
    with pytest.raises(ValueError, match="non-empty"):
        _bound().provenance.__class__(source="", rationale="")


def test_exactly_one_check_may_provide_a_capability() -> None:
    registry = Registry()
    registry.register(FakeCheck(check_id="spectral_slope", provides=("spectral_estimate",)))
    rival = FakeCheck(check_id="rival", provides=("spectral_estimate",))
    with pytest.raises(RegistrationError, match="already provided by 'spectral_slope'"):
        registry.register(rival)
    assert registry.provider_of("spectral_estimate").check_id == "spectral_slope"


def test_an_unprovided_capability_is_named() -> None:
    with pytest.raises(UnknownCapabilityError, match="'spectral_estimate'"):
        Registry().provider_of("spectral_estimate")


def test_a_check_may_not_consume_its_own_capability() -> None:
    check = FakeCheck(provides=("thing",), consumes=("thing",))
    with pytest.raises(RegistrationError, match="its own capability"):
        Registry().register(check)


def test_capability_names_follow_the_id_grammar() -> None:
    check = replace(FakeCheck(), provides=("Spectral.Estimate",))
    with pytest.raises(RegistrationError, match="not snake case"):
        Registry().register(check)
