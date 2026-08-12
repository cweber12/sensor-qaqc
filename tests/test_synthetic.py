"""Generators are seeded, regular-gridded, and shaped as declared (#2)."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from sensor_qaqc.core.synthetic import (
    AR1_TAU,
    BATTERY_DT,
    BATTERY_SAMPLES,
    NEGATIVE_CONTROLS,
    QUANTISED_STEP,
    SyntheticRecord,
    decimate,
    derive_seed,
    flatline,
    quantised,
    ramp,
    red_noise,
    white_noise,
    with_gaps,
)


def test_seeds_are_stable_and_do_not_share_a_stream() -> None:
    # Same triple, same seed - and registering a new check (a different
    # check_id) must not shift any other check's draws.
    assert derive_seed("quantisation", "red_noise", 3) == derive_seed(
        "quantisation", "red_noise", 3
    )
    distinct = {
        derive_seed("quantisation", "red_noise", 0),
        derive_seed("quantisation", "red_noise", 1),
        derive_seed("quantisation", "negative_white_noise", 0),
        derive_seed("spectral_slope", "red_noise", 0),
    }
    assert len(distinct) == len(["one", "two", "three", "four"])


@pytest.mark.parametrize("generator", [white_noise, flatline, ramp, quantised, red_noise])
def test_every_generator_builds_a_clean_regular_utc_grid(
    generator: Callable[[int], SyntheticRecord],
) -> None:
    record = generator(derive_seed("test", "grid", 0))
    index = record.series.index
    assert len(record.series) == BATTERY_SAMPLES
    assert record.gap_fraction == 0.0
    assert record.n_valid == BATTERY_SAMPLES
    assert str(index.tz) == "UTC"
    assert ((index[1:] - index[:-1]) == pd.Timedelta(BATTERY_DT)).all()
    assert record.series.notna().all()


def test_identical_seeds_reproduce_byte_identical_series() -> None:
    seed = derive_seed("test", "determinism", 0)
    assert red_noise(seed).series.equals(red_noise(seed).series)
    assert not red_noise(seed).series.equals(red_noise(seed + 1).series)


def test_an_irregular_index_is_refused_at_construction() -> None:
    # The recorded failure: a gappy index vacates every battery case.
    regular = white_noise(derive_seed("test", "irregular", 0), n=10)
    holed = regular.series.drop(regular.series.index[3])
    with pytest.raises(ValueError, match="clean regular index"):
        SyntheticRecord(variable="sea_water_temperature", series=holed, dt=BATTERY_DT)


def test_the_quantised_control_lives_on_the_encoder_grid() -> None:
    record = quantised(derive_seed("test", "quantised", 0))
    on_grid = np.round(record.series / QUANTISED_STEP) * QUANTISED_STEP
    assert np.allclose(record.series, on_grid, atol=1e-12)
    # Noise at half a step collapses onto very few distinct levels.
    assert record.series.nunique() < 10  # noqa: PLR2004 - "a handful" made concrete


def test_the_ramp_is_monotonic_and_the_flatline_is_constant() -> None:
    assert ramp(derive_seed("test", "ramp", 0)).series.is_monotonic_increasing
    level = flatline(derive_seed("test", "flatline", 0)).series.to_numpy()
    assert np.ptp(level) == 0.0


def test_red_noise_carries_the_declared_memory() -> None:
    record = red_noise(derive_seed("test", "ar1", 0))
    expected = math.exp(-BATTERY_DT / AR1_TAU)
    assert record.series.autocorr(lag=1) == pytest.approx(expected, abs=0.03)


def test_white_noise_is_memoryless() -> None:
    record = white_noise(derive_seed("test", "white", 0))
    assert abs(record.series.autocorr(lag=1)) < 0.05  # noqa: PLR2004 - ~2 sigma at n=5040


def test_decimation_multiplies_dt_and_keeps_the_grid_regular() -> None:
    base = red_noise(derive_seed("test", "decimate", 0))
    coarse = decimate(base, 10)
    assert coarse.dt == timedelta(minutes=60)
    assert len(coarse.series) == math.ceil(len(base.series) / 10)
    index = coarse.series.index
    assert ((index[1:] - index[:-1]) == pd.Timedelta(coarse.dt)).all()


def test_gaps_are_nan_in_place_and_the_grid_never_shrinks() -> None:
    base = red_noise(derive_seed("test", "gaps", 0))
    gappy = with_gaps(base, 0.30, derive_seed("test", "gaps", 1))
    assert len(gappy.series) == len(base.series)
    assert gappy.gap_fraction == pytest.approx(0.30, abs=0.001)
    assert gappy.series.index.equals(base.series.index)


def test_the_negative_control_set_is_the_prd_four() -> None:
    assert set(NEGATIVE_CONTROLS) == {"white_noise", "flatline", "ramp", "quantised"}
