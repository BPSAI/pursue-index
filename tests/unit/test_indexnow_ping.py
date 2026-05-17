"""Tests for ``scripts/indexnow_ping.py``.

Sprint 4b Theme B. After every CF Workers Builds deploy that touches a
render-affecting path, the post-deploy workflow submits the live
sitemap URLs to IndexNow so Bing/Yandex (and ChatGPT-search via Bing)
pick up changes within minutes instead of days.

These tests cover pure helpers (URL collection, batch splitting,
payload construction) plus the end-to-end ``main()`` with ``urlopen``
mocked. Same approach as ``test_wayback_save.py`` so a future operator
reading both files sees the same idiom.
"""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import indexnow_ping  # noqa: E402


# --- sitemap parsing --------------------------------------------------


_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://pursueindex.com/</loc></url>
  <url><loc>https://pursueindex.com/about</loc></url>
  <url><loc>https://pursueindex.com/card/0b298cfc9c65a4d6</loc></url>
</urlset>
""".strip()


def test_parse_sitemap_urls_returns_loc_values() -> None:
    urls = indexnow_ping.parse_sitemap_urls(_SITEMAP_XML)
    assert urls == [
        "https://pursueindex.com/",
        "https://pursueindex.com/about",
        "https://pursueindex.com/card/0b298cfc9c65a4d6",
    ]


# --- batching --------------------------------------------------------


def test_chunk_urls_respects_max_batch_size() -> None:
    """``chunk_urls`` yields at most ``size`` URLs per batch."""
    urls = [f"https://pursueindex.com/{i}" for i in range(2500)]
    batches = list(indexnow_ping.chunk_urls(urls, size=1000))
    assert len(batches) == 3
    assert len(batches[0]) == 1000
    assert len(batches[1]) == 1000
    assert len(batches[2]) == 500


def test_chunk_urls_emits_one_batch_when_under_limit() -> None:
    urls = ["https://pursueindex.com/a", "https://pursueindex.com/b"]
    batches = list(indexnow_ping.chunk_urls(urls, size=10000))
    assert batches == [urls]


def test_chunk_urls_yields_nothing_for_empty_input() -> None:
    assert list(indexnow_ping.chunk_urls([], size=100)) == []


# --- payload construction --------------------------------------------


def test_build_payload_includes_host_key_keyLocation_urlList() -> None:
    """Per IndexNow spec, all four fields are required."""
    urls = ["https://pursueindex.com/", "https://pursueindex.com/about"]
    payload = indexnow_ping.build_payload(
        host="pursueindex.com",
        key="abc123",
        key_location="https://pursueindex.com/abc123.txt",
        urls=urls,
    )
    assert payload == {
        "host": "pursueindex.com",
        "key": "abc123",
        "keyLocation": "https://pursueindex.com/abc123.txt",
        "urlList": urls,
    }


def test_build_payload_url_list_preserves_input_order() -> None:
    urls = ["https://pursueindex.com/z", "https://pursueindex.com/a"]
    payload = indexnow_ping.build_payload(
        host="pursueindex.com",
        key="k",
        key_location="https://pursueindex.com/k.txt",
        urls=urls,
    )
    assert payload["urlList"] == urls


# --- key resolution --------------------------------------------------


def test_resolve_key_prefers_env_var_when_set(monkeypatch: Any) -> None:
    """``INDEXNOW_KEY`` env wins over the on-disk file."""
    monkeypatch.setenv("INDEXNOW_KEY", "env-key")
    # Even if the file exists with another value, env should win.
    assert indexnow_ping.resolve_key(file_path=None) == "env-key"


def test_resolve_key_reads_file_when_env_unset(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.delenv("INDEXNOW_KEY", raising=False)
    keyfile = tmp_path / "indexnow-key.txt"
    keyfile.write_text("file-key\n")
    assert indexnow_ping.resolve_key(file_path=keyfile) == "file-key"


def test_resolve_key_returns_none_when_neither_source_present(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Graceful: missing key → return None so main() can exit 0."""
    monkeypatch.delenv("INDEXNOW_KEY", raising=False)
    nonexistent = tmp_path / "no-such-file.txt"
    assert indexnow_ping.resolve_key(file_path=nonexistent) is None


# --- main() end-to-end ------------------------------------------------


def _make_mock_urlopen(
    response_status: int = 200,
    response_body: bytes = b"",
    captured: list[Any] | None = None,
):
    """Build a urlopen-mock that records each call into ``captured``."""

    class _Resp:
        status = response_status

        def __init__(self) -> None:
            self._body = response_body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_: Any) -> None:
            return None

    def _urlopen(req: Any, timeout: float = 60.0) -> Any:  # noqa: ARG001
        if captured is not None:
            # urllib.request.Request: .full_url, .data, .headers
            captured.append(
                {
                    "url": req.full_url,
                    "data": bytes(req.data) if req.data else b"",
                    "headers": dict(req.headers),
                }
            )
        return _Resp()

    return _urlopen


def test_main_exits_0_when_key_missing(monkeypatch: Any, tmp_path: Path) -> None:
    """No env, no file → graceful exit 0 (no network call)."""
    monkeypatch.delenv("INDEXNOW_KEY", raising=False)
    nonexistent = tmp_path / "no-key.txt"
    args = indexnow_ping._build_parser().parse_args(
        [
            "--sitemap",
            "ignored",
            "--key-file",
            str(nonexistent),
            "--host",
            "pursueindex.com",
        ]
    )
    # Should not call urlopen at all when key is missing.
    with patch.object(indexnow_ping.urllib.request, "urlopen") as mock_urlopen:
        rc = indexnow_ping._main_with_args(args)
    assert rc == 0
    assert mock_urlopen.call_count == 0


def test_main_posts_payload_to_indexnow_with_correct_shape(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Happy path: 200 from IndexNow, JSON body has host/key/keyLocation/urlList."""
    monkeypatch.setenv("INDEXNOW_KEY", "abc123")
    sitemap_file = tmp_path / "sitemap.xml"
    sitemap_file.write_text(_SITEMAP_XML)
    args = indexnow_ping._build_parser().parse_args(
        [
            "--sitemap",
            str(sitemap_file),
            "--host",
            "pursueindex.com",
        ]
    )
    captured: list[Any] = []
    fake = _make_mock_urlopen(response_status=200, captured=captured)
    with patch.object(indexnow_ping.urllib.request, "urlopen", side_effect=fake):
        rc = indexnow_ping._main_with_args(args)
    assert rc == 0
    assert len(captured) == 1, "exactly one IndexNow POST for a small sitemap"
    req = captured[0]
    assert req["url"] == "https://api.indexnow.org/indexnow"
    body = json.loads(req["data"].decode("utf-8"))
    assert body["host"] == "pursueindex.com"
    assert body["key"] == "abc123"
    assert (
        body["keyLocation"]
        == "https://pursueindex.com/abc123.txt"
    )
    assert body["urlList"] == [
        "https://pursueindex.com/",
        "https://pursueindex.com/about",
        "https://pursueindex.com/card/0b298cfc9c65a4d6",
    ]


def test_main_splits_oversized_sitemap_into_batches(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """A 25 000-URL sitemap → three IndexNow POSTs of ≤10 000 each."""
    monkeypatch.setenv("INDEXNOW_KEY", "k")
    loc_lines = "\n".join(
        f"  <url><loc>https://pursueindex.com/p{i}</loc></url>"
        for i in range(25000)
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{loc_lines}\n"
        "</urlset>\n"
    )
    sitemap_file = tmp_path / "big.xml"
    sitemap_file.write_text(xml)
    args = indexnow_ping._build_parser().parse_args(
        [
            "--sitemap",
            str(sitemap_file),
            "--host",
            "pursueindex.com",
        ]
    )
    captured: list[Any] = []
    fake = _make_mock_urlopen(response_status=200, captured=captured)
    with patch.object(indexnow_ping.urllib.request, "urlopen", side_effect=fake):
        rc = indexnow_ping._main_with_args(args)
    assert rc == 0
    # ceil(25000 / 10000) = 3
    assert len(captured) == 3
    bodies = [json.loads(c["data"]) for c in captured]
    assert sum(len(b["urlList"]) for b in bodies) == 25000


def test_main_returns_0_on_per_batch_failure_but_logs_warning(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    """Per-batch failure surfaces as ``::warning::`` but exit 0 (matches wayback posture)."""
    monkeypatch.setenv("INDEXNOW_KEY", "k")
    sitemap_file = tmp_path / "sitemap.xml"
    sitemap_file.write_text(_SITEMAP_XML)
    args = indexnow_ping._build_parser().parse_args(
        [
            "--sitemap",
            str(sitemap_file),
            "--host",
            "pursueindex.com",
        ]
    )
    fake = _make_mock_urlopen(response_status=429)
    with patch.object(indexnow_ping.urllib.request, "urlopen", side_effect=fake):
        rc = indexnow_ping._main_with_args(args)
    assert rc == 0
    captured_out = capsys.readouterr().out
    assert "::warning::" in captured_out
    assert "429" in captured_out


def test_main_exits_0_when_sitemap_unreachable(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Missing sitemap → graceful exit 0 (no IndexNow call)."""
    monkeypatch.setenv("INDEXNOW_KEY", "k")
    args = indexnow_ping._build_parser().parse_args(
        [
            "--sitemap",
            str(tmp_path / "does-not-exist.xml"),
            "--host",
            "pursueindex.com",
        ]
    )
    with patch.object(indexnow_ping.urllib.request, "urlopen") as mock_urlopen:
        rc = indexnow_ping._main_with_args(args)
    assert rc == 0
    assert mock_urlopen.call_count == 0


def test_main_uses_mozilla_style_user_agent(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Same UA posture as wayback_save: CF blocks default Python-urllib UA."""
    monkeypatch.setenv("INDEXNOW_KEY", "k")
    sitemap_file = tmp_path / "sitemap.xml"
    sitemap_file.write_text(_SITEMAP_XML)
    args = indexnow_ping._build_parser().parse_args(
        [
            "--sitemap",
            str(sitemap_file),
            "--host",
            "pursueindex.com",
        ]
    )
    captured: list[Any] = []
    fake = _make_mock_urlopen(response_status=200, captured=captured)
    with patch.object(indexnow_ping.urllib.request, "urlopen", side_effect=fake):
        indexnow_ping._main_with_args(args)
    # urllib lowercases custom-header keys when adding them via Request(headers=…).
    ua = captured[0]["headers"].get("User-agent") or captured[0]["headers"].get(
        "user-agent"
    )
    assert ua is not None
    assert "Mozilla" in ua
    assert "pursueindex" in ua
