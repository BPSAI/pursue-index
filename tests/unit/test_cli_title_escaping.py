"""Console sinks render corpus text as the characters it contains (PV1.6).

Card titles, agencies and identifiers are the government's own CSV text, and a
console is asked to *print* them, not to act on them. Two layers of a terminal
would otherwise read them as instructions:

* ``rich``'s markup language, where ``[link=…]`` becomes an OSC-8 hyperlink
  carrying a label and a target of the text's own choosing, and ``[bold red]``
  restyles the line. ``escape()`` and ``markup=False`` settle that layer.
* The control bytes underneath it. ``ESC`` and its C0 neighbours are what a
  terminal reads as cursor moves, colour changes and screen clears; ``rich``
  passes them through unchanged because they are not its markup.
  :func:`~pursue_index.text_control.console_text` settles that layer.

Both layers apply, so every sink that interpolates corpus text goes through
both — and a value carrying neither prints exactly as written.
"""

from __future__ import annotations

import io

from rich.console import Console

from pursue_index.cli import clean_cli, clean_qc_cli, provenance_cli, scrape_output
from pursue_index.provenance_report import CardOutcome, CoverageReport

_MARKUP_TITLE = "[link=https://example.test]war.gov release[/link] [bold red]CLASSIFIED[/]"
_CONTROL_TITLE = "Mission Report\x1b[2JErased, 2023\x07"


def _captured(monkeypatch, module) -> Console:
    console = Console(file=io.StringIO(), width=200, force_terminal=False)
    monkeypatch.setattr(module, "console", console)
    return console


def _outcome(title: str) -> CardOutcome:
    return CardOutcome(
        card_id="c1",
        title=title,
        agency="DOW",
        era="undated",
        primary_tier=None,
        resolved_by="unresolved",
        needs_page_image_comparison=False,
    )


def _report(outcome: CardOutcome) -> CoverageReport:
    return CoverageReport(
        card_count=1,
        resolved_by_claim=0,
        resolved_by_era=0,
        unresolved=1,
        tier_counts={},
        page_image_flagged=0,
        unresolved_by_era={"undated": 1},
        outcomes=(outcome,),
    )


def _diff(title: str) -> dict[str, object]:
    return {"snapshot": None, "added": 0, "removed": 1, "removed_titles": [title]}


def test_unresolved_listing_prints_markup_as_text(monkeypatch) -> None:
    console = _captured(monkeypatch, provenance_cli)
    provenance_cli._print_unresolved(_report(_outcome(_MARKUP_TITLE)))
    output = console.file.getvalue()
    assert "[link=https://example.test]" in output
    assert "\x1b]8;;" not in output


def test_unresolved_listing_prints_control_bytes_as_nothing(monkeypatch) -> None:
    console = _captured(monkeypatch, provenance_cli)
    provenance_cli._print_unresolved(_report(_outcome(_CONTROL_TITLE)))
    output = console.file.getvalue()
    assert "\x1b" not in output
    assert "\x07" not in output
    assert "Mission Report[2JErased, 2023" in output


def test_removed_card_listing_prints_markup_as_text(monkeypatch) -> None:
    console = _captured(monkeypatch, scrape_output)
    scrape_output.print_scrape_diff(_diff(_MARKUP_TITLE))
    output = console.file.getvalue()
    assert "[bold red]CLASSIFIED[/]" in output
    assert "\x1b]8;;" not in output


def test_removed_card_listing_prints_control_bytes_as_nothing(monkeypatch) -> None:
    console = _captured(monkeypatch, scrape_output)
    scrape_output.print_scrape_diff(_diff(_CONTROL_TITLE))
    output = console.file.getvalue()
    assert "\x1b" not in output
    assert "\x07" not in output


def test_the_cleanup_worklist_prints_an_identifier_as_text(monkeypatch) -> None:
    console = _captured(monkeypatch, clean_cli)
    clean_cli._print_dry_run(["card\x1b[31m-1"], budget=1.0, model="m")
    output = console.file.getvalue()
    assert "\x1b[31m" not in output
    assert "card[31m-1" in output


def test_the_qc_worklist_prints_an_identifier_as_text(monkeypatch) -> None:
    console = _captured(monkeypatch, clean_qc_cli)
    clean_qc_cli._print_dry_run(["card\x1b[31m-1"], budget=1.0, model="m")
    output = console.file.getvalue()
    assert "\x1b[31m" not in output
    assert "card[31m-1" in output


def test_ordinary_titles_are_unchanged(monkeypatch) -> None:
    console = _captured(monkeypatch, provenance_cli)
    provenance_cli._print_unresolved(_report(_outcome("DOW-UAP-D027, Mission Report")))
    assert "DOW-UAP-D027, Mission Report" in console.file.getvalue()


def test_an_ordinary_removed_title_is_unchanged(monkeypatch) -> None:
    console = _captured(monkeypatch, scrape_output)
    scrape_output.print_scrape_diff(_diff("DOW-UAP-D027, Mission Report"))
    assert "DOW-UAP-D027, Mission Report" in console.file.getvalue()
