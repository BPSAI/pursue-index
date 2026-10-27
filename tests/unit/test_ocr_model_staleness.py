"""Tests for the OCR model-staleness check (R7C.16 / issue #171).

A card's ``llm`` rows should all have been produced by the single
currently operated model. A card whose ``llm`` rows disagree with each
other, or agree on a model other than the operated one, needs re-OCR
before a release ships. ``dots`` rows are the content-filter backstop,
not a staleness signal, so they never drive the flag.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pursue_index.ocr.model_staleness import (
    MODEL_UNKNOWN,
    build_staleness_report,
    check_card_model_staleness,
)
from pursue_index.scrape.types import CardMetadata, Manifest

_PAGES = iter(range(1, 10_000))


def _row(engine: str, **kw: object) -> dict[str, object]:
    """One OCR row; each call is a new page unless ``page=`` is given."""
    return {"page": next(_PAGES), "text": "x", "confidence": 90.0, "engine": engine, **kw}


def test_uniform_operated_model_is_not_flagged() -> None:
    rows = [_row("llm", model="claude-sonnet-4-6"), _row("llm", model="claude-sonnet-4-6")]
    status = check_card_model_staleness("card1", rows, operated_model="claude-sonnet-4-6")
    assert status.flagged is False
    assert status.distinct_llm_models == ("claude-sonnet-4-6",)


def test_mixed_models_is_flagged() -> None:
    rows = [_row("llm", model="claude-sonnet-4-6"), _row("llm", model="claude-opus-4")]
    status = check_card_model_staleness("card2", rows, operated_model="claude-sonnet-4-6")
    assert status.flagged is True
    assert status.mixed_models is True


def test_off_operated_model_is_flagged_even_when_uniform() -> None:
    rows = [_row("llm", model="claude-opus-4"), _row("llm", model="claude-opus-4")]
    status = check_card_model_staleness("card3", rows, operated_model="claude-sonnet-4-6")
    assert status.flagged is True
    assert status.off_operated_model is True
    assert status.mixed_models is False


def test_missing_fields_report_as_unknown_not_an_error() -> None:
    rows = [_row("llm")]  # an older sidecar, written before R7C.16
    status = check_card_model_staleness("card4", rows, operated_model="claude-sonnet-4-6")
    assert status.row_models == (MODEL_UNKNOWN,)
    assert status.flagged is False


def test_dots_fallback_rows_dont_trip_mixed_models() -> None:
    rows = [
        _row("llm", model="claude-sonnet-4-6"),
        _row("dots", engine_version="dots-mocr-v3"),
    ]
    status = check_card_model_staleness("card5", rows, operated_model="claude-sonnet-4-6")
    assert status.flagged is False
    assert status.row_models == ("claude-sonnet-4-6", "dots-mocr-v3")


def _manifest(cards: list[CardMetadata]) -> Manifest:
    return Manifest(
        source_url="https://example.com/x.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )


def _card(card_id: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        title="t",
        asset_type="PDF",
        agency="FBI",
        asset_url=f"https://www.war.gov/medialink/ufo/{card_id}.pdf",
        asset_filename=f"{card_id}.pdf",
    )


def test_build_staleness_report_flags_mixed_card_passes_uniform(tmp_path: Path) -> None:
    mixed, uniform = _card("mixedcard0001"), _card("uniformcard01")
    manifest = _manifest([mixed, uniform])

    def ocr_dir_for(card: CardMetadata) -> Path:
        d = tmp_path / card.card_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    (ocr_dir_for(mixed) / "pages.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                _row("llm", page=1, model="claude-sonnet-4-6"),
                _row("llm", page=2, model="claude-opus-4"),
            ]
        )
        + "\n"
    )
    (ocr_dir_for(uniform) / "pages.jsonl").write_text(
        json.dumps(_row("llm", page=1, model="claude-sonnet-4-6")) + "\n"
    )

    statuses = build_staleness_report(manifest, ocr_dir_for, operated_model="claude-sonnet-4-6")
    flagged_ids = {s.card_id for s in statuses if s.flagged}
    assert flagged_ids == {"mixedcard0001"}


def test_build_staleness_report_skips_cards_with_no_ocr_output(tmp_path: Path) -> None:
    card = _card("nocard00000001")
    manifest = _manifest([card])

    def ocr_dir_for(c: CardMetadata) -> Path:
        return tmp_path / c.card_id  # never created, no pages.jsonl

    statuses = build_staleness_report(manifest, ocr_dir_for, operated_model="claude-sonnet-4-6")
    assert statuses == []


def test_a_page_re_ocrd_with_the_operated_model_is_uniform_not_stale() -> None:
    rows = [
        _row("llm", page=1, model="claude-opus-4"),
        _row("llm", page=1, model="claude-sonnet-4-6"),  # the later, current row
    ]
    status = check_card_model_staleness("card9", rows, operated_model="claude-sonnet-4-6")
    assert status.flagged is False
    assert status.distinct_llm_models == ("claude-sonnet-4-6",)


def test_the_latest_row_wins_by_generated_at_then_file_order() -> None:
    rows = [
        _row("llm", page=1, model="claude-sonnet-4-6", generated_at="2026-10-02T00:00:00Z"),
        _row("llm", page=1, model="claude-opus-4", generated_at="2026-10-01T00:00:00Z"),
    ]
    status = check_card_model_staleness("card10", rows, operated_model="claude-sonnet-4-6")
    assert status.flagged is False  # the earlier-by-timestamp row is superseded


def test_a_genuinely_mixed_current_set_is_still_stale() -> None:
    rows = [
        _row("llm", page=1, model="claude-opus-4"),
        _row("llm", page=1, model="claude-sonnet-4-6"),
        _row("llm", page=2, model="claude-opus-4"),  # page 2 never re-OCR'd
    ]
    status = check_card_model_staleness("card11", rows, operated_model="claude-sonnet-4-6")
    assert status.flagged is True and status.mixed_models is True


def test_the_report_applies_the_same_selection_to_a_real_pages_jsonl(tmp_path) -> None:
    from pursue_index.ocr import model_staleness
    path = tmp_path / "pages.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [
        _row("llm", page=1, model="claude-opus-4"),
        _row("llm", page=1, model="claude-sonnet-4-6"),
    ]) + "\n")
    rows = model_staleness._load_rows(path)
    assert check_card_model_staleness("c", rows, "claude-sonnet-4-6").flagged is False
