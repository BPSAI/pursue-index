"""The tranche-ready manifest carries the poll's ONE fetched_at: it is
required (no second clock can persist) and the copy is validated."""

from __future__ import annotations

from datetime import UTC, datetime

import _tranche_ready_run
import pytest
from pydantic import ValidationError

from tests.unit.test_tranche_ready_job_guard import _run  # noqa: F401  (puts scripts/ on sys.path)

_RAW = ("﻿Release Date,Title,Type,Agency,Incident Date,PDF | Image Link\r\n"
        '10/23/26,"Case 1",PDF,FBI,1/18/57,https://www.war.gov/medialink/c1.pdf\r\n').encode()
_URL = "https://www.war.gov/x.csv"


def test_fetched_at_is_required() -> None:
    with pytest.raises(TypeError):
        _tranche_ready_run.normalized_manifest(_RAW, _URL, {"cards": []})  # type: ignore[call-arg]


def test_none_fetched_at_is_refused() -> None:
    with pytest.raises(ValueError, match="fetched_at"):
        _tranche_ready_run.normalized_manifest(_RAW, _URL, {"cards": []}, None, None)  # type: ignore[arg-type]


def test_invalid_fetched_at_fails_validation() -> None:
    with pytest.raises((ValidationError, ValueError)):
        _tranche_ready_run.normalized_manifest(
            _RAW, _URL, {"cards": []}, None, "not-a-date")  # type: ignore[arg-type]


def test_given_fetched_at_is_used() -> None:
    when = datetime(2031, 3, 4, tzinfo=UTC)
    m = _tranche_ready_run.normalized_manifest(_RAW, _URL, {"cards": []}, None, when)
    assert m.fetched_at == when


def test_round_trip_dumps_by_alias_and_keeps_every_field(monkeypatch) -> None:
    """The copy is rebuilt from an alias-keyed dump, so a field with an alias
    survives; every value is preserved and the copy is validated."""
    from pursue_index.scrape.types import Manifest

    calls: list[bool] = []
    real = Manifest.model_dump

    def spy(self, *a, **kw):
        calls.append(bool(kw.get("by_alias")))
        return real(self, *a, **kw)

    monkeypatch.setattr(Manifest, "model_dump", spy)
    when = datetime(2031, 3, 4, tzinfo=UTC)
    m = _tranche_ready_run.normalized_manifest(_RAW, _URL, {"cards": []}, None, when)
    assert calls and all(calls), "every manifest dump must use by_alias=True"
    assert m.fetched_at == when and str(m.source_url) == _URL
    assert len(m.cards) == 1 and m.csv_sha256
