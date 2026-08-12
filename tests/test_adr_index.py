"""The ADR index must not drift from the ADRs (#1).

`docs/decisions/README.md` is a hand-written table, and a hand-written index
of a growing directory goes stale the first time someone adds a file and
forgets the row. The failure is quiet: the index still looks complete, so a
reader trusts it and never learns that 0007 exists. These tests make the
omission loud at the commit that causes it.

The deliberate 0003 gap is asserted rather than tolerated: if someone ever
issues a 0003, the assertion fails and the README's explanation of the gap
has to be removed in the same change.
"""

from __future__ import annotations

import re
from pathlib import Path

DECISIONS = Path(__file__).resolve().parents[1] / "docs" / "decisions"
INDEX = DECISIONS / "README.md"

# 0003 was skipped when 0004 and 0005 landed together; see the README.
NEVER_ISSUED = {"0003"}


def _adr_files() -> dict[str, Path]:
    return {p.name[:4]: p for p in sorted(DECISIONS.glob("[0-9][0-9][0-9][0-9]-*.md"))}


def test_every_adr_is_linked_from_the_index() -> None:
    index_text = INDEX.read_text(encoding="utf-8")
    missing = [p.name for p in _adr_files().values() if f"({p.name})" not in index_text]
    assert not missing, f"ADRs exist but are not linked from {INDEX.name}: {missing}"


def test_every_indexed_link_resolves() -> None:
    links = re.findall(r"\]\((\d{4}-[a-z0-9-]+\.md)\)", INDEX.read_text(encoding="utf-8"))
    assert links, "the index links to no ADRs at all"
    broken = [name for name in links if not (DECISIONS / name).is_file()]
    assert not broken, f"{INDEX.name} links to files that do not exist: {broken}"


def test_numbers_are_unique() -> None:
    numbers = [p.name[:4] for p in sorted(DECISIONS.glob("[0-9][0-9][0-9][0-9]-*.md"))]
    assert len(numbers) == len(set(numbers)), f"duplicate ADR numbers: {numbers}"


def test_recorded_gaps_stay_unissued() -> None:
    # Numbers are permanent and never reassigned. Issuing a recorded gap is
    # therefore not a merge conflict but a silent identity collision with a
    # number the README tells readers does not exist.
    issued = set(_adr_files())
    collisions = sorted(issued & NEVER_ISSUED)
    assert not collisions, (
        f"ADR {collisions} is recorded in {INDEX.name} as never issued. "
        "Numbers are not reassigned - use the next free number and update the README."
    )
