"""``poll_snapshot.py --tranche-ready-dir``: the guard and append-only (R7C.31).

* An invalid record (here: one missing a required field) is never written
  or committed: the script exits non-zero and ``--error-out`` -- the body
  the workflow files as the poll failure issue -- names the failing field.
* A second run for the same sha whose recomputed record disagrees (here:
  the same CSV, but a PDF now counts different pages) exits non-zero and
  writes nothing; an identical second run is a no-op success.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pursue_index.scrape import csv_fetcher
from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv
from pursue_index.scrape.manifest import save_manifest
from tests.support.pdf_page_fakes import FakeHttpGet, pdf_bytes

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _tranche_ready_run  # noqa: E402
import poll_snapshot  # noqa: E402

_SOURCE_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = ("Redaction,Release Date,Title,Type,Agency,Incident Date,"
           "Incident Location,PDF | Image Link,Modal Image,Description Blurb")
_URL = "https://www.war.gov/medialink/case_{:04d}.pdf"


def _csv(ns: list[int]) -> bytes:
    rows = [f'False,5/8/26,"DOW-UAP-D{n:03d}, Case",PDF,FBI,1/15/95,"Roswell, NM",'
            f'{_URL.format(n)},https://www.war.gov/img/x.jpg,"desc"' for n in ns]
    return ("﻿" + _HEADER + "\r\n" + "\r\n".join(rows) + "\r\n").encode("utf-8")


def _run(tmp: Path, out: Path, pages: int, monkeypatch: pytest.MonkeyPatch) -> int:
    tmp.mkdir(parents=True, exist_ok=True)
    prior, new = _csv([1]), _csv([1, 2])
    save_manifest(build_manifest(prior, parse_csv(prior), _SOURCE_URL), tmp / "latest.json")
    (tmp / "new.csv").write_bytes(new)
    monkeypatch.setattr(csv_fetcher, "http_get", FakeHttpGet(bodies={_URL.format(2): pdf_bytes(pages)}))
    return poll_snapshot.main([
        "--csv", str(tmp / "new.csv"), "--latest", str(tmp / "latest.json"),
        "--source-url", _SOURCE_URL,
        "--canonical-dir", str(tmp / "canonical"), "--public-dir", str(tmp / "public"),
        "--qc-bundle", str(tmp / "absent.json"),
        "--tranche-ready-dir", str(out / "tranche-ready"),
        "--tranche-diff-dir", str(out / "tranche-diffs"),
        "--registry", str(tmp / "absent-registry.jsonl"),
        "--poll-state", str(tmp / "absent-state.json"), "--csv-archive", str(tmp / "csv"),
        "--error-out", str(tmp / "error.md"),
    ])


def _outputs(out: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def test_a_record_missing_a_required_field_is_not_written_and_the_issue_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    real_build = _tranche_ready_run.build

    def drop_fetch(*args, **kwargs):
        diff, record = real_build(*args, **kwargs)
        del record["fetch"]
        return diff, record

    monkeypatch.setattr(_tranche_ready_run, "build", drop_fetch)

    out = tmp_path / "out"
    assert _run(tmp_path / "run", out, 3, monkeypatch) != 0
    assert _outputs(out) == {}
    body = (tmp_path / "run" / "error.md").read_text()
    assert "'fetch'" in body and "required" in body
    assert "fetch" in capsys.readouterr().err


def test_a_valid_first_run_writes_the_receipt_and_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "out"
    assert _run(tmp_path / "run", out, 3, monkeypatch) == 0
    names = sorted(p.relative_to(out).as_posix() for p in _outputs(out))
    assert len(names) == 3
    assert names[0].startswith("tranche-diffs/tranche-diff-") and names[0].endswith(".json")
    assert names[2].startswith("tranche-ready/")


def test_a_disagreeing_second_run_exits_non_zero_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "out"
    assert _run(tmp_path / "first", out, 3, monkeypatch) == 0
    before = _outputs(out)
    assert _run(tmp_path / "second", out, 7, monkeypatch) == 3
    assert _outputs(out) == before
    body = (tmp_path / "second" / "error.md").read_text()
    assert "append-only" in body and "sha256=" in body
    assert len(body.encode()) <= 8 * 1024
    assert body.count("`") == 8  # two fences plus the quoted sha12
    assert list((tmp_path / "second").glob("error-*.diff.json"))  # full diff stays local


def test_an_identical_second_run_is_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "out"
    assert _run(tmp_path / "first", out, 3, monkeypatch) == 0
    before = _outputs(out)
    assert _run(tmp_path / "second", out, 3, monkeypatch) == 0
    assert _outputs(out) == before
