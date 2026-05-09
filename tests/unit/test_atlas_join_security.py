"""Security/integrity tests for ``embed.atlas_join``.

These cover the failure modes the security review (laverna) and
cross-cutting review (nayru) called out:

- SEC-001: sha256 sidecar must be verified before parsing
- SEC-002: miss-rate threshold must be clamped to a sane upper bound
- nayru P1: empty/missing ``source_url`` must raise, not silently miss
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pursue_index.embed.atlas_join import (
    AtlasJoinError,
    load_atlas_index,
)
from pursue_index.scrape.types import CardMetadata, Manifest


def _card(card_id: str, asset_url: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        title="x",
        asset_type="PDF",
        agency="FBI",
        asset_url=asset_url,
    )


def _manifest_with_one_card() -> Manifest:
    return Manifest(
        source_url="https://www.war.gov/x.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="deadbeef",
        cards=[
            _card(
                "ff30c985595153f3",
                "https://www.war.gov/medialink/ufo/release_1/059uap00011.pdf",
            ),
        ],
    )


def _write_corpus_with_sidecar(
    tmp_path: Path, body: str, sha_override: str | None = None
) -> Path:
    """Write a corpus + matching .sha256 sidecar (or a deliberately broken one)."""
    corpus = tmp_path / "alex-zhang42-corpus.jsonl"
    corpus.write_text(body)
    real_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    sha = sha_override if sha_override is not None else real_sha
    (tmp_path / "alex-zhang42-corpus.sha256").write_text(
        f"{sha}  {corpus.name}\n"
    )
    return corpus


# ----- SEC-002: threshold clamping --------------------------------------


def test_load_atlas_index_rejects_threshold_above_half() -> None:
    """``miss_rate_threshold`` >0.5 disables the join safety net entirely.

    Per laverna SEC-002: passing ``1.0`` would silently accept 100% misses
    and continue with zero augmentation. Fail-closed by raising on input.
    """
    body = (
        '{"source_url":"https://x/a.pdf","page_num":1,"image_tags":["a"]}\n'
    )
    corpus = _write_corpus_with_sidecar(Path("/tmp"), body)
    try:
        with pytest.raises(ValueError, match="miss_rate_threshold"):
            load_atlas_index(
                corpus, _manifest_with_one_card(), miss_rate_threshold=1.0
            )
        with pytest.raises(ValueError, match="miss_rate_threshold"):
            load_atlas_index(
                corpus, _manifest_with_one_card(), miss_rate_threshold=0.51
            )
    finally:
        corpus.unlink()
        (corpus.parent / "alex-zhang42-corpus.sha256").unlink()


def test_load_atlas_index_rejects_negative_threshold() -> None:
    """A negative threshold is meaningless; clamp at the lower bound."""
    body = '{"source_url":"https://x/a.pdf","page_num":1,"image_tags":["a"]}\n'
    corpus = _write_corpus_with_sidecar(Path("/tmp"), body)
    try:
        with pytest.raises(ValueError, match="miss_rate_threshold"):
            load_atlas_index(
                corpus, _manifest_with_one_card(), miss_rate_threshold=-0.1
            )
    finally:
        corpus.unlink()
        (corpus.parent / "alex-zhang42-corpus.sha256").unlink()


def test_load_atlas_index_accepts_threshold_at_upper_bound(
    tmp_path: Path,
) -> None:
    """``0.5`` is the documented operational ceiling and must succeed."""
    body = (
        '{"source_url":"https://www.war.gov/medialink/ufo/release_1/'
        '059uap00011.pdf","page_num":1,"image_tags":["a"]}\n'
    )
    corpus = _write_corpus_with_sidecar(tmp_path, body)
    index = load_atlas_index(
        corpus, _manifest_with_one_card(), miss_rate_threshold=0.5
    )
    assert ("ff30c985595153f3", 1) in index


# ----- nayru P1: empty/missing source_url --------------------------------


def test_load_atlas_index_raises_on_empty_source_url(tmp_path: Path) -> None:
    """An empty ``source_url`` is a malformed record; must raise, not miss.

    Previously this silently hashed the empty string, never matched a card,
    and was counted as a miss against the threshold. Per nayru's review,
    that's diagnostically wrong — surface it as an error instead.
    """
    body = '{"source_url":"","page_num":1,"image_tags":["a"]}\n'
    corpus = _write_corpus_with_sidecar(tmp_path, body)
    with pytest.raises(AtlasJoinError, match="source_url"):
        load_atlas_index(
            corpus, _manifest_with_one_card(), miss_rate_threshold=0.5
        )


def test_load_atlas_index_raises_on_missing_source_url(tmp_path: Path) -> None:
    """A record with no ``source_url`` key at all must raise."""
    body = '{"page_num":1,"image_tags":["a"]}\n'
    corpus = _write_corpus_with_sidecar(tmp_path, body)
    with pytest.raises(AtlasJoinError, match="source_url"):
        load_atlas_index(
            corpus, _manifest_with_one_card(), miss_rate_threshold=0.5
        )


# ----- SEC-001: sha256 verification --------------------------------------


def test_load_atlas_index_verifies_sha256_sidecar(tmp_path: Path) -> None:
    """A tampered corpus.jsonl must trip a hash mismatch error before parse.

    Per laverna SEC-001: this is the data trust boundary. A missing or
    mismatched sidecar means the source has changed; refuse to proceed.
    """
    body = (
        '{"source_url":"https://www.war.gov/medialink/ufo/release_1/'
        '059uap00011.pdf","page_num":1,"image_tags":["a"]}\n'
    )
    # Write the corpus, then a sidecar pointing at a *different* hash.
    corpus = _write_corpus_with_sidecar(
        tmp_path, body, sha_override="0" * 64
    )
    with pytest.raises(AtlasJoinError, match="sha256"):
        load_atlas_index(
            corpus, _manifest_with_one_card(), miss_rate_threshold=0.5
        )


def test_load_atlas_index_raises_when_sha256_sidecar_missing(
    tmp_path: Path,
) -> None:
    """No sidecar at all = refuse to load. Sidecars are non-negotiable."""
    body = (
        '{"source_url":"https://www.war.gov/medialink/ufo/release_1/'
        '059uap00011.pdf","page_num":1,"image_tags":["a"]}\n'
    )
    corpus = tmp_path / "alex-zhang42-corpus.jsonl"
    corpus.write_text(body)
    # No sidecar created.
    with pytest.raises(AtlasJoinError, match="sha256"):
        load_atlas_index(
            corpus, _manifest_with_one_card(), miss_rate_threshold=0.5
        )


def test_load_atlas_index_skip_hash_check_via_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opt-out env flag bypasses verification for explicit operator override.

    The flag exists for development workflows where the corpus is being
    regenerated and the sidecar hasn't been written yet. Default is OFF.
    """
    body = (
        '{"source_url":"https://www.war.gov/medialink/ufo/release_1/'
        '059uap00011.pdf","page_num":1,"image_tags":["a"]}\n'
    )
    corpus = tmp_path / "alex-zhang42-corpus.jsonl"
    corpus.write_text(body)
    monkeypatch.setenv("PURSUE_AUGMENT_SKIP_HASH_CHECK", "1")
    index = load_atlas_index(
        corpus, _manifest_with_one_card(), miss_rate_threshold=0.5
    )
    assert ("ff30c985595153f3", 1) in index


def test_load_atlas_index_passes_when_sha256_matches(tmp_path: Path) -> None:
    """The happy path: sidecar matches the file → load succeeds."""
    body = (
        '{"source_url":"https://www.war.gov/medialink/ufo/release_1/'
        '059uap00011.pdf","page_num":1,"image_tags":["a"]}\n'
    )
    corpus = _write_corpus_with_sidecar(tmp_path, body)
    index = load_atlas_index(
        corpus, _manifest_with_one_card(), miss_rate_threshold=0.5
    )
    assert ("ff30c985595153f3", 1) in index
