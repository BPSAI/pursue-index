"""Tests for the ``scripts/poll_snapshot.py`` CLI shell.

The shell wraps ``generate_snapshot_diff`` for the credential-free GH
Actions snapshot job, adding a diff+verdict JSON artifact: on a detected
change the script must persist (verdict + added/removed/field-change counts +
new column names) keyed by new_sha, so the snapshot job can commit it and the
gh-comment step can read the verdict back.

Loaded the same way ``test_poll_pursue`` loads its script (scripts/ on
sys.path), invoking ``main`` with a tmp ``--csv`` and ``--diff-out``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# scripts/ is not a package; add it to sys.path so the module imports.
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import poll_snapshot  # noqa: E402

from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv  # noqa: E402
from pursue_index.scrape.manifest import save_manifest  # noqa: E402

_SOURCE_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = (
    "Redaction,Release Date,Title,Type,Agency,Incident Date,"
    "Incident Location,PDF | Image Link,Modal Image,Description Blurb"
)


def _row(title: str, url: str) -> str:
    return (
        f'False,5/8/26,"{title}",PDF,FBI,1/15/95,'
        f'"Roswell, NM",{url},https://www.war.gov/img/x.jpg,"desc"'
    )


def _csv(rows: list[str]) -> bytes:
    body = "\r\n".join(rows)
    return ("﻿" + _HEADER + "\r\n" + body + "\r\n").encode("utf-8")


_URL1 = "https://www.war.gov/medialink/case_0001.pdf"
_URL2 = "https://www.war.gov/medialink/case_0002.pdf"


def _argv(tmp_path: Path, csv_path: Path, latest: Path, diff_out: Path | None) -> list[str]:
    argv = [
        "--csv", str(csv_path),
        "--latest", str(latest),
        "--canonical-dir", str(tmp_path / "canonical"),
        "--public-dir", str(tmp_path / "public"),
    ]
    if diff_out is not None:
        argv += ["--diff-out", str(diff_out)]
    return argv


def _run(tmp_path: Path, raw: bytes, latest_seed: bytes | None) -> Path:
    """Invoke the script against tmp paths; return the diff-out path."""
    csv_path = tmp_path / "new.csv"
    csv_path.write_bytes(raw)
    latest = tmp_path / "latest.json"
    if latest_seed is not None:
        # Seed a prior latest.json directly so the diff has a baseline,
        # matching test_poll_snapshot's seeding (the generator reads but
        # never writes latest.json).
        manifest = build_manifest(latest_seed, parse_csv(latest_seed), _SOURCE_URL)
        save_manifest(manifest, latest)
    diff_out = tmp_path / "diff.json"
    poll_snapshot.main(_argv(tmp_path, csv_path, latest, diff_out))
    return diff_out


def test_writes_verdict_artifact_needs_review(tmp_path: Path) -> None:
    """A real added card produces a needs-review artifact with counts +
    new_sha."""
    diff_out = _run(
        tmp_path,
        raw=_csv([_row("Case 0001", _URL1), _row("Case 0002", _URL2)]),
        latest_seed=_csv([_row("Case 0001", _URL1)]),
    )
    assert diff_out.exists()
    art = json.loads(diff_out.read_text())
    assert art["verdict"] == "needs-review"
    assert art["added"] == 1
    assert art["removed"] == 0
    assert art["new_sha"]


def test_writes_verdict_artifact_benign(tmp_path: Path) -> None:
    """No structural change (identical rows) -> benign verdict artifact."""
    same = _csv([_row("Case 0001", _URL1)])
    diff_out = _run(tmp_path, raw=same, latest_seed=same)
    art = json.loads(diff_out.read_text())
    assert art["verdict"] == "benign"
    assert art["added"] == 0
    assert art["removed"] == 0


def test_writes_summary_markdown(tmp_path: Path) -> None:
    """--summary-out writes the rendered markdown the gh-comment step posts."""
    csv_path = tmp_path / "new.csv"
    csv_path.write_bytes(_csv([_row("Case 0001", _URL1), _row("Case 0002", _URL2)]))
    latest = tmp_path / "latest.json"
    seed = _csv([_row("Case 0001", _URL1)])
    save_manifest(build_manifest(seed, parse_csv(seed), _SOURCE_URL), latest)
    summary = tmp_path / "summary.md"
    argv = [*_argv(tmp_path, csv_path, latest, None), "--summary-out", str(summary)]
    poll_snapshot.main(argv)
    text = summary.read_text()
    assert "Tranche verdict" in text
    assert "needs-review" in text
    assert "added: 1" in text


def test_diff_out_omitted_still_succeeds(tmp_path: Path) -> None:
    """--diff-out is optional; without it the script still runs (back-compat
    with the bare kv-summary invocation)."""
    csv_path = tmp_path / "c.csv"
    csv_path.write_bytes(_csv([_row("Case 0001", _URL1)]))
    rc = poll_snapshot.main(
        _argv(tmp_path, csv_path, tmp_path / "latest.json", None)
    )
    assert rc == 0
