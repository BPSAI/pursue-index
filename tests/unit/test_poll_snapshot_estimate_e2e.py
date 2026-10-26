"""End to end: ``python scripts/poll_snapshot.py`` writes the per-page estimate.

Runs the script as the snapshot job does -- a separate interpreter, real
argv -- on a fixture CSV. The PDF fetch is stubbed without touching the
script: a ``sitecustomize`` on ``PYTHONPATH`` swaps ``csv_fetcher.http_get``
for the shared fake before the script starts, serving fixture PDFs of known
page counts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv
from pursue_index.scrape.manifest import save_manifest

_REPO = Path(__file__).resolve().parents[2]
_SOURCE_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = (
    "Redaction,Release Date,Title,Type,Agency,Incident Date,"
    "Incident Location,PDF | Image Link,Modal Image,Description Blurb"
)
_PDFS = {f"https://www.war.gov/medialink/case_{n:04d}.pdf": n for n in (1, 10, 100)}
_OLD = "https://www.war.gov/medialink/case_0000.pdf"

_SITECUSTOMIZE = """
import json, os, sys
from pathlib import Path
sys.path[:0] = [os.environ["E2E_REPO"], os.path.join(os.environ["E2E_REPO"], "src")]
from tests.support.pdf_page_fakes import FakeHttpGet, pdf_bytes
from pursue_index.scrape import csv_fetcher
spec = json.loads(Path(os.environ["E2E_PDF_SPEC"]).read_text())
csv_fetcher.http_get = FakeHttpGet(bodies={u: pdf_bytes(n) for u, n in spec.items()})
"""


def _csv(urls: list[str]) -> bytes:
    rows = [
        f'False,5/8/26,"Case {i}",PDF,FBI,1/15/95,"Roswell, NM",{u},'
        f'https://www.war.gov/img/x.jpg,"desc"'
        for i, u in enumerate(urls)
    ]
    return ("﻿" + _HEADER + "\r\n" + "\r\n".join(rows) + "\r\n").encode("utf-8")


def _env(tmp_path: Path) -> dict[str, str]:
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(_SITECUSTOMIZE)
    spec = tmp_path / "pdf-spec.json"
    spec.write_text(json.dumps(_PDFS))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(PYTHONPATH=str(site), E2E_REPO=str(_REPO), E2E_PDF_SPEC=str(spec),
               PURSUE_REPO_ROOT=str(_REPO))
    return env


def test_script_writes_the_per_page_estimate_into_the_tranche_summary(tmp_path: Path) -> None:
    seed = _csv([_OLD])
    save_manifest(build_manifest(seed, parse_csv(seed), _SOURCE_URL), tmp_path / "latest.json")
    (tmp_path / "new.csv").write_bytes(_csv([_OLD, *_PDFS]))
    summary = tmp_path / "verdict-summary.md"
    proc = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "poll_snapshot.py"),
         "--csv", str(tmp_path / "new.csv"), "--latest", str(tmp_path / "latest.json"),
         "--source-url", _SOURCE_URL,
         "--canonical-dir", str(tmp_path / "canonical"),
         "--public-dir", str(tmp_path / "public"),
         "--diff-out", str(tmp_path / "diff.json"),
         "--summary-out", str(summary),
         "--qc-bundle", str(tmp_path / "absent-bundle.json")],
        env=_env(tmp_path), capture_output=True, text=True, timeout=120, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    text = summary.read_text()
    assert "Tranche verdict" in text
    assert "over 111 pages" in text
    assert "recommended cap" in text
    assert "judge rate: table estimate" in text
    assert "partial" not in text.lower()
