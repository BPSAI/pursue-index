"""Per-page llm→dots content-filter fallback (T#11).

Covers: llm.py surfacing Anthropic's output-content-filter 400 as a typed
ContentFilterError (and NOT swallowing other errors); the run_llm_dots_fallback
runner routing only the filter-blocked page to dots (per-page engine tags); and
the pipeline wiring (dispatch + concurrency).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image

from pursue_index.ocr import dots as ocr_dots
from pursue_index.ocr import llm as ocr_llm
from pursue_index.ocr import runners
from pursue_index.ocr.llm import ContentFilterError


# --- llm.py: typed content-filter error ------------------------------------
class _RaisingMessages:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def create(self, **_: object) -> object:
        raise self._exc


class _RaisingClient:
    def __init__(self, exc: Exception) -> None:
        self.messages = _RaisingMessages(exc)


def test_content_filter_400_raises_typed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "c")
    exc = Exception(
        "Error code: 400 - {'error': {'message': 'Output blocked by content filtering policy'}}"
    )
    monkeypatch.setattr(ocr_llm, "_get_anthropic_client", lambda: _RaisingClient(exc))
    with pytest.raises(ContentFilterError):
        ocr_llm.ocr_image(Image.new("RGB", (8, 8)))


def test_non_filter_error_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "c")
    monkeypatch.setattr(
        ocr_llm, "_get_anthropic_client", lambda: _RaisingClient(RuntimeError("rate limited"))
    )
    with pytest.raises(RuntimeError, match="rate limited"):
        ocr_llm.ocr_image(Image.new("RGB", (8, 8)))


class _StatusError(Exception):
    def __init__(self, msg: str, status: int) -> None:
        super().__init__(msg)
        self.status_code = status


def test_non_400_echoing_filter_text_is_not_misclassified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-400 error whose body merely echoes 'output blocked' must NOT be
    routed to dots — it propagates as itself (the 400-status gate)."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "c")
    exc = _StatusError("500 server error: output blocked (echoed input)", 500)
    monkeypatch.setattr(ocr_llm, "_get_anthropic_client", lambda: _RaisingClient(exc))
    with pytest.raises(_StatusError):
        ocr_llm.ocr_image(Image.new("RGB", (8, 8)))


# --- runner: per-page fallback ---------------------------------------------
def _three_pages(_p: Path, _dpi: int) -> Iterator[Image.Image]:
    for _ in range(3):
        yield Image.new("RGB", (8, 8))


def test_fallback_routes_only_filter_page_to_dots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {"llm": 0, "dots": 0}

    def fake_llm(_img: Image.Image) -> tuple[str, float]:
        calls["llm"] += 1
        if calls["llm"] == 2:  # page 2 trips the filter
            raise ContentFilterError("Output blocked by content filtering policy")
        return ("sonnet text", 95.0)

    def fake_dots(_img: Image.Image) -> tuple[str, float]:
        calls["dots"] += 1
        return ("dots text", 70.0)

    monkeypatch.setattr(ocr_llm, "ocr_image", fake_llm)
    monkeypatch.setattr(ocr_dots, "ocr_image", fake_dots)

    out = tmp_path / "pages.jsonl"
    n, err = runners.run_llm_dots_fallback(tmp_path / "x.pdf", out, 300, _three_pages)

    assert err is None
    assert n == 3
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["engine"] for r in rows] == ["llm", "dots", "llm"]
    assert rows[1]["text"] == "dots text"  # the blocked page fell back
    assert calls["dots"] == 1  # dots invoked only for the one blocked page


def test_non_filter_error_still_fails_the_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _boom(_img: Image.Image) -> tuple[str, float]:
        raise RuntimeError("boom")

    monkeypatch.setattr(ocr_llm, "ocr_image", _boom)
    _n, err = runners.run_llm_dots_fallback(tmp_path / "x.pdf", tmp_path / "p.jsonl", 300, _three_pages)
    assert err is not None
    assert "boom" in err


# --- pipeline wiring -------------------------------------------------------
def test_pipeline_routes_llm_dots(monkeypatch: pytest.MonkeyPatch) -> None:
    from pursue_index.ocr import pipeline

    hit = {}
    monkeypatch.setattr(
        pipeline.ocr_runners,
        "run_llm_dots_fallback",
        lambda *a: (hit.setdefault("called", True), (0, None))[1],
    )
    pipeline._run_engine(Path("x.pdf"), Path("p.jsonl"), 300, "llm-dots")
    assert hit.get("called")


def test_llm_dots_concurrency_matches_llm() -> None:
    from pursue_index.ocr import pipeline

    assert pipeline._concurrency_for("llm-dots") == pipeline._concurrency_for("llm")
