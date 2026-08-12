"""The minimal view of a record that admissibility and compute see (#2).

The canonical record itself is #3's to build; defining it here would
preempt that PRD. This protocol carries only what the framework needs:
the identity key that selects thresholds (``variable``, a CF
``standard_name``), the masked series checks compute on, and the scalar
facts requirements are evaluated against. #3's canonical record will
satisfy it; the conformance battery constructs synthetic ones.

``series`` follows the masking contract (#3, #6): a uniform time grid at
exactly ``dt``, gaps and QC-rejected points as NaN in place - never
dropped, never interpolated. That is why ``n_valid`` exists separately:
significance arithmetic uses ``n_valid``, never ``len()``. (The name is
``series``, not pandas' conventional ``.values``, because ruff's
pandas-vet reads any ``.values`` attribute as the ndarray anti-pattern
and would demand a suppression at every use site.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import timedelta

    import pandas as pd


class RecordView(Protocol):
    """Structural interface between the framework and any record source."""

    @property
    def variable(self) -> str:
        """CF ``standard_name`` - the key thresholds are resolved under."""
        ...

    @property
    def series(self) -> pd.Series:
        """The observations on a uniform grid at ``dt``, gaps as NaN in place."""
        ...

    @property
    def dt(self) -> timedelta:
        """The sampling interval of the uniform grid."""
        ...

    @property
    def duration(self) -> timedelta:
        """First-to-last span of the grid, gaps included."""
        ...

    @property
    def n_valid(self) -> int:
        """Count of non-NaN observations - the only n statistics may use."""
        ...

    @property
    def gap_fraction(self) -> float:
        """Fraction of grid points that are NaN, in [0, 1]."""
        ...
