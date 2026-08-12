"""The check registry: nothing registers without its conformance facts (#2).

Registration is the gate where the framework's non-negotiables are
enforced as constructor-time errors rather than review habits:

- ``check_id`` is flat lowercase snake, never domain-qualified (#1): a
  dotted id would couple the name to a directory, and ids live in
  archived run folders forever, so moving a check between domains must
  never rename it. Renames are separately caught by
  ``tests/test_check_ids.py`` against the committed append-only id list.
- A check cannot register without a declared false-alarm bound - the
  rate it claims on the AR(1) null, which the battery measures it
  against. Declared honestly (the tidal check's real residual rate is
  ~0.10; declare 0.10, not 0.05 with an apologetic comment).
- A check cannot register without a positive control: a seeded synthetic
  record it must PASS at native resolution. Without one, the battery's
  decimation and gap ladders have nothing to degrade from and would pass
  vacuously (audit finding 2 on #2).
- Computed-once / consumed-by-name: exactly one check may provide a
  given capability, so a second provider is a registration error, not a
  silent double-count.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sensor_qaqc.core.checks import Check

# Flat lowercase snake: no dots (domain qualification), no leading digit,
# no leading/trailing/doubled underscores. Capability names follow the same
# grammar so consumed-by-name stays greppable.
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


class RegistrationError(ValueError):
    """The check's declaration violates a framework rule; nothing was registered."""


class UnknownCheckError(KeyError):
    """No check with that id is registered."""


class UnknownCapabilityError(KeyError):
    """No registered check provides that capability."""


class Registry:
    """Registered checks in registration order, validated on entry."""

    def __init__(self) -> None:
        self._checks: dict[str, Check] = {}
        self._provider_ids: dict[str, str] = {}

    def register(self, check: Check) -> None:
        self._validate_id(check)
        self._validate_false_alarm_bound(check)
        self._validate_capabilities(check)
        self._checks[check.check_id] = check
        for capability in check.provides:
            self._provider_ids[capability] = check.check_id

    def get(self, check_id: str) -> Check:
        if check_id not in self._checks:
            known = ", ".join(self._checks) or "none"
            msg = f"unknown check_id {check_id!r}; registered: {known}"
            raise UnknownCheckError(msg)
        return self._checks[check_id]

    def provider_of(self, capability: str) -> Check:
        if capability not in self._provider_ids:
            known = ", ".join(sorted(self._provider_ids)) or "none"
            msg = f"no registered check provides {capability!r}; provided: {known}"
            raise UnknownCapabilityError(msg)
        return self._checks[self._provider_ids[capability]]

    def ids(self) -> frozenset[str]:
        return frozenset(self._checks)

    def __iter__(self) -> Iterator[Check]:
        return iter(self._checks.values())

    def __len__(self) -> int:
        return len(self._checks)

    def _validate_id(self, check: Check) -> None:
        check_id = check.check_id
        if not _ID_PATTERN.fullmatch(check_id):
            msg = (
                f"check_id {check_id!r} is not flat lowercase snake"
                " (never domain-qualified, never dotted)"
            )
            raise RegistrationError(msg)
        if check_id in self._checks:
            msg = f"check_id {check_id!r} is already registered"
            raise RegistrationError(msg)

    @staticmethod
    def _validate_false_alarm_bound(check: Check) -> None:
        bound = check.false_alarm_bound
        if not 0.0 < bound.value < 1.0:
            msg = (
                f"check {check.check_id!r} declares false-alarm bound {bound.value},"
                " which is not a rate in (0, 1)"
            )
            raise RegistrationError(msg)
        if bound.unit != "1":
            msg = (
                f"check {check.check_id!r} declares false-alarm bound in unit"
                f" {bound.unit!r}; a rate is dimensionless (unit '1')"
            )
            raise RegistrationError(msg)

    def _validate_capabilities(self, check: Check) -> None:
        for capability in (*check.provides, *check.consumes):
            if not _ID_PATTERN.fullmatch(capability):
                msg = f"check {check.check_id!r}: capability name {capability!r} is not snake case"
                raise RegistrationError(msg)
        for capability in check.provides:
            if capability in self._provider_ids:
                msg = (
                    f"capability {capability!r} is already provided by"
                    f" {self._provider_ids[capability]!r}; exactly one check may provide it"
                )
                raise RegistrationError(msg)
        overlap = set(check.provides) & set(check.consumes)
        if overlap:
            msg = f"check {check.check_id!r} consumes its own capability: {sorted(overlap)}"
            raise RegistrationError(msg)
