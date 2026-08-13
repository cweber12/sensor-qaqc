"""Which reader reads this source, and which format it is (#3).

One assembly point, no import side effects - the same rule the check registry
follows. A reader registered here is reachable from the command surface with
no further wiring, and a format nobody registered is a refusal rather than a
mysterious absence.

**Selection is by what is actually there**, not by a flag an operator has to
know: the container comes from the path (a workbook file, a directory of CSVs
or a single CSV), and among the formats using that container the one whose
declared tables are *all present* wins, most-metadata-first. That ordering is
the point - a bundle with a details sidecar must not be read as a bare CSV,
because doing so would silently skip the checksum gate on a source that
publishes statistics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sensor_qaqc.instruments.containers import CSV, XLSX
from sensor_qaqc.instruments.generic_csv import GenericCsvReader
from sensor_qaqc.instruments.onset.hoboconnect import HOBOconnectReader

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sensor_qaqc.instruments.extraction import SourceReader
    from sensor_qaqc.instruments.sources import SourceCatalogue, SourceFormat

# format_id -> the reader that implements that shape. Onset's two entries
# share a reader: same tables, same vocabulary, different container.
READERS: dict[str, Callable[[SourceFormat], SourceReader]] = {
    "hoboconnect_xlsx": HOBOconnectReader,
    "hoboconnect_sheets_csv": HOBOconnectReader,
    "generic_csv": GenericCsvReader,
}

SUFFIX_CONTAINERS = {".xlsx": XLSX, ".csv": CSV}


class UnreadableSourceError(LookupError):
    """Nothing registered can read what is at this path."""


def reader_for(path: Path, catalogue: SourceCatalogue) -> SourceReader:
    """Return the reader for the source at ``path``, or refuse saying why."""
    source_format = select_format(path, catalogue)
    return READERS[source_format.format_id](source_format)


def select_format(path: Path, catalogue: SourceCatalogue) -> SourceFormat:
    """Return the format whose container and tables match what is at ``path``."""
    if not path.exists():
        raise UnreadableSourceError(f"there is nothing at {path.as_posix()!r} to read")
    container = CSV if path.is_dir() else SUFFIX_CONTAINERS.get(path.suffix.lower())
    if container is None:
        raise UnreadableSourceError(
            f"nothing registered reads {path.name!r};"
            f" known containers are: {', '.join(sorted(SUFFIX_CONTAINERS))} or a directory of CSVs"
        )
    candidates = [
        catalogue.for_format(format_id)
        for format_id in sorted(READERS)
        if catalogue.for_format(format_id).container == container
    ]
    # Most declared tables first: a source that carries its metadata must be
    # read as the format that reads that metadata.
    for source_format in sorted(candidates, key=lambda f: -len(f.tables)):
        if _tables_present(source_format, path):
            return source_format
    described = ", ".join(
        f"{f.format_id} (needs {', '.join(sorted(f.tables.values()))})" for f in candidates
    )
    raise UnreadableSourceError(
        f"no registered {container} format matches {path.as_posix()!r}; tried: {described}"
    )


def _tables_present(source_format: SourceFormat, path: Path) -> bool:
    if source_format.container == XLSX:
        return path.is_file()
    directory = path if path.is_dir() else path.parent
    return all(
        (path if table == "data" and not path.is_dir() else directory / name).is_file()
        for table, name in source_format.tables.items()
    )
