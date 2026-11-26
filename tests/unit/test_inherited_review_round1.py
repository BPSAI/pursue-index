"""The console prints every row route, and an inheritance tie ordered by row index."""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Any

from rich.console import Console

from pursue_index.cli import provenance_cli
from pursue_index.file_basis import _strongest
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import build_report
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim


def _row(card_id: str, title: str, **fields: Any) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "agency": "DOW", "release_date": "5/8/2026", **fields}


def _claim(card_id: str, row_key: str) -> ResolvedClaim:
    return ResolvedClaim(
        card_id=card_id,
        row_key=row_key,
        tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
        source=ResolutionSource.NTRS_METADATA,
        identifier_kind="ntrs_citation_id",
        identifier_value="19700001234",
        artifact_url="https://ntrs.nasa.gov/citations/19700001234",
        established_date=date(1970, 1, 2),
        date_basis=DateBasis.PUBLISHER_DATE,
    )


def test_the_printed_row_routes_include_claim_inherited_and_sum_to_the_total(monkeypatch) -> None:
    console = Console(file=io.StringIO(), width=250, force_terminal=False)
    monkeypatch.setattr(provenance_cli, "console", console)
    manifest = {"cards": [_row("aaaa", "A1"), _row("aaaa", "A2"), _row("bbbb", "B1")]}
    report = build_report(manifest, extra_claims=[_claim("aaaa", "aaaa#0")])
    assert report.row_counts["claim_inherited"] == 1
    provenance_cli._print_coverage(report)
    text = console.file.getvalue()
    line = next(ln for ln in text.splitlines() if ln.startswith("Row partition"))
    total = int(re.search(r"\((?:unit: rows, )?(\d+) total\)", line).group(1))
    assert total == report.card_row_count
    assert re.search(r"claim_inherited\D*1", line)
    routes = re.sub(r"^.*?\):", "", line)
    assert sum(int(n) for n in re.findall(r"\b(\d+)\b", routes)) == total


def test_row_index_reads_the_numeric_suffix() -> None:
    from pursue_index.row_key import row_index

    assert row_index("aaaa#10") == 10
    assert row_index("no-card-id-3#0") == 0


class _Claim:
    tier = ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED


def test_a_tie_between_claimed_rows_goes_to_the_lower_numeric_index() -> None:
    entries = [("aaaa#10", _Claim()), ("aaaa#2", _Claim())]
    winner = _strongest(entries)  # type: ignore[arg-type]
    assert winner is not None and winner[0] == "aaaa#2"


def test_a_tie_between_rows_with_no_card_id_is_deterministic() -> None:
    entries = [("no-card-id-1#0", _Claim()), ("no-card-id-0#0", _Claim())]
    first = _strongest(entries)  # type: ignore[arg-type]
    second = _strongest(list(reversed(entries)))  # type: ignore[arg-type]
    assert first == second
