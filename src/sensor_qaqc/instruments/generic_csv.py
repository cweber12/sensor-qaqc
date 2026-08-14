"""Reading a CSV that states nothing about itself (#3).

The second filler of the canonical schema, and the one that proves the claim:
a format with no vendor metadata at all reaches the same record as a
HOBOconnect export, through the same assembly function, with nothing
downstream aware of the difference.

What it cannot do is the point. A bare CSV declares no unit, no zone label, no
logging interval and no logger identity, so this reader extracts none of them
and **guesses at none of them**: they arrive as operator-supplied metadata or
assembly refuses, naming each one. Publishing no statistics, it also has no
checksum gate - reported as *not applicable*, with its reason, rather than
passing quietly.

That asymmetry is the mechanism the PRD promises: prompts shrink as extractors
improve. Nothing here is a fallback for a format we failed to parse; it is the
floor, and every fact a real format states is one fewer question.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from sensor_qaqc.instruments.containers import read_tables
from sensor_qaqc.instruments.extraction import ExtractedMetadata, Extraction
from sensor_qaqc.instruments.tables import parse_data

if TYPE_CHECKING:
    from pathlib import Path

    from sensor_qaqc.instruments.sources import SourceFormat


class GenericCsvReader:
    """Reads a single-series CSV: the timestamps, the values, and no more."""

    def __init__(self, source_format: SourceFormat) -> None:
        if source_format.data.header_declares:
            raise ValueError(
                f"{source_format.format_id} declares that its header states"
                f" {sorted(source_format.data.header_declares)}; this reader is for sources"
                " that state nothing, so a format with a speaking header wants its own"
            )
        self._format = source_format

    @property
    def format_id(self) -> str:
        return self._format.format_id

    def read(self, path: Path) -> Extraction:
        """Parse the table. Everything absent is reported, never invented."""
        loaded = read_tables(self._format, path)
        data = parse_data(loaded.tables["data"], self._format.data, cells=loaded.cells)
        notes = [
            *data.notes,
            (
                "this source publishes no metadata: the unit, the zone label, the logging"
                " interval and the logger's identity are all operator-supplied, and there"
                " are no vendor statistics for the checksum gate to reproduce"
            ),
        ]
        return Extraction(
            format_id=self.format_id,
            timestamps=data.timestamps,
            values=np.asarray(data.values, dtype=np.float64),
            # Every field left None on purpose: see the module docstring.
            metadata=ExtractedMetadata(),
            published=None,
            notes=tuple(notes),
        )
