"""Run every registered check against one record, in memory (#2).

Nothing is gated: every check gets a result, no verdict suppresses
another check, and the only ordering constraint is data flow - a
consumer runs after its capability's provider, otherwise registration
order holds. Persistence (the run folder, the manifest) is #4's; this
module's contract ends at the results mapping.

Admissibility belongs here, not to the checks: requirements are
evaluated before compute, and an unmet one becomes INCONCLUSIVE with the
generated reason. An unavailable capability is the same shape - the
provider was INCONCLUSIVE or did not emit - because *a check that could
not run is not evidence of absence*, and its consumers must inherit that
honesty rather than crash or guess.

A compute that raises is a bug and propagates. Catching it and returning
INCONCLUSIVE would launder defects into a legitimate verdict state.

Thresholds are resolved once for the record's variable and passed in;
an unknown variable raises ``MissingThresholdsError`` before any check
runs - the whole run refuses, it does not degrade (#2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sensor_qaqc.core.verdicts import CheckResult, Verdict

if TYPE_CHECKING:
    from sensor_qaqc.core.checks import Check
    from sensor_qaqc.core.records import RecordView
    from sensor_qaqc.core.registry import Registry
    from sensor_qaqc.core.thresholds import ThresholdTable


class CapabilityCycleError(RuntimeError):
    """The provides/consumes graph has a cycle; no execution order exists."""


class UndeclaredEmissionError(RuntimeError):
    """A compute emitted a capability its check does not declare in ``provides``."""


def run_checks(
    registry: Registry, record: RecordView, table: ThresholdTable
) -> dict[str, CheckResult]:
    """Run all checks; results keyed by check_id in execution order."""
    thresholds = table.for_variable(record.variable)
    emitted: dict[str, object] = {}
    inconclusive_providers: dict[str, str] = {}
    results: dict[str, CheckResult] = {}

    for check in _execution_order(registry):
        reasons = [
            reason
            for requirement in check.requirements
            if (reason := requirement.unmet_reason(record)) is not None
        ]
        # Execution order guarantees every provider already ran, so each
        # consumed capability was either emitted or its provider is on record
        # as having failed to emit (INCONCLUSIVE, or ran without emitting).
        reasons.extend(
            f"capability {capability!r} unavailable: provider"
            f" {inconclusive_providers[capability]!r} did not emit it"
            for capability in check.consumes
            if capability not in emitted
        )

        if reasons:
            result = CheckResult(verdict=Verdict.INCONCLUSIVE, reason="; ".join(reasons))
        else:
            capabilities = {name: emitted[name] for name in check.consumes}
            result = check.compute(record, thresholds, capabilities)
            undeclared = set(result.provides) - set(check.provides)
            if undeclared:
                msg = (
                    f"check {check.check_id!r} emitted undeclared"
                    f" capabilities: {sorted(undeclared)}"
                )
                raise UndeclaredEmissionError(msg)
            emitted.update(result.provides)

        for capability in check.provides:
            if capability not in emitted:
                inconclusive_providers[capability] = check.check_id
        results[check.check_id] = result

    return results


def _execution_order(registry: Registry) -> list[Check]:
    """Registration order, deferring consumers until their providers ran.

    Every consumed capability must have a registered provider
    (``provider_of`` raises otherwise), and the provides/consumes graph
    must be acyclic. Kahn-style selection keeps the order deterministic:
    always the earliest-registered runnable check.
    """
    remaining = list(registry)
    scheduled: set[str] = set()
    order: list[Check] = []
    while remaining:
        runnable = next(
            (
                check
                for check in remaining
                if all(
                    registry.provider_of(capability).check_id in scheduled
                    for capability in check.consumes
                )
            ),
            None,
        )
        if runnable is None:
            stuck = ", ".join(check.check_id for check in remaining)
            msg = f"capability cycle among checks: {stuck}"
            raise CapabilityCycleError(msg)
        order.append(runnable)
        scheduled.add(runnable.check_id)
        remaining.remove(runnable)
    return order
