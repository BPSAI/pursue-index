"""Reading the stored source catalogue, once, for every stage that resolves.

Three stages resolve cards against the PV1.4 sitemap catalogue: the identifier
resolver, the era bucketing pass and the coverage report. They read the same
tracked artifact, and they have to read it the same way — the same row
validation, the same drop-and-count bookkeeping, the same answer to "how many
rows does this catalogue actually hold?". A stage with its own loader drifts,
and the drift surfaces as two artifacts disagreeing about the same corpus.

So the load lives here, and each stage publishes what it got: the entries it
resolves against and the number of rows the artifact held that could not become
one. That count belongs in every artifact the load feeds, because "resolved
nothing" and "resolved nothing *and* skipped 400 rows" are different findings.

A missing artifact is not an error. CREST and the government-description route
need no catalogue, so a checkout that has never run the (live) catalogue build
still resolves the cards those routes cover — it simply resolves fewer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from pursue_index.source_index import OUTPUT_PATH as CATALOGUE_PATH
from pursue_index.source_index import SourceEntry, entries_from_rows

__all__ = [
    "LoadedCatalogue",
    "load_catalogue",
]


class LoadedCatalogue(NamedTuple):
    """The catalogue a stage resolves against, and what the artifact cost to read.

    ``dropped_rows`` counts rows the stored artifact held that could not become
    an entry — a row that is not a mapping, one missing a field, or one whose
    URL is not an address a reader can follow.
    """

    entries: list[SourceEntry]
    dropped_rows: int


def load_catalogue(repo_root: Path) -> LoadedCatalogue:
    """Load the tracked catalogue under ``repo_root``, or an empty one."""
    path = repo_root / CATALOGUE_PATH
    if not path.exists():
        return LoadedCatalogue([], 0)
    data = json.loads(path.read_text())
    entries, dropped = entries_from_rows(data.get("entries", []))
    return LoadedCatalogue(entries, dropped)
