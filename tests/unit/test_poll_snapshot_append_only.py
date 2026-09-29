"""Diff records under ``data/manifests/diffs/`` are append-only (#157).

On 2026-09-24 a stale-edge re-observation of ``19e6dd7a69d5`` made the
snapshot lane recompute that sha's diff against a ``latest.json`` that was
already ``19e6`` and overwrite the tranche's real record (needs-review,
+72 cards) with ``benign``/+0. ``poll_snapshot.py --diff-out`` must never
rewrite an existing record: an identical recompute is a no-op, a
disagreeing one fails the job without writing.
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

from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv  # noqa: E402
from pursue_index.scrape.manifest import save_manifest  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_SOURCE_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = (
    "Redaction,Release Date,Title,Type,Agency,Incident Date,"
    "Incident Location,PDF | Image Link,Modal Image,Description Blurb"
)


def _row(title: str, n: int) -> str:
    return (
        f'False,5/8/26,"{title}",PDF,FBI,1/15/95,'
        f'"Roswell, NM",https://www.war.gov/medialink/case_{n:04d}.pdf,'
        'https://www.war.gov/img/x.jpg,"desc"'
    )


def _csv(rows: list[str]) -> bytes:
    return ("\ufeff" + _HEADER + "\r\n" + "\r\n".join(rows) + "\r\n").encode("utf-8")


_PRIOR = _csv([_row("Case 0001", 1)])
_NEW = _csv([_row("Case 0001", 1), _row("Case 0002", 2)])


def _run(tmp_path: Path, raw: bytes, prior: bytes, diff_out: Path) -> int:
    csv_path = tmp_path / "new.csv"
    csv_path.write_bytes(raw)
    latest = tmp_path / "latest.json"
    save_manifest(build_manifest(prior, parse_csv(prior), _SOURCE_URL), latest)
    return poll_snapshot.main([
        "--csv", str(csv_path),
        "--latest", str(latest),
        "--canonical-dir", str(tmp_path / "canonical"),
        "--public-dir", str(tmp_path / "public"),
        "--diff-out", str(diff_out),
    ])


def test_identical_recompute_leaves_existing_record_bytes_untouched(tmp_path: Path) -> None:
    diff_out = tmp_path / "diffs" / "x.json"
    assert _run(tmp_path, _NEW, _PRIOR, diff_out) == 0
    # Re-serialize with different whitespace: same record, different bytes.
    stored = json.dumps(json.loads(diff_out.read_text()), indent=4) + "\n"
    diff_out.write_text(stored)

    assert _run(tmp_path, _NEW, _PRIOR, diff_out) == 0
    assert diff_out.read_text() == stored


def test_disagreeing_recompute_fails_loudly_and_does_not_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    diff_out = tmp_path / "diffs" / "x.json"
    assert _run(tmp_path, _NEW, _PRIOR, diff_out) == 0
    before = diff_out.read_bytes()

    # Same new bytes, but diffed against a baseline that already equals
    # them: exactly the 2026-09-24 overwrite (needs-review -> benign/+0).
    (tmp_path / "second").mkdir()
    rc = _run(tmp_path / "second", _NEW, _NEW, diff_out)

    assert rc != 0
    assert diff_out.read_bytes() == before
    err = capsys.readouterr().err
    assert "append-only" in err
    assert str(diff_out) in err


def test_real_19e6_record_is_not_rewritten_by_a_stale_recompute(tmp_path: Path) -> None:
    """Replays the incident on the committed data: 19e6 bytes recomputed
    against a 19e6 latest.json must not replace the stored record."""
    sha = "19e6dd7a69d5c41c30bc3d9302462e922c6225cf18649298b329e68918e28a20"
    record = tmp_path / "diffs" / f"{sha}.json"
    record.parent.mkdir(parents=True)
    original = (_REPO / "data" / "manifests" / "diffs" / f"{sha}.json").read_bytes()
    record.write_bytes(original)
    raw = (_REPO / "data" / "raw" / "csv" / f"{sha}.csv").read_bytes()

    rc = _run(tmp_path, raw, raw, record)

    assert rc != 0
    assert record.read_bytes() == original


def test_existing_record_leaves_the_snapshot_mirror_untouched(tmp_path: Path) -> None:
    """With a record already present the recompute runs off to the side:
    a rejected (or no-op) run must not have touched snapshots/ or index.json,
    whatever the calling workflow does with the exit code."""
    diff_out = tmp_path / "diffs" / "x.json"
    assert _run(tmp_path, _NEW, _PRIOR, diff_out) == 0
    mirrors = [tmp_path / "canonical", tmp_path / "public"]
    before = {p: p.read_bytes() for d in mirrors for p in sorted(d.rglob("*")) if p.is_file()}

    # Disagreeing recompute against a baseline never rotated before, so a
    # generator run against the real mirror would add its snapshot.
    other = _csv([_row("Case 0003", 3)])
    assert _run(tmp_path, _NEW, other, diff_out) != 0
    # Agreeing recompute.
    assert _run(tmp_path, _NEW, _PRIOR, diff_out) == 0

    after = {p: p.read_bytes() for d in mirrors for p in sorted(d.rglob("*")) if p.is_file()}
    assert after == before
