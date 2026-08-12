"""Domain and channel vocabulary (#1, #2).

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
