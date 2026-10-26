"""End to end (R7C.12): ``python scripts/tranche_diff.py --bytes-dir`` on the
096ef replay, then ``pursue ingest approve`` on what it wrote.

The script runs as the operator runs it -- a separate interpreter, real
argv, unmodified script. Only the network is faked: a ``sitecustomize`` on
``PYTHONPATH`` installs a stand-in ``curl_cffi`` whose ``requests.get``
serves synthetic bytes, so nothing reaches war.gov. D042's new URL serves
the synthetic metadata-only re-save of a synthetic base PDF; every other
URL serves placeholder bytes. The bytes-dir holds both D042 files under
``<byte_sha256>.pdf``, and the receipt-time registry gains a row pinning
D042's old card to the base PDF's sha.

The diff is written to a temporary ``--out-dir`` (never the committed
``data/tranche-diffs/``) and must carry D042 under ``renames_metadata_only``;
``ingest approve`` must then alias it with ``method: "metadata-only-resave"``
and no ``--approve-rename`` flag.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli import ingest_cli
from pursue_index.cli.commands import app
from tests.support.tranche_096ef import (
    D042_NEW_ID,
    D042_OLD_ID,
    NEW_MANIFEST,
    OLD_MANIFEST,
    REPO_ROOT,
    d042_new_url,
    receipt,
    receipt_time_registry,
)
from tests.support.tranche_bytes_fakes import build_base_pdf, metadata_only_resave

_SITECUSTOMIZE = """
import json, os, sys, types
from pathlib import Path
bodies = {u: Path(p).read_bytes() for u, p in
          json.loads(Path(os.environ["E2E_BODIES"]).read_text()).items()}
class _Resp:
    def __init__(self, content): self.content = content
    def raise_for_status(self): pass
requests = types.ModuleType("curl_cffi.requests")
requests.get = lambda url, **kw: _Resp(bodies.get(url, url.encode()))
curl_cffi = types.ModuleType("curl_cffi")
curl_cffi.requests = requests
sys.modules.update({"curl_cffi": curl_cffi, "curl_cffi.requests": requests})
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def replay(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the script once; return its ``--out-dir``."""
    tmp = tmp_path_factory.mktemp("replay")
    base = build_base_pdf()
    old_bytes, new_bytes = base.data, metadata_only_resave(base)
    bytes_dir = tmp / "bytes"
    bytes_dir.mkdir()
    for data in (old_bytes, new_bytes):
        (bytes_dir / f"{_sha(data)}.pdf").write_bytes(data)
    (tmp / "site").mkdir()
    (tmp / "site" / "sitecustomize.py").write_text(_SITECUSTOMIZE)
    (tmp / "bodies.json").write_text(json.dumps(
        {d042_new_url(): str(bytes_dir / f"{_sha(new_bytes)}.pdf")}))
    registry = receipt_time_registry(tmp / "registry.jsonl", [{
        "card_id": D042_OLD_ID, "byte_sha256": _sha(old_bytes),
        "fetched_at": "2099-01-01T00:00:00+00:00",
    }])
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(PYTHONPATH=str(tmp / "site"), E2E_BODIES=str(tmp / "bodies.json"),
               PURSUE_REPO_ROOT=str(REPO_ROOT))
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "tranche_diff.py"),
         "--old-manifest", str(OLD_MANIFEST), "--new-manifest", str(NEW_MANIFEST),
         "--registry", str(registry), "--out-dir", str(tmp / "out"),
         "--bytes-dir", str(bytes_dir)],
        env=env, capture_output=True, text=True, timeout=300, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return tmp / "out"


def test_d042_is_a_metadata_only_rename_not_a_quarantine(replay: Path) -> None:
    written = replay / "tranche-diff-096ef2c0058a.json"
    diff = json.loads(written.read_text())
    assert diff["tranche_sha256"] == receipt()["tranche_sha256"]
    assert all(q["new_card_id"] != D042_NEW_ID for q in diff["quarantined"])
    [row] = diff["renames_metadata_only"]
    assert (row["old_card_id"], row["new_card_id"]) == (D042_OLD_ID, D042_NEW_ID)
    assert (row["verdict"], row["method"]) == ("metadata-only", "metadata-only-resave")
    assert diff["summary"]["renames_metadata_only"] == 1
    assert diff["summary"]["quarantined"] == len(diff["quarantined"])
    assert all(r["card_id"] != D042_OLD_ID for r in diff["removed"])
    md = (replay / "tranche-diff-096ef2c0058a.md").read_text()
    assert "Renames by metadata-only re-save" in md


def test_ingest_approve_aliases_d042_without_a_flag(
    replay: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingest_cli, "enforce_poll_freshness", lambda *a, **k: None)
    result = CliRunner().invoke(app, [
        "ingest", "approve", "--tranche", receipt()["tranche_sha256"],
        "--note", "D042 metadata-only re-save", "--skip-audit",
        "--log", str(tmp_path / "log.jsonl"), "--aliases", str(tmp_path / "aliases.json"),
        "--diff-dir", str(replay), "--snapshots-dir", str(tmp_path / "snaps"),
    ])
    assert result.exit_code == 0, result.output
    aliases = json.loads((tmp_path / "aliases.json").read_text())["aliases"]
    assert [(a["old_card_id"], a["new_card_id"], a["method"]) for a in aliases] == [
        (D042_OLD_ID, D042_NEW_ID, "metadata-only-resave")]
