"""checks list/show read the registry and refuse honestly (#2, ADR 0002)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sensor_qaqc.cli.__main__ import EXIT_NO_RESULT, EXIT_PRODUCED, main
from sensor_qaqc.cli.checks_commands import render_list, render_show
from sensor_qaqc.core.checks import Channel, Domain
from sensor_qaqc.core.registry import Registry
from sensor_qaqc.core.requirements import MinValidSamples
from sensor_qaqc.core.synthetic import red_noise
from sensor_qaqc.core.thresholds import Provenance, Threshold
from sensor_qaqc.core.verdicts import CheckResult, Verdict

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pytest

    from sensor_qaqc.core.records import RecordView
    from sensor_qaqc.core.requirements import Requirement
    from sensor_qaqc.core.thresholds import ThresholdLike


def _bound() -> Threshold:
    return Threshold(
        value=0.1,
        unit="1",
        provenance=Provenance(source="full battery 2026-08-12", rationale="measured residual rate"),
    )


@dataclass(frozen=True)
class FakeCheck:
    check_id: str = "tidal_lines"
    domain: Domain = Domain.COHERENCE
    channel: Channel = Channel.ASTRONOMICAL
    requirements: tuple[Requirement, ...] = (MinValidSamples(n=3600),)
    false_alarm_bound: Threshold = field(default_factory=_bound)
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ("spectral_estimate",)

    def positive_control(self, seed: int) -> RecordView:
        return red_noise(seed)

    def compute(
        self,
        record: RecordView,  # noqa: ARG002 - fake
        thresholds: Mapping[str, ThresholdLike],  # noqa: ARG002 - fake
        capabilities: Mapping[str, object],  # noqa: ARG002 - fake
    ) -> CheckResult:
        return CheckResult(verdict=Verdict.PASS)


def test_an_empty_registry_lists_as_a_statement_not_a_blank() -> None:
    assert "no checks registered" in render_list(Registry())


def test_list_carries_id_domain_channel_bound_and_requirements() -> None:
    registry = Registry()
    registry.register(FakeCheck())
    listing = render_list(registry)
    assert "tidal_lines" in listing
    assert "domain=coherence" in listing
    assert "channel=astronomical" in listing
    assert "far<=0.1" in listing
    assert "MinValidSamples(n=3600)" in listing


def test_show_carries_the_bound_with_its_provenance() -> None:
    shown = render_show(FakeCheck())
    assert "check_id: tidal_lines" in shown
    assert "false-alarm bound: 0.1" in shown
    assert "source: full battery 2026-08-12" in shown
    assert "rationale: measured residual rate" in shown
    assert "consumes: spectral_estimate" in shown
    assert "provides: none" in shown


def test_checks_list_produces_output_and_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    # The assembled registry is empty until #6-#8; producing that statement
    # is producing output (ADR 0002: producer, exit 0).
    assert main(["checks", "list"]) == EXIT_PRODUCED
    assert "no checks registered" in capsys.readouterr().out


def test_checks_show_unknown_id_exits_1_naming_it(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["checks", "show", "quantisation"]) == EXIT_NO_RESULT
    stderr = capsys.readouterr().err
    assert "quantisation" in stderr
    assert "unknown check_id" in stderr
    assert "Traceback" not in stderr
