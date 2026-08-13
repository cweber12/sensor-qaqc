"""Fixture bytes must be identical on every OS - .gitattributes enforcement (#1).

The manifest and #3's checksum gate hash raw bytes. Without the ``-text``
exclusions in .gitattributes, a text fixture checks out CRLF on Windows and
LF on Linux, giving different SHA-256 for the same commit on two CI legs and
breaking #4's determinism acceptance for a reason nobody would guess. The
hashes below are the committed values: if this test fails on any leg,
line-ending conversion touched a fixture, and the fix is the attribute -
never the hash.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

EOL_CANARY = "tests/data/eol_canary.csv"

# Keys are repo-relative because the guarded fixtures live under two roots:
# tests/data/ holds test inputs, docs/data/ holds the sample workbook that #3
# parses and that the README points a first-time user at. Both are covered by
# `-text` in .gitattributes, so both belong here.
FIXTURES = {
    EOL_CANARY: "31c85a59383f17971b1a0842e220f089634a9bc3f0e59706cffe35273f682309",
    # The pristine HOBOconnect export: all 3,029 samples, and the Details
    # statistics reproduce from the Data sheet (#3 acceptance).
    "docs/data/yellow_buoy_temps.xlsx": (
        "e5f6676e8636273f1ba4aeafa7cc533c439511390ca7d36f9fed6b8b55081efc"
    ),
    # A Google Sheets round-trip of the HOBOconnect export with the seven
    # out-of-water samples trimmed, so its Data sheet no longer reproduces
    # its own Details statistics (#3 audit, 2026-08-12). Kept as the
    # real-world corrupt case the ingest checksum gate must refuse.
    "tests/data/yellow_buoy_temps_edited.xlsx": (
        "9b6294534e13dd88aec674cccb99d0b53201ebf9bce955fe3d25811dd3e9f55e"
    ),
    # The pristine workbook's three sheets written out as CSV files by
    # scripts/derive_csv_fixtures.py, run once (#3 slice 6). Pinned because
    # the CSV adapter's whole claim is that they ingest to the same canonical
    # record the workbook does: if these bytes drift, that comparison is
    # against something nobody derived.
    "tests/data/csv_bundle/data.csv": (
        "75b7571607b1d7341f1d9fba397d9c5ae6cb4337431862ae0f0fc9c0415db0df"
    ),
    "tests/data/csv_bundle/events.csv": (
        "b6b72aefbb537ba9778479fbabed670ef7c5c00a5aee2b1bac1da251deade19f"
    ),
    "tests/data/csv_bundle/details.csv": (
        "d11279ddd8958e233b462954f47131de333c8f5961bebd2cecf23f207ec10a8c"
    ),
}

# Every text fixture, checked for line-ending conversion. The workbooks are
# zip containers and legitimately contain 0x0d, so they are covered by
# `*.xlsx binary` in .gitattributes instead.
TEXT_FIXTURES = tuple(rel for rel in FIXTURES if rel.endswith(".csv"))


def _fixture_path(rel: str) -> Path:
    return REPO_ROOT / rel


def test_fixture_bytes_match_committed_hash() -> None:
    actual = {rel: hashlib.sha256(_fixture_path(rel).read_bytes()).hexdigest() for rel in FIXTURES}
    assert actual == FIXTURES


def test_text_fixtures_contain_no_crlf() -> None:
    # Guards the other direction: a fixture re-saved with CRLF and a
    # "helpfully" updated hash would pass the hash test on every leg while
    # silently changing the bytes every consumer parses.
    converted = [rel for rel in TEXT_FIXTURES if b"\r" in _fixture_path(rel).read_bytes()]
    assert not converted, f"line endings were converted in: {converted}"
