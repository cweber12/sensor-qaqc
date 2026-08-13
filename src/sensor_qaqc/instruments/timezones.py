"""Resolving the local label an export declares into UTC (#3).

An export writes naive local timestamps and declares the zone as an
*abbreviation* in a column header - ``Date-Time (PDT)``. An abbreviation is not
a zone: ``CST`` is US Central Standard in one hemisphere and China Standard in
another, six hours and a sign apart. So the reader resolves only labels it can
defend and refuses the rest, naming what it knows. An operator whose export
carries an unknown label supplies the record's timestamps' offset knowingly
rather than having one guessed for them.

The table is deliberately small and grows with the exports actually met. Both
entries are US Pacific, the zone of the deployment and of the host that wrote
these files, either side of the March/November transition.

**A record spanning a transition** is not resolved by a fixed offset, and this
module does not pretend otherwise: the two local stamps around the November
repeat are identical, so the grid contract sees a duplicate timestamp and
refuses. That is the correct outcome - the file is ambiguous about which of the
two hours a sample belongs to, and inventing an answer is exactly what the
no-interpolation rule exists to prevent elsewhere.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

# label -> (local - UTC). US Pacific, per the IANA database's America/Los_Angeles
# entry: PST is UTC-8, PDT is UTC-7.
LOCAL_OFFSETS: Mapping[str, timedelta] = {
    "PST": timedelta(hours=-8),
    "PDT": timedelta(hours=-7),
}


class UnknownTimezoneLabelError(LookupError):
    """The export declares a zone label this reader will not guess at."""


def offset_for(label: str) -> timedelta:
    """Return the (local - UTC) offset for a declared label, or refuse."""
    if label not in LOCAL_OFFSETS:
        known = ", ".join(sorted(LOCAL_OFFSETS))
        raise UnknownTimezoneLabelError(
            f"the export declares the zone label {label!r}, which this reader does not"
            f" resolve; it knows: {known}. An abbreviation is not a zone - supply the"
            " timestamps' offset rather than having one assumed."
        )
    return LOCAL_OFFSETS[label]


def to_utc(naive_local: Sequence[datetime], label: str) -> pd.DatetimeIndex:
    """Convert naive local stamps to a tz-aware UTC index using the label."""
    index = pd.DatetimeIndex(naive_local)
    if index.tz is not None:
        raise ValueError(f"timestamps are already zoned ({index.tz}); expected naive local stamps")
    localised: pd.DatetimeIndex = (index - offset_for(label)).tz_localize("UTC")
    return localised
