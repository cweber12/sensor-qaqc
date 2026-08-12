"""Thresholds carry mandatory provenance and may only ever tighten (#2).

Every number in this system carries a written reason (CLAUDE.md); a
threshold is the archetype. ``Threshold`` cannot be constructed without a
``Provenance`` - there is deliberately no unspecified variant - which is
what makes the generated check pages (#11) possible and "re-derive the
prototype's numbers" enforceable rather than aspirational.

Floors combine with ``MaxOfFloors`` only. There is deliberately no
``MinOfFloors`` in the codebase (a test asserts its absence): taking the
minimum of floors would let a plausible datasheet number silently weaken a
check - deriving the autocorrelation e-folding floor from the MX2204
datasheet alone gives ~0.58 h against a physical floor of ~1.0 h.
Manufacturer specs may inform a threshold; they may never relax one.

Thresholds are keyed by variable (CF ``standard_name``) with no default:
pointing the tool at salinity before salinity thresholds exist must
refuse, not fall back to temperature numbers - a confident report built
on the wrong variable's numbers is worse than no report.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class Provenance:
    """Where a number came from: its source, and why this value.

    ``source`` names the origin (a citation, a datasheet, a derivation, a
    battery run); ``rationale`` says why the value is what it is. Both are
    mandatory and non-empty by construction.
    """

    source: str
    rationale: str

    def __post_init__(self) -> None:
        for name in ("source", "rationale"):
            if not getattr(self, name).strip():
                msg = f"provenance requires a non-empty {name}"
                raise ValueError(msg)


@dataclass(frozen=True)
class Threshold:
    """A named number a check compares against, with its origin attached.

    ``unit`` is UDUNITS-style free text; dimensionless quantities (rates,
    ratios) use ``"1"``. The value must be finite - a NaN or infinite
    threshold compares as nonsense and would poison every verdict downstream.
    """

    value: float
    unit: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            msg = f"threshold value must be finite, got {self.value!r}"
            raise ValueError(msg)
        if not self.unit.strip():
            msg = "threshold requires a non-empty unit ('1' for dimensionless)"
            raise ValueError(msg)
        # mypy enforces this for literal arguments but is silent for Any -
        # the route YAML-built thresholds (#5/#6) take - so the invariant
        # must also hold at runtime. isinstance, not truthiness, so a
        # falsy-but-valid Provenance variant could not regress it (#21).
        if not isinstance(self.provenance, Provenance):
            msg = f"threshold provenance must be a Provenance, got {self.provenance!r}"
            raise TypeError(msg)


@dataclass(frozen=True)
class MaxOfFloors:
    """The tightest of several floors, keeping every constituent visible.

    The combined object exposes ``value``/``unit``/``provenance`` like a
    ``Threshold``, so checks consume it identically, while the check pages
    (#11) can still render every floor that was considered and which one
    governs. On a tie the earliest-listed floor governs, so combination
    order is deterministic.
    """

    floors: tuple[Threshold, ...]

    def __post_init__(self) -> None:
        if not self.floors:
            msg = "MaxOfFloors requires at least one floor"
            raise ValueError(msg)
        units = {floor.unit for floor in self.floors}
        if len(units) > 1:
            msg = f"floors must share a unit, got {sorted(units)}"
            raise ValueError(msg)

    @property
    def governing(self) -> Threshold:
        """The floor whose value wins - the tightest one."""
        return max(self.floors, key=lambda floor: floor.value)

    @property
    def value(self) -> float:
        return self.governing.value

    @property
    def unit(self) -> str:
        return self.floors[0].unit

    @property
    def provenance(self) -> Provenance:
        """The governing floor's provenance - the reason the value holds."""
        return self.governing.provenance


ThresholdLike: TypeAlias = Threshold | MaxOfFloors


class MissingThresholdsError(LookupError):
    """No thresholds exist for the requested variable; the run must refuse."""


class ThresholdTable:
    """Resolved thresholds, keyed by variable then by threshold name.

    There is no default and no fallback lookup: an unknown variable raises
    ``MissingThresholdsError`` naming what was asked for and what exists.
    """

    def __init__(self, by_variable: Mapping[str, Mapping[str, ThresholdLike]]) -> None:
        self._by_variable = {
            variable: dict(thresholds) for variable, thresholds in by_variable.items()
        }

    @property
    def variables(self) -> frozenset[str]:
        return frozenset(self._by_variable)

    def for_variable(self, standard_name: str) -> Mapping[str, ThresholdLike]:
        if standard_name not in self._by_variable:
            known = ", ".join(sorted(self._by_variable)) or "none"
            msg = (
                f"no thresholds for variable {standard_name!r}; "
                f"thresholds exist for: {known}. Refusing to fall back."
            )
            raise MissingThresholdsError(msg)
        return self._by_variable[standard_name]
