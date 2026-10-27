"""Empty xref subsections still spend the parser's time budget."""

from __future__ import annotations

import pytest
from pypdf import PdfReader

from pursue_index import pdf_limits, pdf_update
from pursue_index.pdf_limits import LimitExceededError


def test_empty_subsections_hit_the_time_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"xref\n" + b"0 0\n" * 5000 + b"trailer\n<< /Size 1 >>\n"
    budget = pdf_limits.Budget()
    monkeypatch.setattr(budget, "check", lambda: (_ for _ in ()).throw(
        LimitExceededError("time-budget", "spent")))
    reader = PdfReader.__new__(PdfReader)
    with pytest.raises(LimitExceededError):
        pdf_update._read_table(data, 0, reader, budget)
