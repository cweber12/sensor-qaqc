"""The registry id set only ever grows (#1, #2).

``check_ids.txt`` is the committed, append-only record of every id ever
registered; the assembled registry must equal it exactly. A new check
appends a line (a visible one-line diff); a rename or removal makes one
of the two assertions here go red, because ids live in archived run
folders forever and renaming one breaks historical data.

Read via ``importlib.resources`` so the same test also proves the record
ships as package data, like ``layers.toml``.
"""

from __future__ import annotations

import importlib.resources

from sensor_qaqc.cli.registry import build_registry


def committed_ids() -> list[str]:
    raw = importlib.resources.files("sensor_qaqc").joinpath("check_ids.txt").read_text("utf-8")
    lines = [line.strip() for line in raw.splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def test_the_committed_record_has_no_duplicates() -> None:
    ids = committed_ids()
    assert len(ids) == len(set(ids))


def test_every_committed_id_is_still_registered() -> None:
    # A rename or a deletion trips this side: ids are permanent.
    registered = build_registry().ids()
    missing = [check_id for check_id in committed_ids() if check_id not in registered]
    assert missing == [], (
        f"ids in check_ids.txt but not registered (renamed or removed?): {missing}. "
        "check_ids are permanent; retire the code, never the id."
    )


def test_every_registered_id_is_committed() -> None:
    # A new check trips this side until its id is appended to the record.
    committed = set(committed_ids())
    unrecorded = sorted(build_registry().ids() - committed)
    assert unrecorded == [], (
        f"registered ids missing from check_ids.txt: {unrecorded}. "
        "Append them (append-only) in the same commit that registers them."
    )
