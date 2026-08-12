"""Seeded synthetic records for the conformance battery (#2, ADR 0006).

Every series is built on a **clean regular index**: an earlier attempt fed
the negative controls a real gappy index while declaring a fixed dt, which
shattered the record into one-sample segments, made every lag statistic
NaN, and returned INCONCLUSIVE for all cases - passing the assertion while
testing nothing. ``SyntheticRecord`` therefore refuses construction on an
irregular index; gaps enter only through :func:`with_gaps`, as NaN in
place per the masking contract (#3).

Seeds derive from ``sha256(check_id/case/index)``, never from one global
stream or the builtin ``hash`` (process-salted): with a shared stream,
registering a new check would shift every later check's draws, moving an
unrelated check's measured false-alarm rate and blaming the wrong commit.

Battery parameters, each with its reason (expanded in ADR 0006):

- ``BATTERY_DT`` = 6 min - the finest rung of the #2 decimation ladder,
  and comfortably above the MX2204's 4-min t90 in stirred water (Onset
  spec, ``docs/qc_refs/MX2203_MX2204_QAQC_Reference.md``), so a synthetic
  sample is a resolved measurement, not sensor smoothing.
- ``BATTERY_DURATION`` = 21 d - the deployment length in the recorded
  prior-failure cases (#3's wrong-span incident; #8's Rayleigh table),
  above the 15 d constituent-derivation floor (Zervas 1999, via #8).
- ``AR1_TAU`` = 1 h - the coastal water-temperature decorrelation scale
  recorded in #2 as the physical e-folding floor; AR(1) itself is the
  standard geophysical null (autocorrelation compendium, Part G: the
  default alternative to randomness is autoregressive; red backgrounds
  are fitted as AR(1)). phi = exp(-dt/tau).
- ``QUANTISED_STEP`` = 0.01 degC - the MX2204's stated resolution (Onset
  spec, table row "Resolution"); the quantised control's noise sigma is
  half a step, so the artifact dominates the signal.
- Amplitudes (``NOISE_SIGMA``, ``RAMP_SPAN``) are order-of-magnitude
  choices for sub-daily coastal variability; checks must be scale-aware
  through thresholds, not through the battery's luck in picking a scale.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from functools import cached_property
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Callable

BATTERY_VARIABLE = "sea_water_temperature"
BATTERY_DT = timedelta(minutes=6)
BATTERY_DURATION = timedelta(days=21)
BATTERY_SAMPLES = BATTERY_DURATION // BATTERY_DT  # 5040
AR1_TAU = timedelta(hours=1)
NOISE_SIGMA = 0.1  # degC
RAMP_SPAN = 2.0  # degC over the record
QUANTISED_STEP = 0.01  # degC, MX2204 resolution
QUANTISED_SIGMA = QUANTISED_STEP / 2
BASELINE_DEGC = 15.0

# Fixed epoch so identical seeds give byte-identical records on any day.
_EPOCH = pd.Timestamp("2026-01-01T00:00:00", tz="UTC")


def derive_seed(check_id: str, case_name: str, index: int) -> int:
    """Stable per-(check, case, realisation) seed; no shared stream."""
    digest = hashlib.sha256(f"{check_id}/{case_name}/{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


@dataclass(frozen=True)
class SyntheticRecord:
    """A concrete RecordView on a verified-regular grid."""

    variable: str
    series: pd.Series
    dt: timedelta

    def __post_init__(self) -> None:
        index = self.series.index
        if len(index) < 2:  # noqa: PLR2004 - a grid needs two points to have a spacing
            msg = "a synthetic record needs at least two samples"
            raise ValueError(msg)
        steps = index[1:] - index[:-1]
        if not (steps == pd.Timedelta(self.dt)).all():
            msg = (
                "synthetic records are built on a clean regular index; an"
                f" irregular one silently vacates the battery (got steps"
                f" {pd.unique(steps)!r} against dt={self.dt})"
            )
            raise ValueError(msg)

    @cached_property
    def duration(self) -> timedelta:
        span: timedelta = (self.series.index[-1] - self.series.index[0]).to_pytimedelta()
        return span

    @cached_property
    def n_valid(self) -> int:
        return int(self.series.notna().sum())

    @cached_property
    def gap_fraction(self) -> float:
        return 1.0 - self.n_valid / len(self.series)


def _record(data: np.ndarray, dt: timedelta) -> SyntheticRecord:
    index = pd.date_range(start=_EPOCH, periods=len(data), freq=dt, tz="UTC")
    return SyntheticRecord(
        variable=BATTERY_VARIABLE,
        series=pd.Series(data, index=index),
        dt=dt,
    )


def white_noise(seed: int, n: int = BATTERY_SAMPLES, dt: timedelta = BATTERY_DT) -> SyntheticRecord:
    """Memoryless noise: nearly anything beats it, which is why it is only a control."""
    rng = np.random.default_rng(seed)
    return _record(BASELINE_DEGC + rng.normal(0.0, NOISE_SIGMA, n), dt)


def flatline(seed: int, n: int = BATTERY_SAMPLES, dt: timedelta = BATTERY_DT) -> SyntheticRecord:
    """Generate a constant level - zero variance, the classic dead sensor."""
    rng = np.random.default_rng(seed)
    level = BASELINE_DEGC + rng.normal(0.0, 1.0)
    return _record(np.full(n, level), dt)


def ramp(seed: int, n: int = BATTERY_SAMPLES, dt: timedelta = BATTERY_DT) -> SyntheticRecord:
    """Generate a pure linear trend - all memory, no ocean."""
    rng = np.random.default_rng(seed)
    start = BASELINE_DEGC + rng.normal(0.0, 1.0)
    return _record(start + np.linspace(0.0, RAMP_SPAN, n), dt)


def quantised(seed: int, n: int = BATTERY_SAMPLES, dt: timedelta = BATTERY_DT) -> SyntheticRecord:
    """Noise below the encoder step: the record is mostly the quantiser."""
    rng = np.random.default_rng(seed)
    raw = BASELINE_DEGC + rng.normal(0.0, QUANTISED_SIGMA, n)
    return _record(np.round(raw / QUANTISED_STEP) * QUANTISED_STEP, dt)


def red_noise(seed: int, n: int = BATTERY_SAMPLES, dt: timedelta = BATTERY_DT) -> SyntheticRecord:
    """AR(1) with the coastal decorrelation scale - the geophysical null.

    phi = exp(-dt/tau); x0 is drawn from the stationary distribution so
    the series carries no start-up transient, and the innovation variance
    is scaled so the stationary sigma is ``NOISE_SIGMA`` at every dt.
    """
    rng = np.random.default_rng(seed)
    phi = float(np.exp(-dt / AR1_TAU))
    innovation_sigma = NOISE_SIGMA * float(np.sqrt(1.0 - phi**2))
    x = np.empty(n)
    x[0] = rng.normal(0.0, NOISE_SIGMA)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0.0, innovation_sigma)
    return _record(BASELINE_DEGC + x, dt)


NEGATIVE_CONTROLS: dict[str, Callable[[int], SyntheticRecord]] = {
    "white_noise": white_noise,
    "flatline": flatline,
    "ramp": ramp,
    "quantised": quantised,
}


def decimate(record: SyntheticRecord, factor: int) -> SyntheticRecord:
    """Simulate a coarser logging interval by taking every ``factor``-th sample.

    Stride selection, not averaging: a logger at 60 min takes instantaneous
    readings, it does not low-pass the 6-min series it never saw.
    """
    if factor < 1:
        msg = f"decimation factor must be >= 1, got {factor}"
        raise ValueError(msg)
    return SyntheticRecord(
        variable=record.variable,
        series=record.series.iloc[::factor],
        dt=record.dt * factor,
    )


def with_gaps(record: SyntheticRecord, fraction: float, seed: int) -> SyntheticRecord:
    """Mask a fraction of samples to NaN in place - the grid never shrinks (#3)."""
    if not 0.0 <= fraction < 1.0:
        msg = f"gap fraction must be in [0, 1), got {fraction}"
        raise ValueError(msg)
    rng = np.random.default_rng(seed)
    n = len(record.series)
    masked = record.series.copy()
    positions = rng.choice(n, size=round(fraction * n), replace=False)
    masked.iloc[positions] = np.nan
    return SyntheticRecord(variable=record.variable, series=masked, dt=record.dt)
