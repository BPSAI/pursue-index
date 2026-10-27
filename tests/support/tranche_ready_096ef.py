"""Replay the poll's snapshot job on the Release-7 tranche 096ef2c0058a.

``run_replay`` drives ``scripts/poll_snapshot.py``'s ``main`` exactly as the
workflow's snapshot step does -- the committed CSV bytes for 096ef against a
``latest.json`` that is the receipt's prior manifest (c3f8...) -- with every
tranche-ready output going to ``tmp``. Only the network is stubbed
(``csv_fetcher.http_get``):

* each of the 28 net-new PDFs serves a blank PDF with the page count the
  published ``pages.json`` gives that card (1,140 pages over the 29 scoped
  cards, the example's figure);
* D042's NEW URL serves the synthetic metadata-only re-save
  (``tranche_bytes_fakes``) of a synthetic base PDF, and D042's OLD URL --
  the old card's ``asset_url`` in the prior manifest -- serves that base
  PDF, or fails when ``old_fetch_ok`` is false.

The registry is the receipt-time registry (``tranche_096ef``) plus one row
pinning D042's old card to the base PDF's sha, so the old bytes the stub
serves are the registry's bytes. The clean-qc bundle meters the judge at
0.0165/page, the example's metered figure.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from pursue_index.scrape import csv_fetcher
from tests.support.pdf_page_fakes import FakeHttpGet, pdf_bytes
from tests.support.tranche_096ef import (
    D042_NEW_ID,
    D042_OLD_ID,
    DATA,
    NEW_MANIFEST,
    OLD_MANIFEST,
    REPO_ROOT,
    receipt_time_registry,
)
from tests.support.tranche_bytes_fakes import build_base_pdf, metadata_only_resave

SHA = "096ef2c0058abd412a568d630df31cb836241c1c08c4f67bdc8cdb7e5c8418b9"
CSV = DATA / "raw" / "csv" / f"{SHA}.csv"
VECTOR = REPO_ROOT / "tests" / "fixtures" / "tranche-ready-096ef.json"

# Pages per scoped card, counted from web/public/data/pages.json (the
# published OCR of this tranche): 1,140 in all.
PAGE_COUNTS = {
    "0e2f21236a2289fa": 3, "12a7f37083cf2b87": 50, "149f0e075ae4517d": 42,
    "1af7a333fa99bdd9": 2, "21c9fa9b9a543068": 72, "2570557981d64cc7": 2,
    "338995394c698b33": 5, "38e700c6f51082f0": 1, "3acf9cf5047465bd": 298,
    "3d74932e77e7868e": 5, "55f5f0db04de21f2": 3, "6a7a525ada83a4d6": 134,
    "6f5beb626837fa74": 6, "81fe3a1b9cd4bf42": 3, "82f2e60220d94740": 141,
    "85fd315af4b25993": 42, "9bd42e0157fe4697": 26, "a3a9754af3184c3b": 5,
    "b63bea0452d1d4b3": 4, "b87355e7ab051114": 49, "cb5426fe2a0b512d": 5,
    "d3cb04b8e4d55dc1": 4, "d6016299267e9604": 60, "e5c4575f838f0175": 4,
    "ee657817d068d59b": 11, "f52425adaa32c4f2": 4, "fc95f65e81965edf": 3,
    "ffea128d68063d60": 155, D042_NEW_ID: 1,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _urls(manifest: Path) -> dict[str, str]:
    return {c["card_id"]: c["asset_url"] for c in json.loads(manifest.read_text())["cards"]
            if c.get("asset_type") == "PDF" and c.get("asset_url")}


def d042_bytes() -> tuple[bytes, bytes]:
    """(old, new): a base PDF and its metadata-only re-save."""
    base = build_base_pdf()
    return base.data, metadata_only_resave(base)


def fake_http_get(*, old_fetch_ok: bool = True, pages: dict[str, int] | None = None) -> FakeHttpGet:
    old, new = d042_bytes()
    new_urls = _urls(NEW_MANIFEST)
    bodies = {new_urls[cid]: pdf_bytes(n) for cid, n in (pages or PAGE_COUNTS).items()}
    bodies[new_urls[D042_NEW_ID]] = new
    old_url = _urls(OLD_MANIFEST)[D042_OLD_ID]
    if old_fetch_ok:
        bodies[old_url] = old
    return FakeHttpGet(bodies=bodies, fail=frozenset() if old_fetch_ok else {old_url})


def replay_args(tmp: Path, *extra: str) -> list[str]:
    """argv for ``poll_snapshot.main``; every output lands under ``tmp``."""
    tmp.mkdir(parents=True, exist_ok=True)
    if not (tmp / "latest.json").exists():
        shutil.copy(OLD_MANIFEST, tmp / "latest.json")
    old, _ = d042_bytes()
    registry = receipt_time_registry(tmp / "registry.jsonl", [{
        "card_id": D042_OLD_ID, "byte_sha256": sha256(old),
        "fetched_at": "2099-01-01T00:00:00+00:00"}])
    bundle = tmp / "clean-qc-bundle.json"
    bundle.write_text(json.dumps({"stats": {"metered_judge_spend_usd": 16.5,
                                            "metered_judge_calls": 1000}}))
    return [
        "--csv", str(CSV), "--latest", str(tmp / "latest.json"),
        "--canonical-dir", str(tmp / "canonical"), "--public-dir", str(tmp / "public"),
        "--diff-out", str(tmp / "diffs" / f"{SHA}.json"),
        "--summary-out", str(tmp / "verdict-summary.md"), "--qc-bundle", str(bundle),
        "--tranche-ready-dir", str(tmp / "tranche-ready"),
        "--tranche-diff-dir", str(tmp / "tranche-diffs"),
        "--registry", str(registry), "--poll-state", str(DATA / "poll-state.json"),
        "--csv-archive", str(DATA / "raw" / "csv"),
        "--tranche-issue", "177", "--poll-commit", "b3cac29",
        "--error-out", str(tmp / "tranche-ready-error.md"), *extra,
    ]


def run_replay(tmp: Path, http_get: FakeHttpGet, *extra: str) -> int:
    """Run the snapshot job's script in-process with ``http_get`` as the network."""
    import poll_snapshot  # scripts/ is on sys.path via the caller

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(csv_fetcher, "http_get", http_get)
        return poll_snapshot.main(replay_args(tmp, *extra))
