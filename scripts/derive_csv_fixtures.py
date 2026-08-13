"""Write the CSV-bundle fixtures out of the pristine workbook (#3, slice 6).

Run once; the outputs are committed and hash-pinned in
``tests/test_fixture_hashes.py``. They exist so the CSV adapter is tested
against a bundle whose canonical record is *known* - the one the workbook
produces - rather than against a synthetic file that only proves the adapter
agrees with itself.

Deriving beats hand-writing for the same reason the checksum gate exists: a
hand-made fixture encodes what its author believed the format contained, and
believing was the failure mode. These carry the real headers, the real
statistics and the real 3,029 rows.

This is a fixture-generation step run by a person, never by a test and never
by the tool: it reads ``docs/data/`` and writes ``tests/data/``, and rerunning
it must reproduce the committed bytes exactly (LF endings, UTF-8, no BOM).

Usage: uv run python scripts/derive_csv_fixtures.py
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = REPO_ROOT / "docs" / "data" / "yellow_buoy_temps.xlsx"
OUT = REPO_ROOT / "tests" / "data" / "csv_bundle"
# The sheet a table lives in, and the file it becomes.
TABLES = {"Data": "data.csv", "Events": "events.csv", "Details": "details.csv"}
# The workbook stores naive local Excel serials; sources.yaml declares this
# format for reading them back, so the two must stay in step.
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime(TIMESTAMP_FORMAT)
    return str(value)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    try:
        for sheet, name in TABLES.items():
            rows = [
                [_cell(value) for value in row]
                for row in workbook[sheet].iter_rows(values_only=True)
            ]
            width = max(len(row) for row in rows)
            path = OUT / name
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerows([row + [""] * (width - len(row)) for row in rows])
            print(f"{path.relative_to(REPO_ROOT).as_posix()}: {len(rows)} rows")
    finally:
        workbook.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
