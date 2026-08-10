"""Committing a sidecar registers the card in the observations index.

The index is what consumers enumerate, so a sidecar that is on disk but
unlisted carries no text into the search payload or the vectors. A run
therefore registers each card it commits, and the proof runs through the real
loader rather than a re-read of the index.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.embed.image_observations import load_observation_text
from pursue_index.vision.eligibility import EligibleItem
from pursue_index.vision.index import register_cards
from pursue_index.vision.run import run_vision


def _item(card_id: str, page: int = 1) -> EligibleItem:
    return EligibleItem(
        card_id=card_id, page=page, kind="img_card",
        image_path=Path(f"/images/{card_id}"), title=f"T {card_id}",
    )


def _examine(_img: object) -> dict:
    return {
        "image_type": "photograph",
        "description": "A described image.",
        "visible_text": "",
        "observations": [{"claim": "A concrete claim", "kind": "observation"}],
    }


def _load(item: EligibleItem) -> object:
    return object()


def test_a_newly_examined_card_is_readable_through_the_real_loader(
    tmp_path: Path,
) -> None:
    run_vision([_item("imgA")], tmp_path, examine_fn=_examine, load_image_fn=_load)
    text = load_observation_text(tmp_path / "index.json")
    assert ("imgA", 1) in text
    assert "A concrete claim" in text[("imgA", 1)]


def test_registration_preserves_the_index_and_never_repeats_a_card(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {"schema_version": 1, "card_ids": ["existing"], "quarantine_policy": "x"}
        ),
        encoding="utf-8",
    )
    register_cards(index_path, ["imgA", "existing"])
    register_cards(index_path, ["imgA"])

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["card_ids"] == ["existing", "imgA"]
    assert index["card_count"] == 2
    assert index["quarantine_policy"] == "x"


def test_a_card_that_could_not_be_committed_is_not_registered(
    tmp_path: Path,
) -> None:
    (tmp_path / "imgA.json").write_text("{ truncated", encoding="utf-8")
    run_vision([_item("imgA")], tmp_path, examine_fn=_examine, load_image_fn=_load)
    index_path = tmp_path / "index.json"
    listed = (
        json.loads(index_path.read_text(encoding="utf-8")).get("card_ids", [])
        if index_path.exists()
        else []
    )
    assert "imgA" not in listed
