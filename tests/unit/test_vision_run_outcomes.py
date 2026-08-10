"""What a vision run counts as coverage, and how odd results stay contained.

Three properties are pinned here:

* An examination that produced no content is its own outcome. The call
  returned, but there is nothing to render into a page, so the unit stays
  outstanding and the gate still reports the shortfall.
* An ``observations`` list is normalized to the entries the sidecar schema
  defines — entries that are not objects, or that carry no claim, are dropped
  — inside the per-item boundary, so one odd reply cannot end the pass.
* Persisting a card is bounded the same way examining one is: a card whose
  existing sidecar cannot be read or does not satisfy the schema is recorded
  and skipped, and every other card of the run still lands.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.vision.eligibility import EligibleItem
from pursue_index.vision.run import preflight_coverage, run_vision


def _item(card_id: str, page: int = 1, row_key: str = "") -> EligibleItem:
    return EligibleItem(
        card_id=card_id, page=page, kind="img_card",
        image_path=Path(f"/images/{card_id}"), title=f"T {card_id}",
        row_key=row_key,
    )


def _load(item: EligibleItem) -> object:
    return object()


def _full_result() -> dict:
    return {
        "image_type": "photograph",
        "description": "A described image.",
        "visible_text": "",
        "observations": [{"claim": "A concrete claim", "kind": "observation"}],
    }


def test_an_examination_with_no_content_leaves_the_unit_outstanding(
    tmp_path: Path,
) -> None:
    def examine(_img: object) -> dict:
        return {"image_type": "", "description": "", "visible_text": "",
                "observations": []}

    report = run_vision(
        [_item("imgA")], tmp_path, examine_fn=examine, load_image_fn=_load
    )
    assert not report.ok
    assert report.missing == [("imgA", "", 1)]
    assert report.empty == [("imgA", "", 1)]


def test_a_page_with_no_content_is_not_re_read_as_coverage(tmp_path: Path) -> None:
    def examine(_img: object) -> dict:
        return {"description": "   ", "visible_text": "", "observations": []}

    run_vision([_item("imgA")], tmp_path, examine_fn=examine, load_image_fn=_load)
    assert not preflight_coverage([_item("imgA")], tmp_path).ok


def test_observations_that_are_not_objects_are_dropped_and_the_page_still_lands(
    tmp_path: Path,
) -> None:
    def examine(_img: object) -> dict:
        return {
            "description": "A described image.",
            "visible_text": "",
            "observations": ["a bare string", {"kind": "observation"},
                             {"claim": "A concrete claim"}],
        }

    report = run_vision(
        [_item("imgA")], tmp_path, examine_fn=examine, load_image_fn=_load
    )
    assert report.ok
    page = json.loads((tmp_path / "imgA.json").read_text())["pages"][0]
    assert [o["claim"] for o in page["observations"]] == ["A concrete claim"]


def test_an_unreadable_existing_sidecar_is_recorded_and_the_run_continues(
    tmp_path: Path,
) -> None:
    (tmp_path / "imgA.json").write_text("{ truncated", encoding="utf-8")

    report = run_vision(
        [_item("imgA"), _item("imgB")], tmp_path,
        examine_fn=lambda _img: _full_result(), load_image_fn=_load,
    )
    assert report.missing == [("imgA", "", 1)]
    assert [key for key, _reason in report.failures] == [("imgA", "", 1)]
    assert (tmp_path / "imgB.json").exists()
