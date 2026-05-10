"""Tests for the PDF-fetch health check.

The 6h cron poll currently only exercises the CSV endpoint. If Akamai
ever tightens PDF gating *separately* (e.g. only the medialink/
download path gets new bot rules), we want to find out within 6h via
the same issue-creation pipeline — not hours/days later when an
operator-attended download stage trips.

These tests pin the contract for the health-check module:

* sentinel selection is **deterministic** across runs (operator must
  be able to reproduce a failure)
* the fetch reuses the curl_cffi Chrome-impersonate path so a gating
  shift catches both CSV and PDF fetches at once
* a 200 with bytes back -> ok, exit 0
* a 403/4xx -> fail, exit 1, error string mentions the status
* a transport error -> fail, exit 1, error string mentions the
  exception type
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.scrape import pdf_health


_MANIFEST_TWO_PDFS = {
    "source_url": "https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-csv.csv",
    "fetched_at": "2026-05-08T21:00:46.185453Z",
    "csv_sha256": "deadbeef" * 8,
    "cards": [
        {
            "card_id": "ffff000000000001",
            "title": "Z-card-late-lex",
            "asset_type": "PDF",
            "agency": "FBI",
            "asset_url": "https://www.war.gov/medialink/ufo/release_1/late.pdf",
            "asset_filename": "late.pdf",
            "raw": {},
        },
        {
            "card_id": "0000ffff00000002",
            "title": "A-card-early-lex",
            "asset_type": "PDF",
            "agency": "FBI",
            "asset_url": "https://www.war.gov/medialink/ufo/release_1/early.pdf",
            "asset_filename": "early.pdf",
            "raw": {},
        },
        {
            "card_id": "00000000ffff0003",
            "title": "Video card — must be skipped",
            "asset_type": "VID",
            "agency": "DOW",
            "asset_url": "https://www.dvidshub.net/video/12345",
            "raw": {},
        },
    ],
}


def _write_manifest(tmp_path: Path, payload: dict) -> Path:
    """Persist a minimal-but-valid manifest fixture and return the path."""
    p = tmp_path / "latest.json"
    p.write_text(json.dumps(payload))
    return p


# ---------------------------------------------------------------------------
# sentinel selection
# ---------------------------------------------------------------------------


def test_pick_sentinel_returns_lex_smallest_pdf_card_id(tmp_path: Path) -> None:
    """Determinism: same manifest -> same sentinel across runs.

    Lex-smallest card_id wins so a manifest reorder doesn't shift the
    sentinel and create spurious "different PDF failed today" noise.
    The VID card has the smallest card_id overall but must NOT be
    picked — only PDFs are eligible.
    """
    manifest_path = _write_manifest(tmp_path, _MANIFEST_TWO_PDFS)

    sentinel = pdf_health.pick_sentinel(manifest_path)

    # 0000ffff00000002 (early.pdf) < ffff000000000001 (late.pdf).
    assert sentinel.card_id == "0000ffff00000002"
    assert str(sentinel.asset_url).endswith("/early.pdf")


def test_pick_sentinel_skips_non_pdf_cards(tmp_path: Path) -> None:
    """A VID card with a smaller card_id must NOT be picked — only PDFs."""
    manifest_path = _write_manifest(tmp_path, _MANIFEST_TWO_PDFS)

    sentinel = pdf_health.pick_sentinel(manifest_path)

    assert sentinel.asset_type == "PDF"


def test_pick_sentinel_raises_when_no_pdfs(tmp_path: Path) -> None:
    """If a manifest somehow has zero PDFs, surface that loudly — the cron
    should not silently green when there's nothing to check."""
    payload = dict(_MANIFEST_TWO_PDFS)
    payload["cards"] = [c for c in payload["cards"] if c["asset_type"] != "PDF"]
    manifest_path = _write_manifest(tmp_path, payload)

    with pytest.raises(ValueError, match="no PDF"):
        pdf_health.pick_sentinel(manifest_path)


# ---------------------------------------------------------------------------
# health check fetch
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


def test_check_pdf_health_uses_chrome_impersonation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The health fetch MUST go through curl_cffi Chrome impersonation —
    the whole point is to mirror the CSV fetcher's TLS contract so a
    gating shift catches both at once."""
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse(200, b"x" * 256)

    monkeypatch.setattr(pdf_health.csv_fetcher, "http_get", fake_get)

    result = pdf_health.check_pdf_health("https://www.war.gov/x.pdf")

    assert isinstance(result, pdf_health.HealthOk)
    assert result.bytes_received == 256
    assert "chrome" in str(captured.get("impersonate", "")).lower()
    # Range request keeps the health check cheap (no full PDF download).
    headers = captured.get("headers", {})
    assert isinstance(headers, dict)
    assert headers.get("Range", "").startswith("bytes=0-")


def test_check_pdf_health_returns_fail_on_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 403 is the canonical Akamai-gating signature. The fail result must
    carry the status so the issue body can quote it verbatim."""

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(403, b"Access Denied")

    monkeypatch.setattr(pdf_health.csv_fetcher, "http_get", fake_get)

    result = pdf_health.check_pdf_health("https://www.war.gov/x.pdf")

    assert isinstance(result, pdf_health.HealthFail)
    assert result.status == 403
    assert "403" in result.error


def test_check_pdf_health_returns_fail_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 isn't Akamai gating but it's still a real failure — the sentinel
    URL changed underneath us, or the manifest is stale. Same alert path."""

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(404, b"")

    monkeypatch.setattr(pdf_health.csv_fetcher, "http_get", fake_get)

    result = pdf_health.check_pdf_health("https://www.war.gov/x.pdf")

    assert isinstance(result, pdf_health.HealthFail)
    assert result.status == 404


def test_check_pdf_health_returns_fail_on_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A network/DNS error must NOT crash the script — it's the same alert
    the operator wants to see (something is wrong with the fetch path)."""

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        raise ConnectionError("name resolution failed")

    monkeypatch.setattr(pdf_health.csv_fetcher, "http_get", fake_get)

    result = pdf_health.check_pdf_health("https://www.war.gov/x.pdf")

    assert isinstance(result, pdf_health.HealthFail)
    assert result.status == -1  # transport sentinel
    assert "ConnectionError" in result.error


# ---------------------------------------------------------------------------
# kv-format helpers (format_ok / format_fail)
# ---------------------------------------------------------------------------


def test_format_ok_emits_stable_kv_line() -> None:
    """``pdf-health.ok url=<url> bytes=<n>`` is the contract the workflow
    log greps. Pin the exact format so a reorder/rename of fields can't
    silently break a downstream awk/cut consumer."""
    result = pdf_health.HealthOk(url="https://www.war.gov/x.pdf", bytes_received=256)

    assert pdf_health.format_ok(result) == (
        "pdf-health.ok url=https://www.war.gov/x.pdf bytes=256"
    )


def test_format_fail_replaces_internal_whitespace_with_underscores() -> None:
    """A multi-word error like ``ValueError: no PDF cards in manifest``
    contains spaces that break any whitespace-splitting log parser. The
    sanitizer must collapse them to a single token (underscores)."""
    result = pdf_health.HealthFail(
        url="-",
        status=-1,
        error="ValueError: no PDF cards in manifest",
    )

    line = pdf_health.format_fail(result)

    # Header fields stay quotable single tokens.
    assert line.startswith("pdf-health.fail url=- status=-1 error=")
    # Extract the error= value and assert it has no internal whitespace.
    error_value = line.split("error=", 1)[1]
    assert " " not in error_value
    assert "\t" not in error_value


def test_format_fail_redacts_cf_ray_substring() -> None:
    """WAF debug headers (cf-ray, x-akamai-*, x-check-cacheable, via:*) can
    contain operator-internal info we don't want in the public Actions
    log. Redact known patterns before printing. (laverna SEC-002)"""
    result = pdf_health.HealthFail(
        url="https://www.war.gov/x.pdf",
        status=403,
        error="HTTPError 403 cf-ray:abc12345-LAX",
    )

    line = pdf_health.format_fail(result)

    assert "cf-ray" not in line.lower()
    assert "[redacted]" in line


def test_format_fail_truncates_long_error_to_80_chars() -> None:
    """An unbounded error string would blow up the log line length and
    bury the structured kv fields. Cap at 80 chars."""
    long_error = "X" * 200
    result = pdf_health.HealthFail(
        url="https://www.war.gov/x.pdf", status=500, error=long_error
    )

    line = pdf_health.format_fail(result)

    error_value = line.split("error=", 1)[1]
    assert len(error_value) <= 80


def test_format_fail_handles_empty_error_string() -> None:
    """An empty error must not produce ``error=`` (a dangling kv) — the
    parser must always see a value token, even if it's just ``unknown``."""
    result = pdf_health.HealthFail(url="-", status=-1, error="")

    line = pdf_health.format_fail(result)

    error_value = line.split("error=", 1)[1]
    assert error_value  # non-empty
    assert " " not in error_value


# ---------------------------------------------------------------------------
# CLI: `pursue ops pdf-health`
# ---------------------------------------------------------------------------


def _patch_pdf_health_cli(
    monkeypatch: pytest.MonkeyPatch, status_code: int, body: bytes
) -> None:
    """Wire a fake transport into the module the CLI calls."""

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(status_code, body)

    monkeypatch.setattr(pdf_health.csv_fetcher, "http_get", fake_get)


def test_cli_pdf_health_exits_zero_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Happy path: 200 -> exit 0, stdout starts with ``pdf-health.ok``."""
    from typer.testing import CliRunner

    from pursue_index.cli.ops_cli import ops_app

    manifest_path = _write_manifest(tmp_path, _MANIFEST_TWO_PDFS)
    _patch_pdf_health_cli(monkeypatch, 200, b"%PDF-1.4 fake bytes")

    runner = CliRunner()
    res = runner.invoke(ops_app, ["pdf-health", "--manifest", str(manifest_path)])

    assert res.exit_code == 0
    assert "pdf-health.ok" in res.stdout


def test_cli_pdf_health_exits_one_on_403(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Akamai 403 -> exit 1, stderr/stdout mentions ``pdf-health.fail`` and 403."""
    from typer.testing import CliRunner

    from pursue_index.cli.ops_cli import ops_app

    manifest_path = _write_manifest(tmp_path, _MANIFEST_TWO_PDFS)
    _patch_pdf_health_cli(monkeypatch, 403, b"")

    runner = CliRunner()
    res = runner.invoke(ops_app, ["pdf-health", "--manifest", str(manifest_path)])

    assert res.exit_code == 1
    combined = res.stdout + (res.stderr or "")
    assert "pdf-health.fail" in combined
    assert "403" in combined


def test_cli_pdf_health_exits_one_on_transport_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transport error -> exit 1, error type leaks through to the CLI output."""
    from typer.testing import CliRunner

    from pursue_index.cli.ops_cli import ops_app

    manifest_path = _write_manifest(tmp_path, _MANIFEST_TWO_PDFS)

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        raise ConnectionError("name resolution failed")

    monkeypatch.setattr(pdf_health.csv_fetcher, "http_get", fake_get)

    runner = CliRunner()
    res = runner.invoke(ops_app, ["pdf-health", "--manifest", str(manifest_path)])

    assert res.exit_code == 1
    combined = res.stdout + (res.stderr or "")
    assert "pdf-health.fail" in combined
    assert "ConnectionError" in combined
