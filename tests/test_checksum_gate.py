"""Reproducing the vendor's own statistics is the cheapest check in the tool (#3).

Onset computes ``Samples``, ``Max``, ``Min``, ``Avg`` and ``Std Dev`` without
us and publishes them in the export. Reproducing them from our parse is a
checksum over column selection, unit handling, header offset, timezone
handling and row dropping - for about ten lines of arithmetic.

The two fixtures are the two outcomes. The pristine export reproduces all five;
the Google Sheets round-trip of it, with seven out-of-water samples trimmed
away, does not - and the gate names which. Row-counting blessed that file
(header + 3,022 data + 6 mangled + 1 trailing = 3,030 rows, "matching" the
published 3,029); reproducing the statistics catches it.

The gate runs on the raw parse, before any trim or mask, because Details
describes everything the logger recorded rather than the subset that survives
analysis.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from sensor_qaqc.instruments.checksum import (
    PUBLISHED_TOLERANCE,
    verify_published_statistics,
)
from sensor_qaqc.instruments.extraction import ExtractedMetadata, Extraction
from sensor_qaqc.instruments.onset.hoboconnect import HOBOconnectReader
from sensor_qaqc.instruments.sources import load_source_catalogue
from workbook_builder import statistics_for, write_workbook

if TYPE_CHECKING:
    from sensor_qaqc.instruments.checksum import GateOutcome

PRISTINE = Path(__file__).resolve().parents[1] / "docs" / "data" / "yellow_buoy_temps.xlsx"
EDITED = Path(__file__).resolve().parent / "data" / "yellow_buoy_temps_edited.xlsx"

# Measured on the two fixtures; the audit addendum on #3 records the same.
PRISTINE_SAMPLES, EDITED_SAMPLES = 3029, 3022
PUBLISHED_MINIMUM, EDITED_MINIMUM = 58.60, 63.96
PUBLISHED_STD_DEV, EDITED_STD_DEV = 2.38, 2.37
STATISTIC_COUNT = 7


def _gate(path: Path) -> GateOutcome:
    reader = HOBOconnectReader(load_source_catalogue().for_format("hoboconnect_xlsx"))
    return verify_published_statistics(reader.read(path))


def _samples(n: int) -> list[tuple[datetime, float]]:
    first = datetime(2026, 7, 11, 7, 0)  # noqa: DTZ001 - naive local, as the sheet stores it
    return [(first + timedelta(minutes=10 * k), 70.0 + k / 100) for k in range(n)]


# --- The two fixtures are the two outcomes. ---


def test_the_pristine_export_reproduces_every_published_statistic() -> None:
    outcome = _gate(PRISTINE)
    assert outcome.applicable
    assert not outcome.refused
    assert len(outcome.checks) == STATISTIC_COUNT
    assert outcome.mismatches == ()


def test_the_edited_copy_is_refused_and_told_which_statistics_disagree() -> None:
    outcome = _gate(EDITED)
    assert outcome.refused
    named = {mismatch.name for mismatch in outcome.mismatches}
    assert {"samples", "minimum", "std_dev"} <= named
    # Trimming the first six samples and the last one moves both ends of the
    # record too, so the gate sees five mismatches, not the three the audit
    # listed from the statistics table alone.
    assert {"first_sample_time", "last_sample_time"} <= named
    assert "maximum" not in named
    assert "average" not in named


def test_the_refusal_quotes_both_numbers_for_every_mismatch() -> None:
    # "the gate refused" is not actionable; "Samples 3022 against a published
    # 3029" is. The report is what an operator reads.
    report = _gate(EDITED).report
    for expected in (str(EDITED_SAMPLES), str(PRISTINE_SAMPLES), f"{EDITED_MINIMUM:.2f}"):
        assert expected in report
    assert f"{PUBLISHED_MINIMUM:.2f}" in report


def test_the_standard_deviation_convention_is_inert_on_this_record() -> None:
    # Onset does not say whether its Std Dev is the population or the sample
    # one. At n = 3029 the two differ by 0.0004, far inside the tolerance, so
    # the gate's choice cannot decide the outcome - which is why documenting
    # the choice is enough and deriving it is not needed.
    reader = HOBOconnectReader(load_source_catalogue().for_format("hoboconnect_xlsx"))
    readings = [float(v) for v in reader.read(PRISTINE).values]  # noqa: PD011 - an Extraction is not a DataFrame
    assert abs(statistics.pstdev(readings) - PUBLISHED_STD_DEV) <= PUBLISHED_TOLERANCE
    assert abs(statistics.stdev(readings) - PUBLISHED_STD_DEV) <= PUBLISHED_TOLERANCE


# --- A parse corrupted on purpose, in the two ways the gate exists to catch. ---


def test_a_parse_that_read_the_values_in_the_wrong_unit_is_refused(tmp_path: Path) -> None:
    # The statistics are published in the export's native unit. A reader that
    # converted on the way in - the exact habit the native-unit rule bans -
    # produces plausible numbers that reproduce nothing.
    fahrenheit = _samples(12)
    celsius = [(when, (value - 32) / 1.8) for when, value in fahrenheit]
    path = write_workbook(
        tmp_path / "converted.xlsx", celsius, published=statistics_for(fahrenheit)
    )
    outcome = _gate(path)
    assert outcome.refused
    assert {"maximum", "minimum", "average"} <= {m.name for m in outcome.mismatches}


def test_a_parse_missing_the_last_row_is_refused(tmp_path: Path) -> None:
    samples = _samples(12)
    path = write_workbook(tmp_path / "short.xlsx", samples[:-1], published=statistics_for(samples))
    outcome = _gate(path)
    assert outcome.refused
    assert {"samples", "last_sample_time"} <= {m.name for m in outcome.mismatches}


# --- The tolerance follows from how the statistics are published. ---


def test_a_difference_inside_the_last_published_place_passes(tmp_path: Path) -> None:
    samples = _samples(12)
    published = statistics_for(samples)
    published["Avg"] = f"{statistics.fmean(v for _, v in samples) + 0.004:.3f}"
    path = write_workbook(tmp_path / "near.xlsx", samples, published=published)
    assert not _gate(path).refused


def test_a_difference_beyond_the_last_published_place_is_refused(tmp_path: Path) -> None:
    samples = _samples(12)
    published = statistics_for(samples)
    published["Avg"] = f"{statistics.fmean(v for _, v in samples) + 0.006:.3f}"
    path = write_workbook(tmp_path / "far.xlsx", samples, published=published)
    outcome = _gate(path)
    assert outcome.refused
    assert [m.name for m in outcome.mismatches] == ["average"]


def test_the_tolerance_is_half_of_the_last_place_the_export_publishes() -> None:
    # Not a chosen number: Onset publishes 2-decimal strings, so anything
    # inside half of the last place is the same published value. Comparing
    # with round() instead would false-fail on a .xx5 tie.
    assert pytest.approx(0.005) == PUBLISHED_TOLERANCE


# --- A format that publishes nothing: not applicable, and said out loud. ---


def test_a_source_without_published_statistics_reports_not_applicable() -> None:
    index = pd.date_range("2026-07-11T14:00:00Z", periods=4, freq="10min")
    extraction = Extraction(
        format_id="generic_csv",
        timestamps=index,
        values=np.arange(4, dtype=float),
        metadata=ExtractedMetadata(units="degC"),
    )
    outcome = verify_published_statistics(extraction)
    assert not outcome.applicable
    assert not outcome.refused
    assert "no vendor statistics" in outcome.reason
    assert "generic_csv" in outcome.report
