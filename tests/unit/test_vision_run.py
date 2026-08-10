"""Run orchestration + coverage gate for the vision stage.

``run_vision`` produces sidecars for eligible items using injected
``examine_fn``/``load_image_fn`` seams (no live API, no PDF rendering in
tests). ``preflight_coverage`` compares eligible-vs-produced without spending
anything. The coverage contract is ``produced ⊇ eligible(worklist)``; a
shortfall is the red path the CLI turns into a non-zero exit.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.vision.eligibility import EligibleItem
from pursue_index.vision.run import (
    preflight_coverage,
    produced_pages,
    run_vision,
)


def _item(
    card_id: str, page: int, kind: str = "img_card", row_key: str = ""
) -> EligibleItem:
    return EligibleItem(
        card_id=card_id, page=page, kind=kind,
        image_path=Path(f"/tmp/{card_id}"), title=f"T {card_id}",
        row_key=row_key,
    )


def _fake_examine(_img: object) -> dict:
    return {
        "image_type": "photograph",
        "description": "A fake description for tests.",
        "visible_text": "",
        "observations": [
            {"claim": "A fake claim", "kind": "observation", "confidence": "high"},
        ],
    }


def _fake_load(item: EligibleItem) -> object:
    return object()  # opaque stand-in; _fake_examine ignores it


def test_run_vision_writes_sidecars_and_reports_full_coverage(tmp_path: Path) -> None:
    items = [_item("imgA", 1), _item("imgB", 1)]
    report = run_vision(
        items, tmp_path, examine_fn=_fake_examine, load_image_fn=_fake_load
    )
    assert report.ok
    assert not report.missing
    assert (tmp_path / "imgA.json").exists()
    data = json.loads((tmp_path / "imgA.json").read_text())
    assert data["our_pass"]["model"] == "claude-opus-4-8"
    assert data["pages"][0]["description"] == "A fake description for tests."


def test_run_vision_merges_multiple_pages_into_one_card_sidecar(
    tmp_path: Path,
) -> None:
    items = [
        _item("cardP", 2, "image_only_page"),
        _item("cardP", 3, "image_only_page"),
    ]
    run_vision(items, tmp_path, examine_fn=_fake_examine, load_image_fn=_fake_load)
    data = json.loads((tmp_path / "cardP.json").read_text())
    assert {p["page"] for p in data["pages"]} == {2, 3}


def test_produced_pages_scans_existing_sidecars(tmp_path: Path) -> None:
    """A sidecar page without a row key covers the single-row form of its card."""
    (tmp_path / "cardX.json").write_text(
        json.dumps(
            {
                "card_id": "cardX",
                "schema_version": 1,
                "our_pass": {"model": "claude-opus-4-8"},
                "pages": [
                    {"page": 1, "observations": [{"claim": "A claim"}]},
                    {"page": 4, "observations": [{"claim": "Another claim"}]},
                ],
            }
        )
    )
    assert produced_pages(tmp_path) == {("cardX", "", 1), ("cardX", "", 4)}


def test_preflight_reports_shortfall_without_spending(tmp_path: Path) -> None:
    # One eligible item, no sidecar on disk -> shortfall, red path.
    items = [_item("imgA", 1)]
    report = preflight_coverage(items, tmp_path)
    assert not report.ok
    assert report.missing == [("imgA", "", 1)]
    # No sidecar was written (preflight never spends).
    assert list(tmp_path.glob("*.json")) == []


def test_preflight_passes_when_covered(tmp_path: Path) -> None:
    (tmp_path / "imgA.json").write_text(
        json.dumps(
            {
                "card_id": "imgA",
                "schema_version": 1,
                "our_pass": {"model": "claude-opus-4-8"},
                "pages": [{"page": 1, "observations": [{"claim": "A claim"}]}],
            }
        )
    )
    report = preflight_coverage([_item("imgA", 1)], tmp_path)
    assert report.ok
    assert not report.missing


def test_each_row_of_a_shared_card_id_is_examined(tmp_path: Path) -> None:
    """Two eligible rows under one card_id are two units of work.

    Coverage counts rows, so producing one row's observation leaves the other
    outstanding rather than satisfying it.
    """
    items = [_item("dupe", 1, row_key="a"), _item("dupe", 1, row_key="b")]
    calls: list[int] = []

    def counting_examine(img: object) -> dict:
        calls.append(1)
        return _fake_examine(img)

    report = run_vision(
        items, tmp_path, examine_fn=counting_examine, load_image_fn=_fake_load
    )
    assert sum(calls) == 2
    assert report.ok
    data = json.loads((tmp_path / "dupe.json").read_text())
    assert {p["row_key"] for p in data["pages"]} == {"a", "b"}


def test_shared_card_id_shortfall_is_reported(tmp_path: Path) -> None:
    """One produced row of a shared card_id leaves the other row short."""
    produced_row = [_item("dupe", 1, row_key="a")]
    run_vision(
        produced_row, tmp_path, examine_fn=_fake_examine, load_image_fn=_fake_load
    )
    both_rows = [*produced_row, _item("dupe", 1, row_key="b")]
    report = preflight_coverage(both_rows, tmp_path)
    assert not report.ok
    assert report.missing == [("dupe", "b", 1)]


def test_run_vision_is_idempotent_skips_already_produced(tmp_path: Path) -> None:
    calls: list[int] = []

    def counting_examine(_img: object) -> dict:
        calls.append(1)
        return _fake_examine(_img)

    items = [_item("imgA", 1)]
    run_vision(items, tmp_path, examine_fn=counting_examine, load_image_fn=_fake_load)
    run_vision(items, tmp_path, examine_fn=counting_examine, load_image_fn=_fake_load)
    assert sum(calls) == 1  # second run skipped the already-produced page
