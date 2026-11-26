"""The corpus CSV URL is stored under ``corpus_manifest_url``, not ``source_manifest``."""

from __future__ import annotations

from typing import Any

import pytest

from pursue_index import era_bucketing, identifier_resolver, ntrs_source, tier0_sweep
from pursue_index.ntrs_claims_load import load_ntrs_claims

URL = "https://example.test/corpus.csv"
MANIFEST: dict[str, Any] = {"cards": [], "csv_sha256": "a" * 64, "source_url": URL}


def _era() -> dict[str, Any]:
    return era_bucketing.build_output(MANIFEST, era_bucketing.bucket(MANIFEST))


def _ident() -> dict[str, Any]:
    return identifier_resolver.build_output(MANIFEST, [], 0)


def _ntrs() -> dict[str, Any]:
    return ntrs_source.build_output(MANIFEST, [], {})


def _tier0() -> dict[str, Any]:
    return tier0_sweep.build_output(MANIFEST, tier0_sweep.sweep(MANIFEST))


@pytest.mark.parametrize("build", [_era, _ident, _ntrs, _tier0])
def test_writer_emits_corpus_manifest_url_only(build: Any) -> None:
    out = build()
    assert out["corpus_manifest_url"] == URL
    assert "source_manifest" not in out


def test_loader_reads_the_new_key() -> None:
    loaded = load_ntrs_claims({"csv_sha256": "a" * 64, "corpus_manifest_url": URL})
    assert getattr(loaded, "corpus_manifest_url", None) == URL


def test_loader_reads_an_old_key_file() -> None:
    loaded = load_ntrs_claims({"csv_sha256": "a" * 64, "source_manifest": URL})
    assert getattr(loaded, "corpus_manifest_url", None) == URL
