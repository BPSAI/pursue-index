"""Full-tranche PDF/IMG worklist scoping (R7C.1 / #168).

``summarize_ingest_work`` only ever scoped the diff's ``new_content`` rows
(Class B). Three classes of real work fell out: quarantined-new cards (Class
C) that clear the gate as new cards after ``ingest approve`` with no explicit
per-card marker; approved renames, whose new ``card_id`` has no OCR sidecar
yet; and existing cards whose registry byte sha has drifted from what their
OCR sidecar recorded. ``scope_pdf_img_cards`` closes all three, tagging each
card_id with why it's in scope.

Fixtures below replay the real Release 7 tranche-diffs on disk
(``data/tranche-diffs/tranche-diff-{c3f8209ef5f5,096ef2c0058a}.json``) and
their real ``card-aliases.json`` rows, so the counts assert against real
production data rather than invented numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.ingest_scope import (
    REASON_BYTES_CHANGED,
    REASON_NEW,
    REASON_QUARANTINED_NEW,
    REASON_RENAMED,
    ScopedCard,
    load_aliases,
    load_ocr_meta_sha_map,
    load_registry_sha_map,
    scope_pdf_img_cards,
    scope_worklist,
)

_C3F8_SHA = "c3f8209ef5f53a124bf3f30c4a36106ffaa63ea9770ad2d33e2ba5c4fec347c7"
_096EF_SHA = "096ef2c0058abd412a568d630df31cb836241c1c08c4f67bdc8cdb7e5c8418b9"

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DIFF_DIR = _REPO_ROOT / "data" / "tranche-diffs"
_ALIASES_PATH = _REPO_ROOT / "data" / "card-aliases.json"


def _load_diff(sha: str) -> dict:
    return json.loads((_DIFF_DIR / f"tranche-diff-{sha[:12]}.json").read_text())


# --- replay fixture: tranche c3f8 ------------------------------------------
#
# Real diff: 4 quarantined rows. One (new_card_id cb8be77a22e07f9b) is
# aliased this tranche (operator_manual rename) but carries no asset (it's
# the retitled video, PR004 Oct-2023 -> Jan-2024 — same registry bytes, no
# new PDF/IMG to fetch). The other three (D002/D003/D004) are unaddressed
# quarantined PDFs that clear the gate as new cards. A synthetic
# bytes-changed PDF (an existing, already-OCR'd card whose registry sha has
# drifted) is added via the registry/OCR-meta maps, since real OCR sidecars
# live outside this repo.


def test_c3f8_replay_scopes_all_four_pdf_bearing_cards() -> None:
    diff = _load_diff(_C3F8_SHA)
    aliases = load_aliases(_ALIASES_PATH)

    scoped = scope_pdf_img_cards(
        diff,
        _C3F8_SHA,
        aliases=aliases,
        registry_sha_by_card={"1b33dafd36c74c06": "newsha000000"},
        ocr_meta_sha_by_card={"1b33dafd36c74c06": "oldsha111111"},
    )

    by_id = {c.card_id: c.reason for c in scoped}
    assert by_id == {
        "247e6e1bd6da7377": REASON_QUARANTINED_NEW,  # D002
        "31656bd3e7de783d": REASON_QUARANTINED_NEW,  # D003
        "b1d24cb7f46cfa20": REASON_QUARANTINED_NEW,  # D004
        "1b33dafd36c74c06": REASON_BYTES_CHANGED,
    }
    # The retitled video (cb8be77a22e07f9b, no asset) is not a PDF/IMG card.
    assert "cb8be77a22e07f9b" not in by_id
    assert len(scoped) == 4


# --- replay fixture: tranche 096ef ------------------------------------------
#
# Real diff: 28 new_content PDFs + 1 quarantined PDF (D042) resolved this
# tranche as an operator_manual rename with new bytes. Total scope: 29,
# the renamed card tagged ``renamed`` (not ``bytes-changed`` — it's a new
# card_id with no prior OCR sidecar to compare against).


def test_096ef_replay_scopes_29_cards_rename_tagged_renamed() -> None:
    diff = _load_diff(_096EF_SHA)
    aliases = load_aliases(_ALIASES_PATH)

    scoped = scope_pdf_img_cards(diff, _096EF_SHA, aliases=aliases)

    assert len(scoped) == 29
    by_id = {c.card_id: c.reason for c in scoped}
    assert by_id["ff3939f95d878062"] == REASON_RENAMED  # D042
    new_ids = [r["new_card_id"] for r in diff["new_content"]]
    assert all(by_id[cid] == REASON_NEW for cid in new_ids)
    assert len(new_ids) == 28


# --- metadata-only tranche ---------------------------------------------------


def test_metadata_only_diff_scopes_nothing() -> None:
    diff = {
        "tranche_sha256": "deadbeef" * 8,
        "new_content": [],
        "quarantined": [],
    }
    scoped = scope_pdf_img_cards(diff, diff["tranche_sha256"])
    assert scoped == []


# --- unit-level behavior on synthetic diffs ---------------------------------


def test_new_content_pdf_row_tagged_new() -> None:
    diff = {
        "new_content": [
            {"new_card_id": "a" * 16, "asset_filename": "x.pdf", "asset_url": "https://x/x.pdf"},
        ],
        "quarantined": [],
    }
    scoped = scope_pdf_img_cards(diff, "sha1")
    assert scoped == [ScopedCard("a" * 16, REASON_NEW)]


def test_new_content_video_row_excluded_by_asset_type() -> None:
    diff = {
        "new_content": [
            {
                "new_card_id": "v" * 16,
                "asset_filename": "x.mp4",
                "asset_url": "https://x/x.mp4",
                "asset_type": "VID",
            },
        ],
        "quarantined": [],
    }
    scoped = scope_pdf_img_cards(diff, "sha1")
    assert scoped == []


def test_new_content_video_row_excluded_by_extension_when_no_asset_type() -> None:
    """Real production diffs never carry asset_type on new_content rows
    (verified against every tranche-diff on disk) -- fall back to the
    filename extension."""
    diff = {
        "new_content": [
            {"new_card_id": "v" * 16, "asset_filename": "x.mp4", "asset_url": "https://x/x.mp4"},
        ],
        "quarantined": [],
    }
    scoped = scope_pdf_img_cards(diff, "sha1")
    assert scoped == []


def test_quarantined_row_with_no_asset_excluded() -> None:
    """A quarantined row approved as a rename to a card with no asset
    (e.g. a retitled video) must not appear in the PDF/IMG worklist."""
    diff = {
        "new_content": [],
        "quarantined": [
            {
                "new_card_id": "r" * 16,
                "new_asset_filename": None,
                "new_asset_url": None,
            }
        ],
    }
    aliases = [{"old_card_id": "o" * 16, "new_card_id": "r" * 16, "tranche_sha256": "sha1"}]
    scoped = scope_pdf_img_cards(diff, "sha1", aliases=aliases)
    assert scoped == []


def test_quarantined_resolved_by_an_older_tranches_alias_is_not_renamed_here() -> None:
    """An alias established under a *different* tranche must not mark this
    tranche's quarantined row as ``renamed`` -- it's still unaddressed here."""
    diff = {
        "new_content": [],
        "quarantined": [
            {"new_card_id": "q" * 16, "new_asset_filename": "q.pdf", "new_asset_url": "https://x/q.pdf"},
        ],
    }
    aliases = [{"old_card_id": "o" * 16, "new_card_id": "q" * 16, "tranche_sha256": "some-other-tranche"}]
    scoped = scope_pdf_img_cards(diff, "sha1", aliases=aliases)
    assert scoped == [ScopedCard("q" * 16, REASON_QUARANTINED_NEW)]


def test_bytes_changed_skipped_when_card_already_scoped_above() -> None:
    """A card already tagged new/quarantined-new/renamed never also gets a
    bytes-changed tag, even if it happens to appear in the registry map
    (e.g. operator re-ran the scope mid-ingest)."""
    diff = {
        "new_content": [
            {"new_card_id": "n" * 16, "asset_filename": "n.pdf", "asset_url": "https://x/n.pdf"},
        ],
        "quarantined": [],
    }
    scoped = scope_pdf_img_cards(
        diff,
        "sha1",
        registry_sha_by_card={"n" * 16: "sha-now"},
        ocr_meta_sha_by_card={"n" * 16: "sha-before"},
    )
    assert scoped == [ScopedCard("n" * 16, REASON_NEW)]


def test_bytes_changed_requires_a_prior_ocr_meta_entry() -> None:
    """A registry row with no corresponding OCR meta.json isn't
    'bytes-changed' -- it's simply never been OCR'd (covered elsewhere, not
    a drift)."""
    diff = {"new_content": [], "quarantined": []}
    scoped = scope_pdf_img_cards(
        diff, "sha1", registry_sha_by_card={"x" * 16: "sha-now"}, ocr_meta_sha_by_card={}
    )
    assert scoped == []


def test_bytes_unchanged_not_scoped() -> None:
    diff = {"new_content": [], "quarantined": []}
    scoped = scope_pdf_img_cards(
        diff,
        "sha1",
        registry_sha_by_card={"x" * 16: "same-sha"},
        ocr_meta_sha_by_card={"x" * 16: "same-sha"},
    )
    assert scoped == []


# --- loaders -----------------------------------------------------------------


def test_load_aliases_reads_the_aliases_list(tmp_path: Path) -> None:
    p = tmp_path / "card-aliases.json"
    p.write_text(json.dumps({"aliases": [{"old_card_id": "a", "new_card_id": "b", "tranche_sha256": "t"}]}))
    assert load_aliases(p) == [{"old_card_id": "a", "new_card_id": "b", "tranche_sha256": "t"}]


def test_load_aliases_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_aliases(tmp_path / "nope.json") == []


def test_load_registry_sha_map_last_row_wins(tmp_path: Path) -> None:
    p = tmp_path / "registry.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps({"card_id": "a", "byte_sha256": "first"}),
                json.dumps({"card_id": "a", "byte_sha256": "second"}),
                json.dumps({"card_id": "b", "byte_sha256": "only"}),
            ]
        )
    )
    assert load_registry_sha_map(p) == {"a": "second", "b": "only"}


def test_load_registry_sha_map_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_registry_sha_map(tmp_path / "nope.jsonl") == {}


def test_load_ocr_meta_sha_map_reads_pdf_sha256(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr"
    card_dir = ocr_dir / "cardid"
    card_dir.mkdir(parents=True)
    (card_dir / "meta.json").write_text(json.dumps({"pdf_sha256": "abc123", "card_id": "cardid"}))
    assert load_ocr_meta_sha_map(ocr_dir, ["cardid", "missing-card"]) == {"cardid": "abc123"}


def test_scope_worklist_wires_loaders_together(tmp_path: Path) -> None:
    aliases_path = tmp_path / "card-aliases.json"
    aliases_path.write_text(json.dumps({"aliases": []}))
    registry_path = tmp_path / "registry.jsonl"
    registry_path.write_text(json.dumps({"card_id": "existing", "byte_sha256": "new-sha"}) + "\n")
    ocr_dir = tmp_path / "ocr"
    (ocr_dir / "existing").mkdir(parents=True)
    (ocr_dir / "existing" / "meta.json").write_text(json.dumps({"pdf_sha256": "old-sha"}))

    diff = {
        "new_content": [
            {"new_card_id": "n" * 16, "asset_filename": "n.pdf", "asset_url": "https://x/n.pdf"},
        ],
        "quarantined": [],
    }
    scoped = scope_worklist(
        diff, "sha1", aliases_path=aliases_path, registry_path=registry_path, ocr_dir=ocr_dir
    )
    by_id = {c.card_id: c.reason for c in scoped}
    assert by_id == {"n" * 16: REASON_NEW, "existing": REASON_BYTES_CHANGED}
