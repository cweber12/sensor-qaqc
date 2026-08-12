"""Fixture bytes must be identical on every OS - .gitattributes enforcement (#1).

The manifest and #3's checksum gate hash raw bytes. Without the ``-text``
exclusions in .gitattributes, a text fixture checks out CRLF on Windows and
LF on Linux, giving different SHA-256 for the same commit on two CI legs and
breaking #4's determinism acceptance for a reason nobody would guess. The
hash below is the committed value: if this test fails on any leg, line-ending
conversion touched a fixture, and the fix is the attribute - never the hash.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURES = {
    "eol_canary.csv": "31c85a59383f17971b1a0842e220f089634a9bc3f0e59706cffe35273f682309",
}


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "data" / name


def test_fixture_bytes_match_committed_hash() -> None:
    actual = {
        name: hashlib.sha256(_fixture_path(name).read_bytes()).hexdigest() for name in FIXTURES
    }
    assert actual == FIXTURES


def test_text_fixture_contains_no_crlf() -> None:
    # Guards the other direction: a fixture re-saved with CRLF and a
    # "helpfully" updated hash would pass the hash test on every leg while
    # silently changing the bytes every consumer parses.
    assert b"\r" not in _fixture_path("eol_canary.csv").read_bytes()
