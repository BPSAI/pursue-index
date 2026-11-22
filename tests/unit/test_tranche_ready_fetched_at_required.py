"""The tranche-ready manifest carries the poll's ONE fetched_at: it is
required (no second clock can persist) and the copy is validated."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tests.unit.test_tranche_ready_job_guard import _run  # noqa: F401  (puts scripts/ on sys.path)

import _tranche_ready_run  # noqa: E402

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
