"""Image loading/rendering for the vision stage.

IMG cards load the downloaded asset directly; image-only PDF pages rasterize a
single page at 150 DPI (matching the frozen July artifact's ``pdftoppm -r 150``
provenance note). The PDF branch monkeypatches ``convert_from_path`` so no real
PDF/poppler is needed in the suite.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from pursue_index.vision import render
from pursue_index.vision.eligibility import EligibleItem


def test_load_img_card_reads_asset(tmp_path: Path) -> None:
    asset = tmp_path / "imgA.jpg"
    Image.new("RGB", (10, 10), "white").save(asset)
    item = EligibleItem(
        card_id="imgA", page=1, kind="img_card", image_path=asset, title="t"
    )
    img = render.load_image_for(item)
    assert img.size == (10, 10)


def test_load_image_only_page_rasterizes_single_page(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_convert(path, dpi, first_page, last_page):  # noqa: ANN001
        captured.update(
            path=path, dpi=dpi, first_page=first_page, last_page=last_page
        )
        return [Image.new("RGB", (20, 20), "black")]

    monkeypatch.setattr(render, "convert_from_path", fake_convert)
    item = EligibleItem(
        card_id="cardP", page=7, kind="image_only_page",
        image_path=tmp_path / "cardP.pdf", title="t",
    )
    img = render.load_image_for(item)
    assert img.size == (20, 20)
    assert captured["first_page"] == 7 and captured["last_page"] == 7
    assert captured["dpi"] == 150
