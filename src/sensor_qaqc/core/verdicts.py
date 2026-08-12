"""The four-state verdict vocabulary and the check result type (#2).

Four states, never two: ``ok = verdict == "PASS"`` is banned repo-wide
because collapsing four states into a boolean is how MARGINAL and
INCONCLUSIVE pages come to render FAIL-side prose under a header showing
the true verdict (#10). There is deliberately no ``ok`` property on either
type here.

INCONCLUSIVE has two producers with one meaning: the runner, when a
declared requirement is unmet before compute (admissibility), and the
check itself, when only computation can reveal that no conclusion is
possible. On both paths a reason is mandatory - ``CheckResult`` cannot be
constructed INCONCLUSIVE without one, so "could not run" can never be
mistaken for "ran and passed", which is the prototype failure this PRD
exists to prevent.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class Verdict(enum.StrEnum):
    """What a check concluded - or that it could not conclude."""

    PASS = "PASS"  # noqa: S105 - a verdict, not a password
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict with its named metrics.

    ``metrics`` holds the derivable physical numbers the report prints -
    a renderer may never recompute them (#10). ``reason`` is free text for
    the reader; it is required exactly when the verdict is INCONCLUSIVE
    and welcome on any verdict (a MARGINAL without a reason is legal but
    unkind). ``provides`` carries computed-once capability payloads by
    name; the runner hands them to the declared consumers and to nobody
    else.
    """

    verdict: Verdict
    metrics: Mapping[str, float] = field(default_factory=dict)
    reason: str | None = None
    provides: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.verdict is Verdict.INCONCLUSIVE and not (self.reason or "").strip():
            msg = "an INCONCLUSIVE result cannot be constructed without a reason"
            raise ValueError(msg)
