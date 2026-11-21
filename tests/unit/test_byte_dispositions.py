"""Byte-change dispositions: the strict loader and rule 4 of ``ingest_scope``."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from pursue_index.byte_dispositions import (
    ByteDispositionError,
    Disposition,
    covers,
    load_byte_change_dispositions,
)
from pursue_index.ingest_scope import (
    REASON_BYTES_CHANGED,
    scope_pdf_img_cards,
    scope_worklist,
)

CARD = "7d1b50162c29378a"
OLD = "a" * 64
NEW = "b" * 64
REF = "3" * 64
REPO_DATA = Path(__file__).resolve().parents[2] / "data"


def _row(**over) -> dict:
    row = {
        "card_id": CARD,
        "old_sha256": OLD,
        "new_sha256": NEW,
        "disposition": "resave-content-verified",
        "reviewed_at": "2026-11-21",
        "evidence": "upstream re-save: image recompression and added text layer",
        "evidence_ref": REF,
        "ocr_from": OLD,
    }
    row.update(over)
    return row


def _write(tmp_path: Path, *rows: dict) -> Path:
    path = tmp_path / "byte-change-dispositions.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _scope(dispositions=None, *, recorded=OLD, current=NEW):
    return scope_pdf_img_cards(
        {},
        "t",
        registry_sha_by_card={CARD: current},
        ocr_meta_sha_by_card={CARD: recorded},
        dispositions=dispositions,
    )


# --- loader -----------------------------------------------------------------


def test_loader_keys_rows_by_card_and_new_sha(tmp_path):
    got = load_byte_change_dispositions(_write(tmp_path, _row()))
    assert set(got) == {(CARD, NEW)}
    assert got[(CARD, NEW)].disposition == "resave-content-verified"
    assert got[(CARD, NEW)].old_sha256 == OLD


def test_loader_missing_file_is_empty(tmp_path):
    assert load_byte_change_dispositions(tmp_path / "absent.jsonl") == {}


@pytest.mark.parametrize(
    "bad",
    [
        {"disposition": "looks-fine"},
        {"old_sha256": "xyz"},
        {"new_sha256": "B" * 64},  # uppercase hex
        {"new_sha256": "b" * 63},
        {"evidence_ref": None},
        {"evidence_ref": "3" * 63},
        {"evidence_ref": "A" * 64},
        {"ocr_from": "c" * 64},  # must equal old_sha256 for resave-content-verified
        {"reviewed_at": "yesterday"},
        {"evidence": "see https://example.org/x"},
        {"evidence": "see issue #42"},
        {"evidence": "checked in pursue-example"},
        {"unexpected": 1},
    ],
)
def test_loader_rejects_bad_rows(tmp_path, bad):
    with pytest.raises(ByteDispositionError):
        load_byte_change_dispositions(_write(tmp_path, _row(**bad)))


def test_loader_rejects_missing_evidence_ref(tmp_path):
    row = _row()
    del row["evidence_ref"]
    with pytest.raises(ByteDispositionError):
        load_byte_change_dispositions(_write(tmp_path, row))


@pytest.mark.parametrize("kind", ["resave-content-verified", "content-changed"])
def test_loader_rejects_missing_ocr_from(tmp_path, kind):
    row = _row(disposition=kind)
    del row["ocr_from"]
    with pytest.raises(ByteDispositionError, match="ocr_from"):
        load_byte_change_dispositions(_write(tmp_path, row))


@pytest.mark.parametrize("kind", ["resave-content-verified", "content-changed"])
def test_loader_rejects_null_or_malformed_ocr_from(tmp_path, kind):
    for bad in (None, "xyz"):
        with pytest.raises(ByteDispositionError, match="ocr_from"):
            load_byte_change_dispositions(_write(tmp_path, _row(disposition=kind, ocr_from=bad)))


def test_covers_checks_ocr_from_itself():
    disp = Disposition(CARD, OLD, NEW, "resave-content-verified", "2026-11-21", "e", REF, OLD)
    assert covers({(CARD, NEW): disp}, CARD, OLD, NEW)
    for bad in (None, "c" * 64):
        broken = dataclasses.replace(disp, ocr_from=bad)
        assert not covers({(CARD, NEW): broken}, CARD, OLD, NEW)


def test_committed_rows_all_carry_ocr_from_equal_to_old_sha():
    got = load_byte_change_dispositions(REPO_DATA / "byte-change-dispositions.jsonl")
    assert got
    assert all(d.ocr_from == d.old_sha256 for d in got.values())


def test_loader_rejects_duplicate_pair(tmp_path):
    with pytest.raises(ByteDispositionError, match="duplicate"):
        load_byte_change_dispositions(_write(tmp_path, _row(), _row()))


def test_loader_rejects_bad_json(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ByteDispositionError):
        load_byte_change_dispositions(path)


def test_committed_file_loads_and_is_public_safe():
    path = REPO_DATA / "byte-change-dispositions.jsonl"
    assert path.is_file()
    load_byte_change_dispositions(path)  # the loader enforces the public-safety rules
    text = path.read_text(encoding="utf-8").lower()
    for needle in ("http", "www.", "pursue-", "bpsai", "github"):
        assert needle not in text


# --- rule 4 -----------------------------------------------------------------


def test_bytes_changed_without_disposition_is_scoped():
    assert [(s.card_id, s.reason) for s in _scope()] == [(CARD, REASON_BYTES_CHANGED)]


def test_matching_resave_row_suppresses(tmp_path):
    disp = load_byte_change_dispositions(_write(tmp_path, _row()))
    assert _scope(disp) == []


def test_content_changed_row_still_scopes(tmp_path):
    disp = load_byte_change_dispositions(
        _write(tmp_path, _row(disposition="content-changed"))
    )
    assert [s.card_id for s in _scope(disp)] == [CARD]


def test_old_sha_mismatch_does_not_suppress(tmp_path):
    disp = load_byte_change_dispositions(_write(tmp_path, _row()))
    # The OCR moved on since review: its sha is no longer the reviewed one.
    assert [s.card_id for s in _scope(disp, recorded="d" * 64)] == [CARD]


def test_row_for_a_different_new_sha_does_not_suppress(tmp_path):
    disp = load_byte_change_dispositions(_write(tmp_path, _row()))
    assert [s.card_id for s in _scope(disp, current="e" * 64)] == [CARD]


def test_scope_worklist_reads_dispositions_beside_the_registry(tmp_path):
    reg = tmp_path / "asset-bytes-registry.jsonl"
    reg.write_text(
        json.dumps({"card_id": CARD, "byte_sha256": NEW, "current_key": f"{CARD}.pdf"}) + "\n"
    )
    ocr = tmp_path / "ocr"
    (ocr / CARD).mkdir(parents=True)
    (ocr / CARD / "meta.json").write_text(json.dumps({"pdf_sha256": OLD}))
    kw = dict(aliases_path=tmp_path / "none.json", registry_path=reg, ocr_dir=ocr)
    assert [s.card_id for s in scope_worklist({}, "t", **kw)] == [CARD]
    _write(tmp_path, _row())
    assert scope_worklist({}, "t", **kw) == []


def test_committed_file_holds_the_three_verified_may_resaves():
    got = load_byte_change_dispositions(REPO_DATA / "byte-change-dispositions.jsonl")
    cards = {d.card_id for d in got.values() if d.disposition == "resave-content-verified"}
    assert cards >= {"7d1b50162c29378a", "3a5445e8aa7985d4", "b279eac8e49cf4fe"}


def test_covers_ties_ocr_from_to_the_actual_ocr_sha():
    from dataclasses import replace

    from pursue_index.byte_dispositions import Disposition, covers

    base = Disposition(
        "7d1b50162c29378a", "a" * 64, "b" * 64, "resave-content-verified",
        "2026-11-21", "re-save", "3" * 64, "a" * 64,
    )
    assert covers({(base.card_id, base.new_sha256): base}, base.card_id, "a" * 64, "b" * 64)
    forged = replace(base, ocr_from="c" * 64)  # ocr_from is not the OCR's actual sha
    assert not covers({(forged.card_id, forged.new_sha256): forged}, base.card_id, "a" * 64, "b" * 64)
