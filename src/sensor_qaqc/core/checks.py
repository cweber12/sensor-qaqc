"""What a check *is*: the protocol and its vocabulary (#1, #2).

Domain is what the reader asks; **channel** is what the statistician
counts for independence. They are declared separately on every check and
never inferred from each other: spectral slope and autocorrelation
e-folding are a Fourier pair (Wiener-Khinchin) and must never be counted
as two pieces of evidence, whatever directory their checks live in.

Both enums are deliberately closed. An open string would let a typo
("SPECTRAL" vs "spectral") manufacture a fake independent channel and
silently inflate the evidence count - the exact failure #10's "count
independent channels, never N of M checks" rule exists to prevent.
Growing either set is a one-line, reviewable diff here, the same pattern
as ``layers.toml``.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sensor_qaqc.core.records import RecordView
    from sensor_qaqc.core.requirements import Requirement
    from sensor_qaqc.core.thresholds import Threshold, ThresholdLike
    from sensor_qaqc.core.verdicts import CheckResult


class Domain(enum.StrEnum):
    """The question a check asks - never what it lets you conclude (#1)."""

    PLAUSIBILITY = "plausibility"
    INTEGRITY = "integrity"
    COHERENCE = "coherence"


class Channel(enum.StrEnum):
    """The statistical evidence stream a check draws on (#7, #8).

    Checks sharing a channel corroborate; they do not multiply evidence.
    The member set is seeded from the #7/#8 check tables; a new channel
    arrives here in the commit whose check needs it.
    """

    ENCODING = "encoding"
    SPECTRAL = "spectral"
    TEMPORAL = "temporal"
    HARDWARE = "hardware"
    ASTRONOMICAL = "astronomical"
    CROSS_SENSOR = "cross_sensor"
    NETWORK = "network"


class Check(Protocol):
    """A check declares its conformance facts as data; only compute is code.

    The runner - not the check - evaluates ``requirements`` before compute
    and turns an unmet one into INCONCLUSIVE with a generated reason.
    ``positive_control`` returns a seeded synthetic record the check must
    PASS at native resolution; the battery decimates and gap-injects that
    series, so without it the ladders would have nothing to degrade from.
    ``provides``/``consumes`` name capabilities (computed-once,
    consumed-by-name); the registry holds every provider unique.

    ``compute`` receives its thresholds as an argument, resolved for the
    record's variable - a check has no import path to a number, which is
    the structural half of "thresholds are injected, never imported"
    (ADR 0001).
    """

    @property
    def check_id(self) -> str:
        """Flat lowercase snake, never renamed, never domain-qualified (#1)."""
        ...

    @property
    def domain(self) -> Domain: ...

    @property
    def channel(self) -> Channel: ...

    @property
    def requirements(self) -> tuple[Requirement, ...]: ...

    @property
    def false_alarm_bound(self) -> Threshold:
        """Declared FAIL rate on the AR(1) null, as a dimensionless Threshold."""
        ...

    @property
    def provides(self) -> tuple[str, ...]: ...

    @property
    def consumes(self) -> tuple[str, ...]: ...

    def positive_control(self, seed: int) -> RecordView:
        """Return a seeded synthetic record this check must PASS at native resolution."""
        ...

    def compute(
        self,
        record: RecordView,
        thresholds: Mapping[str, ThresholdLike],
        capabilities: Mapping[str, object],
    ) -> CheckResult:
        """Run the check's own logic - reached only after requirements are met."""
        ...
