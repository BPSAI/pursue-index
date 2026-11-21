"""Round-1 review fixes: credentials, streaming, lanes, revert-to-earlier-bytes."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2, sha

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


# --- 3: missing credentials fail closed only in the weekly full-hash -----------------


@pytest.mark.parametrize("extra", [[], ["--fail-on-drift"]])
def test_missing_credentials_warn_and_skip_outside_the_weekly(w, extra, capsys):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    w.creds = False
    assert w.run(*extra) == 0
    cap = capsys.readouterr()
    assert "credential" in (cap.out + cap.err).lower()
    assert w.fetched == [] and w.new_rows() == [], "the archive step is skipped, not half-run"


def test_the_weekly_full_hash_still_fails_closed_without_credentials(w, capsys):
    w.add_card(1)
    w.creds = False
    rc = w.run("--full-hash", "--max-bytes-per-run", "1000", "--run-record", str(w.record))
    assert rc != 0 and "credential" in capsys.readouterr().err.lower()


# --- 4: no response body is ever held in memory --------------------------------------


class _StreamResp:
    status_code = 200

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.chunk_sizes: list[int] = []

    @property
    def content(self) -> bytes:
        raise AssertionError("response.content holds the whole body in memory")

    def raise_for_status(self) -> None: ...

    def iter_content(self, chunk_size: int = 0):
        self.chunk_sizes.append(chunk_size)
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


@pytest.mark.parametrize("ext", ["pdf", "jpg", "mp4", "mp3"])
def test_fetch_streams_into_the_hash_in_chunks_for_every_type(monkeypatch, tmp_path, ext):
    import _r2_fetch

    chunks = [b"a" * 10, b"b" * 7, b"c" * 3]
    resp = _StreamResp(chunks)
    seen: dict = {}

    def fake_get(url, **kw):
        seen.update(kw)
        return resp

    monkeypatch.setattr(_r2_fetch.cffi_requests, "get", fake_get)
    dest = tmp_path / f"asset.{ext}"
    digest, size = r2.fetch_asset(f"https://www.war.gov/x.{ext}", dest)
    assert seen.get("stream") is True
    assert resp.chunk_sizes and resp.chunk_sizes[0] > 0
    assert (digest, size) == (hashlib.sha256(b"".join(chunks)).hexdigest(), 20)
    assert dest.read_bytes() == b"".join(chunks)


def test_an_upload_is_made_from_the_file_not_from_a_bytes_body(w, monkeypatch):
    bodies: list[object] = []
    monkeypatch.setattr(
        r2, "put_archive_and_current", lambda c, b, ak, ck, body, ct: bodies.append(body) or False
    )
    w.add_card(1, "VID", ext="mp4", body=NEW_BODY)
    assert w.run("--full-hash", "--max-bytes-per-run", "1000", "--run-record", str(w.record)) == 0
    assert bodies and not isinstance(bodies[0], bytes | bytearray)


def test_put_streams_a_path_body_as_a_file_object(tmp_path):
    from _r2_archive_put import put_archive_and_current

    f = tmp_path / "b.bin"
    f.write_bytes(b"payload")
    got: list[bytes] = []

    class C:
        def put_object(self, **kw):
            assert not isinstance(kw["Body"], bytes)
            got.append(kw["Body"].read())

    put_archive_and_current(C(), "b", "archive/x.mp4", "cur.mp4", f, "video/mp4")
    assert got == [b"payload", b"payload"], "each PUT reads the file from the start"


# --- 5: the poll lane keeps VID and AUD out ------------------------------------------


def test_asset_types_filter_excludes_vid_and_aud(w):
    w.add_card(1, "PDF", body=NEW_BODY)
    w.add_card(2, "VID", ext="mp4", body=NEW_BODY)
    w.add_card(3, "AUD", ext="mp3", body=NEW_BODY)
    w.add_card(4, "IMG", ext="jpg", body=NEW_BODY)
    assert w.run("--asset-types", "PDF,IMG") == 0
    assert sorted(w.fetched) == sorted(c["asset_url"] for c in (w.cards[0], w.cards[3]))
    assert len(w.new_rows()) == 2


def test_the_default_still_covers_every_asset_type(w):
    for n, (t, e) in enumerate([("PDF", "pdf"), ("IMG", "jpg"), ("VID", "mp4"), ("AUD", "mp3")]):
        w.add_card(n + 1, t, ext=e, body=NEW_BODY)
    assert w.run() == 0
    assert len(w.fetched) == 4


def test_a_full_hash_over_a_filtered_run_is_never_recorded_complete(w):
    w.add_card(1)
    rc = w.run("--full-hash", "--max-bytes-per-run", "1000", "--run-record", str(w.record),
               "--asset-types", "PDF")
    assert rc != 0 and not w.record.exists()


def test_the_poll_lane_runs_the_archive_without_vid_and_aud():
    text = (ROOT / ".github/workflows/poll-pursue.yml").read_text()
    steps = [s for s in yaml.safe_load(text)["jobs"].values() for s in s["steps"]]
    step = next(s for s in steps if s.get("id") == "r2_archive")
    assert "r2_archive_assets.py" in step["run"]
    m = re.search(r"--asset-types\s+(\S+)", step["run"])
    assert m and set(m.group(1).split(",")) == {"PDF", "IMG"}


# --- 6: the weekly byte budget covers the real corpus ---------------------------------


def _corpus_bytes() -> int:
    reg: dict[str, dict] = {}
    for line in (ROOT / "data/asset-bytes-registry.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["card_id"] not in reg or row["fetched_at"] >= reg[row["card_id"]]["fetched_at"]:
                reg[row["card_id"]] = row
    cards = json.loads((ROOT / "data/manifests/latest.json").read_text())["cards"]
    return sum(
        reg[c["card_id"]]["byte_size"]
        for c in cards
        if c.get("asset_url") and c.get("asset_type") in r2.ASSET_TYPES and c["card_id"] in reg
    )


def test_the_weekly_default_budget_exceeds_the_corpus_with_headroom():
    text = (ROOT / ".github/workflows/verify-assets-weekly.yml").read_text()
    defaults = {int(n) for n in re.findall(r"'(\d{9,})'|\"(\d{9,})\"", text) for n in n if n}
    assert defaults, "the workflow must carry an explicit default byte budget"
    total = _corpus_bytes()
    assert all(d >= total * 1.25 for d in defaults), (total, defaults)
    assert f"{total:,}" in text or str(total) in text, "the comment states the computed total"


# --- 7: a revert to earlier bytes is a change ----------------------------------------


def test_reverting_to_earlier_bytes_is_a_change_and_drift(w, capsys):
    cid = w.add_card(1, prior=OLD_BODY, body=OLD_BODY, head_matches_prior=False)
    # Registry history: OLD -> NEW (latest). Upstream now serves OLD again.
    w.rows.append({**w.rows[0], "byte_sha256": sha(NEW_BODY), "byte_size": len(NEW_BODY),
                   "archive_key": f"archive/{sha(NEW_BODY)}.pdf",
                   "fetched_at": "2026-06-01T00:00:00+00:00"})
    rc = w.run("--full-hash", "--max-bytes-per-run", "1000", "--run-record", str(w.record),
               "--fail-on-drift", "--dispositions", str(w.dispositions))
    new = w.new_rows()
    assert [(r["card_id"], r["byte_sha256"]) for r in new] == [(cid, sha(OLD_BODY))]
    assert rc != 0 and "BYTE DRIFT" in capsys.readouterr().err


def test_bytes_equal_to_the_latest_row_are_still_unchanged(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY, head_matches_prior=False)
    assert w.run() == 0
    assert w.new_rows() == []


# --- 2: the unverifiable ceiling -------------------------------------------------------


def test_the_makefile_ceiling_is_a_margin_not_zero():
    m = re.search(r"^OCR_MAX_UNVERIFIABLE \?= (\d+)", (ROOT / "Makefile").read_text(), re.M)
    assert m and 0 < int(m.group(1)) <= 10, "warn and count below a small ceiling; zero gates"
    runbook = (ROOT / "docs/runbooks/ship-tranche.md").read_text()
    assert "OCR_MAX_UNVERIFIABLE" in runbook
