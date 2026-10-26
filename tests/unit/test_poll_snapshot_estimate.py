"""``scripts/poll_snapshot.py --summary-out`` prices the tranche per page (R7C.5).

The snapshot job fetches each new PDF (stubbed here through
``csv_fetcher.http_get``), counts its pages and writes the per-page band into
the tranche-ready block, with the judge figure labeled by what the committed
clean-qc bundle supports. A failed fetch names the card and marks the figure
partial.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import poll_snapshot  # noqa: E402

from pursue_index.scrape import csv_fetcher  # noqa: E402
from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv  # noqa: E402
from pursue_index.scrape.manifest import save_manifest  # noqa: E402
from tests.support.pdf_page_fakes import FakeHttpGet, pdf_bytes  # noqa: E402

_SOURCE_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = (
    "Redaction,Release Date,Title,Type,Agency,Incident Date,"
    "Incident Location,PDF | Image Link,Modal Image,Description Blurb"
)
_URL1 = "https://www.war.gov/medialink/case_0001.pdf"
_URL2 = "https://www.war.gov/medialink/case_0002.pdf"


def _csv(*urls: str) -> bytes:
    rows = [
        f'False,5/8/26,"Case {i}",PDF,FBI,1/15/95,"Roswell, NM",{u},'
        f'https://www.war.gov/img/x.jpg,"desc"'
        for i, u in enumerate(urls)
    ]
    return ("﻿" + _HEADER + "\r\n" + "\r\n".join(rows) + "\r\n").encode("utf-8")


def _summary(tmp_path: Path, bundle_stats: dict | None = None) -> str:
    new = _csv(_URL1, _URL2)
    (tmp_path / "new.csv").write_bytes(new)
    seed = _csv(_URL1)
    save_manifest(build_manifest(seed, parse_csv(seed), _SOURCE_URL), tmp_path / "latest.json")
    bundle = tmp_path / "clean-qc-bundle.json"
    bundle.write_text(json.dumps({"cards": [], "stats": bundle_stats or {}}))
    summary = tmp_path / "summary.md"
    rc = poll_snapshot.main([
        "--csv", str(tmp_path / "new.csv"), "--latest", str(tmp_path / "latest.json"),
        "--source-url", _SOURCE_URL,
        "--canonical-dir", str(tmp_path / "canonical"), "--public-dir", str(tmp_path / "public"),
        "--summary-out", str(summary), "--qc-bundle", str(bundle),
    ])
    assert rc == 0
    return summary.read_text()


def _new_card_id() -> str:
    raw = _csv(_URL1, _URL2)
    return next(c.card_id for c in parse_csv(raw) if str(c.asset_url) == _URL2)


def test_summary_carries_the_counted_page_band(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(csv_fetcher, "http_get", FakeHttpGet(bodies={_URL2: pdf_bytes(7)}))
    text = _summary(tmp_path)
    assert "over 7 pages" in text
    assert "recommended cap" in text
    assert "partial" not in text.lower()


def test_summary_labels_a_bundle_without_metered_fields_table_estimate(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(csv_fetcher, "http_get", FakeHttpGet(bodies={_URL2: pdf_bytes(7)}))
    text = _summary(tmp_path, {"est_total_cost_usd": 216.6})
    assert "judge rate: table estimate" in text
    assert "metered" not in text


def test_summary_labels_a_metered_bundle_metered(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(csv_fetcher, "http_get", FakeHttpGet(bodies={_URL2: pdf_bytes(7)}))
    text = _summary(tmp_path, {"metered_judge_spend_usd": 20.0, "metered_judge_calls": 1000})
    assert "judge rate: metered" in text
    assert "table estimate" not in text


def test_a_failed_fetch_names_the_card_and_marks_the_summary_partial(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(csv_fetcher, "http_get", FakeHttpGet(bodies={}, fail=frozenset({_URL2})))
    text = _summary(tmp_path)
    assert "Est. cost (partial)" in text
    assert f"`{_new_card_id()}`" in text.split("partial:**", 1)[1]
