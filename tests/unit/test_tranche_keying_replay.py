"""Site-level replay on the committed data for card ``c1c59236394f7b14``.

The card is backed by a PDF and a DVIDS video. Its newest registry row is the
video, so a per-card ``rows[-1]`` compared the PDF with the video's bytes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))

import _tranche_classify as classify  # noqa: E402

from pursue_index.tranche_manifest import display_rows_by_card_id  # noqa: E402

CID = "c1c59236394f7b14"


def _data():
    registry = [json.loads(line) for line in
                (_REPO / "data" / "asset-bytes-registry.jsonl").read_text().splitlines()
                if CID in line]
    cards = json.loads((_REPO / "data" / "manifests" / "latest.json").read_text())["cards"]
    return registry, [c for c in cards if c["card_id"] == CID]


def test_the_committed_card_has_a_pdf_row_and_a_newer_video_row() -> None:
    registry, cards = _data()
    assert registry[-1]["asset_url"].startswith("https://www.dvidshub.net/")
    assert any(r["asset_url"].endswith(".pdf") for r in registry)
    assert {c["asset_type"] for c in cards} == {"PDF", "VID"}


def test_the_pdf_compares_against_its_pdf_row_and_never_the_dvids_row() -> None:
    registry, cards = _data()
    pdf_row = next(r for r in registry if r["asset_url"].endswith(".pdf"))
    card = display_rows_by_card_id(cards)[CID]
    assert card["asset_type"] == "PDF"
    label, row = classify._classify_added_card(
        CID, card, pdf_row["byte_sha256"], {}, [], {CID: registry})
    assert label == "RESTORED_UNCHANGED"
    assert row["pinned_byte_sha256"] == pdf_row["byte_sha256"]
    assert row["pinned_byte_sha256"] != registry[-1]["byte_sha256"]
