"""Row-level effect of an acknowledged-unknown overlay entry.

While the entry's ``upstream_value`` is the row's upstream value, the field
stays empty (or keeps the paired prior's stored 4-digit value), the row is
reported under ``acknowledged`` instead of ``unresolved`` / ``open``, and
the card's ``raw`` carries a ``_date_acknowledged`` marker in place of the
``_date_unresolved`` one. A different upstream value re-opens the row as a
fresh UNRESOLVED flag (``acknowledged_value_changed``).
"""

from __future__ import annotations

from pursue_index.scrape.year_normalize import normalize_rows

_M = "_date_unresolved"
_A = "_date_acknowledged"
_REASON = "upstream year conflicts with the title"


def _row(card_id: str = "c1", **fields) -> dict:
    base = {"card_id": card_id, "title": "Case 2005", "asset_filename": None,
            "release_date": None, "incident_date": None, "display_date": None, "raw": {}}
    base.update(fields)
    return base


def _ack(upstream: str = "7/15/05", card_id: str = "c1") -> dict:
    return {(card_id, "incident_date"): {
        "value": None, "status": "acknowledged-unknown", "reason": _REASON,
        "curator": "<who>", "approved_at": "2026-11-21T00:00:00Z", "upstream_value": upstream}}


def _open_prior(raw: str = "7/15/05", **fields) -> dict:
    marker = {"field": "incident_date", "raw": raw, "reason": "no_century_evidence",
              "first_flagged_in": "t0", "first_flagged_at": "2026-11-01T00:00:00Z"}
    return _row(raw={"Incident Date": raw, _M: [marker]}, **fields)


def test_acknowledged_row_is_not_unresolved_or_open() -> None:
    out, report = normalize_rows([_row(incident_date="7/15/05", title="Case")], [_open_prior()],
                                 2026, overlay=_ack(), tranche="t1")
    assert report.unresolved == [] and report.open == []
    assert report.acknowledged == [{"card_id": "c1", "title": "Case", "field": "incident_date",
                                    "raw": "7/15/05", "reason": _REASON, "curator": "<who>",
                                    "approved_at": "2026-11-21T00:00:00Z"}]
    assert out[0]["incident_date"] is None
    assert out[0]["raw"] == {"Incident Date": "7/15/05", _A: [{
        "field": "incident_date", "raw": "7/15/05", "reason": _REASON, "curator": "<who>",
        "approved_at": "2026-11-21T00:00:00Z"}]}


def test_acknowledged_entry_never_writes_a_date() -> None:
    """Title-year evidence would restore 2005, yet the field stays empty."""
    out, report = normalize_rows([_row(incident_date="7/15/05")], [], 2026, overlay=_ack())
    assert out[0]["incident_date"] is None and len(report.acknowledged) == 1


def test_stored_prior_is_kept_unchanged() -> None:
    prior = [_row(incident_date="7/15/1905")]
    out, report = normalize_rows([_row(incident_date="7/15/05")], prior, 2026, overlay=_ack())
    assert out[0]["incident_date"] == "7/15/1905"
    assert report.unresolved == [] and len(report.acknowledged) == 1
    assert _M not in out[0]["raw"] and _A in out[0]["raw"]


def test_changed_upstream_value_reopens_the_row() -> None:
    prior = [_row(raw={"Incident Date": "7/15/05", _A: [{"field": "incident_date"}]})]
    out, report = normalize_rows([_row(incident_date="7/16/05")], prior, 2026,
                                 overlay=_ack(), tranche="t2")
    assert report.acknowledged == []
    assert [(u["raw"], u["reason"]) for u in report.unresolved] == [
        ("7/16/05", "acknowledged_value_changed")]
    assert out[0]["incident_date"] is None
    assert _A not in out[0]["raw"]
    assert out[0]["raw"][_M][0]["first_flagged_in"] == "t2"


def test_renormalizing_an_acknowledged_row_reproduces_it() -> None:
    once, _ = normalize_rows([_row(incident_date="7/15/05")], [], 2026, overlay=_ack())
    twice, report = normalize_rows(once, [], 2026, overlay=_ack())
    assert twice == once and len(report.acknowledged) == 1
