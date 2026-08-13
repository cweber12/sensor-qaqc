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
    "docs/data/yellow_buoy_temps.xlsx": (
        "9b6294534e13dd88aec674cccb99d0b53201ebf9bce955fe3d25811dd3e9f55e"
    ),
    # A Google Sheets round-trip of the HOBOconnect export with the seven
    # out-of-water samples trimmed, so its Data sheet no longer reproduces
    # its own Details statistics (#3 audit, 2026-08-12). Kept as the
    # real-world corrupt case the ingest checksum gate must refuse.
    "tests/data/yellow_buoy_temps_edited.xlsx": (
        "9b6294534e13dd88aec674cccb99d0b53201ebf9bce955fe3d25811dd3e9f55e"
    ),
}


def _fixture_path(rel: str) -> Path:
    return REPO_ROOT / rel


def test_fixture_bytes_match_committed_hash() -> None:
    actual = {rel: hashlib.sha256(_fixture_path(rel).read_bytes()).hexdigest() for rel in FIXTURES}
    assert actual == FIXTURES


def test_text_fixture_contains_no_crlf() -> None:
    # Guards the other direction: a fixture re-saved with CRLF and a
    # "helpfully" updated hash would pass the hash test on every leg while
    # silently changing the bytes every consumer parses.
    #
    # Only the text canary is checked. The workbook is a zip container and
    # will contain 0x0d bytes legitimately, so the same assertion there would
    # fail for a reason that has nothing to do with line-ending conversion;
    # `*.xlsx binary` in .gitattributes is what protects it.
    assert b"\r" not in _fixture_path(EOL_CANARY).read_bytes()
