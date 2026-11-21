"""A network-free, R2-free world for driving ``scripts/r2_archive_assets.py``'s ``main``.

Every fetch, HEAD and R2 client is a stub; nothing here touches a network.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import r2_archive_assets as r2  # noqa: E402

OLD_BODY = b"old bytes"
NEW_BODY = b"new bytes!"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def card_id(n: int) -> str:
    return f"{n:016x}"


def url(n: int, ext: str = "pdf") -> str:
    return f"https://www.war.gov/medialink/ufo/c{n}.{ext}"


class World:
    """Cards, prior registry rows, HEAD answers and fetched bodies, all in memory."""

    def __init__(self, tmp_path: Path, monkeypatch) -> None:
        self.tmp = tmp_path
        self.cards: list[dict] = []
        self.rows: list[dict] = []
        self.head: dict[str, tuple] = {}
        self.bodies: dict[str, bytes] = {}
        self.fetched: list[str] = []
        self.headed: list[str] = []
        self.manifest = tmp_path / "latest.json"
        self.registry = tmp_path / "registry.jsonl"
        self.record = tmp_path / "full-hash-runs.jsonl"
        self.dispositions = tmp_path / "dispositions.jsonl"
        self.creds = True
        monkeypatch.setattr(r2, "head_asset", self._head)
        monkeypatch.setattr(r2, "fetch_asset", self._fetch)
        monkeypatch.setattr(r2, "make_r2_client", lambda: object() if self.creds else None)
        monkeypatch.setattr(r2, "put_archive_and_current", lambda *a, **k: False)

    def _head(self, u):
        self.headed.append(str(u))
        got = tuple(self.head.get(str(u), (None, None)))
        return (*got, None)[:3]  # (content_length, etag, last_modified)

    def _fetch(self, u, dest):
        """The streaming seam: write the body to ``dest``; return ``(sha256, size)``."""
        self.fetched.append(str(u))
        body = self.bodies[str(u)]
        Path(dest).write_bytes(body)
        return sha(body), len(body)

    def add_card(
        self, n: int, asset_type: str = "PDF", *, prior: bytes | None = None,
        body: bytes = NEW_BODY, ext: str = "pdf", etag: str | None = '"e1"',
        head_matches_prior: bool = True, last_modified: str | None = None,
    ) -> str:
        cid, u = card_id(n), url(n, ext)
        self.cards.append({
            "card_id": cid, "title": f"t{n}", "asset_type": asset_type, "agency": "A",
            "asset_url": u, "asset_filename": f"c{n}.{ext}",
        })
        self.bodies[u] = body
        if prior is not None:
            self.rows.append({
                "card_id": cid, "asset_url": u, "asset_filename": f"c{n}.{ext}",
                "byte_sha256": sha(prior), "byte_size": len(prior), "upstream_etag": etag,
                **({"upstream_last_modified": last_modified} if last_modified else {}),
                "archive_key": f"archive/{sha(prior)}.{ext}", "current_key": f"{cid}.{ext}",
                "fetched_at": "2026-05-11T00:00:00+00:00",
            })
            if head_matches_prior:
                self.head[u] = (len(prior), etag, last_modified)
        return cid

    def write(self) -> None:
        self.manifest.write_text(json.dumps({
            "source_url": "https://www.war.gov/UFO/", "fetched_at": "2026-11-21T00:00:00Z",
            "csv_sha256": "0" * 64, "cards": self.cards,
        }))
        self.registry.write_text("".join(json.dumps(r) + "\n" for r in self.rows))

    def run(self, *extra: str, capsys=None) -> int:
        self.write()
        args = ["--manifest", str(self.manifest), "--registry", str(self.registry), *extra]
        return r2.main(args)

    def registry_rows(self) -> list[dict]:
        return [json.loads(ln) for ln in self.registry.read_text().splitlines() if ln.strip()]

    def new_rows(self) -> list[dict]:
        return self.registry_rows()[len(self.rows):]


def world(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)
