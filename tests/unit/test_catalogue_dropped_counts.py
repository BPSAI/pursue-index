"""Tests that a dropped catalogue row is visible in every artifact it affects.

Dropping a row the catalogue cannot use is the right call, and it is only
complete when a reader of the *artifact* can see it happened. Three stages read
the stored catalogue, and each publishes a finding that depends on how much of
it was readable:

* the identifier resolver's claims, which rest on the rows it searched;
* the coverage report's split, which is a statement about how much was searched;
* the era pass's negatives, which rest on having found no claim.

A console line reaches whoever ran the command; the artifact is what anyone else
reads afterwards, so the count goes there too. All three read through one loader
so the figure means the same thing in all three.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.catalogue_load import LoadedCatalogue, load_catalogue
from pursue_index.era_bucketing import bucket
from pursue_index.era_bucketing import build_output as era_build_output
from pursue_index.identifier_resolver import build_output as resolver_build_output
from pursue_index.provenance_report import build_report
from pursue_index.source_index import OUTPUT_PATH as CATALOGUE_PATH

_GOOD_ROW = {
    "url": "https://documents.theblackvault.com/fbi/62-hq-83894.pdf",
    "filename": "62-hq-83894.pdf",
    "last_modified": "Mon, 01 Jun 2015 08:00:00 GMT",
    "agency": "fbi",
    "era": "undated",
    "era_year": None,
}
_MANIFEST = {"cards": [{"card_id": "c1", "title": "A routine transmittal, 2023",
                        "incident_date": "2023", "agency": "DOW"}]}


def _repo_with_catalogue(tmp_path: Path, rows: list[object]) -> Path:
    path = tmp_path / CATALOGUE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": rows}))
    return tmp_path


def test_the_loader_reports_the_rows_it_could_not_read(tmp_path: Path) -> None:
    root = _repo_with_catalogue(tmp_path, [_GOOD_ROW, {"url": None}, "not-a-row"])
    loaded = load_catalogue(root)
    assert [e.url for e in loaded.entries] == [_GOOD_ROW["url"]]
    assert loaded.dropped_rows == 2


def test_a_checkout_without_a_catalogue_loads_an_empty_one(tmp_path: Path) -> None:
    """The live catalogue build is optional, so its absence is not a failure."""
    assert load_catalogue(tmp_path) == LoadedCatalogue([], 0)


def test_the_resolver_artifact_publishes_the_dropped_count() -> None:
    output = resolver_build_output(_MANIFEST, [], catalogue_entries=1, catalogue_rows_dropped=3)
    assert output["catalogue_entries"] == 1
    assert output["catalogue_rows_dropped"]["count"] == 3
    assert output["catalogue_rows_dropped"]["reason"]


def test_the_coverage_report_publishes_the_dropped_count() -> None:
    report = build_report(_MANIFEST, LoadedCatalogue([], 4))
    assert report.catalogue_rows_dropped == 4
    assert report.to_dict()["catalogue_rows_dropped"]["count"] == 4
    assert report.to_dict()["catalogue_entries"] == 0


def test_the_coverage_report_still_accepts_a_plain_sequence_of_entries() -> None:
    """Callers holding only entries keep working; the count then reads zero."""
    report = build_report(_MANIFEST, [])
    assert report.catalogue_rows_dropped == 0


def test_the_era_artifact_publishes_the_dropped_count() -> None:
    result = bucket(_MANIFEST)
    output = era_build_output(_MANIFEST, result, LoadedCatalogue([], 2))
    assert output["catalogue_rows_dropped"]["count"] == 2
    assert output["catalogue_entries"] == 0
