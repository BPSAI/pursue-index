"""Verify-gates round 2: disk, scheme, resolved addresses, ceilings, the drift window,
encoded bodies and file-type changes on the upstream fetch path."""

from __future__ import annotations

import gzip
import hashlib
import http.server
import json
import socketserver
import sys
import threading
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_drift_scan  # noqa: E402
import _r2_fetch  # noqa: E402
import _r2_hosts  # noqa: E402
import _r2_run_state  # noqa: E402

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2, sha, url  # noqa: E402
from tests.unit.test_r2_fetch_bounds import HOSTS, URL, _redirect, _Resp, _serve  # noqa: E402

MIB = 1024**2
Usage = namedtuple("Usage", "total used free")


# --- 1. disk exhaustion ---------------------------------------------------------------


def test_max_bytes_is_a_required_argument(tmp_path):
    with pytest.raises(TypeError, match="max_bytes"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", allowed_hosts=HOSTS)  # type: ignore[call-arg]


def test_low_disk_is_refused_before_any_byte_is_read(monkeypatch, tmp_path, dns):
    resp = _Resp(chunks=[b"x"])
    log = _serve(monkeypatch, {URL: resp})
    monkeypatch.setattr(_r2_fetch.shutil, "disk_usage", lambda _p: Usage(10**12, 10**12, 1000))
    with pytest.raises(_r2_fetch.FetchLimitError, match="insufficient disk"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=1000, allowed_hosts=HOSTS)
    assert log == [] and resp.yielded == 0
    assert not (tmp_path / "a").exists()


def test_the_disk_check_needs_the_ceiling_plus_the_margin(monkeypatch, tmp_path, dns):
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    need = 1000 + _r2_fetch.DISK_MARGIN_BYTES
    seen = []

    def usage(path):
        seen.append(Path(path))
        return Usage(10**12, 0, need)

    monkeypatch.setattr(_r2_fetch.shutil, "disk_usage", usage)
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=1000, allowed_hosts=HOSTS)[1] == 1
    assert seen == [tmp_path]
    monkeypatch.setattr(_r2_fetch.shutil, "disk_usage", lambda _p: Usage(10**12, 0, need - 1))
    with pytest.raises(_r2_fetch.FetchLimitError, match="insufficient disk"):
        _r2_fetch.fetch_asset(URL, tmp_path / "b", max_bytes=1000, allowed_hosts=HOSTS)


def test_low_disk_is_one_cards_failure_naming_the_disk(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    cid = w.add_card(1, body=NEW_BODY)

    def fetch(u, dest, **kw):
        raise _r2_fetch.InsufficientDiskError(need=5, free=1)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    w.run()
    out = capsys.readouterr().out
    assert f"fetch fail {cid}" in out and "insufficient disk" in out and "fail=1" in out


def test_the_run_budget_caps_the_ceiling(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=OLD_BODY)
    w.add_card(2, body=NEW_BODY)
    seen: list[int] = []

    def fetch(u, dest, **kw):
        seen.append(kw["max_bytes"])
        body = w.bodies[str(u)]
        Path(dest).write_bytes(body)
        return sha(body), len(body)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    assert w.run("--full-hash", "--max-bytes-per-run", "1000", "--run-record", str(w.record)) == 0
    assert seen == [1000, 1000 - len(OLD_BODY)]


def test_without_a_run_budget_the_ceiling_is_the_assets_own(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=NEW_BODY)
    seen: list[int] = []

    def fetch(u, dest, **kw):
        seen.append(kw["max_bytes"])
        Path(dest).write_bytes(NEW_BODY)
        return sha(NEW_BODY), len(NEW_BODY)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    w.run()
    assert seen == [_r2_fetch.MAX_ASSET_BYTES]


def test_an_asset_that_outgrows_the_budget_left_fails_the_run_as_over_budget(
    tmp_path, monkeypatch, capsys
):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=NEW_BODY)

    def fetch(u, dest, **kw):
        raise _r2_fetch.FetchOverCapError(observed=kw["max_bytes"] + 1, cap=kw["max_bytes"], declared=True)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    assert w.run("--full-hash", "--max-bytes-per-run", "5", "--run-record", str(w.record)) == 1
    assert "byte budget" in capsys.readouterr().err and not w.record.exists()


# --- 2. scheme enforcement ------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["http://www.war.gov/a.pdf", "ftp://www.war.gov/a.pdf", "file://www.war.gov/etc/passwd",
            "gopher://www.war.gov/a", "//www.war.gov/a.pdf"],
)
def test_the_initial_url_must_be_https(monkeypatch, tmp_path, dns, bad):
    log = _serve(monkeypatch, {bad: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError, match="scheme"):
        _r2_fetch.fetch_asset(bad, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log == []


def test_head_refuses_a_non_https_initial_url(monkeypatch, dns):
    calls: list[str] = []
    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", lambda u, **k: calls.append(u))
    assert _r2_fetch.head_asset("http://www.war.gov/a.pdf", allowed_hosts=HOSTS) == (None, None, None)
    assert calls == []


@pytest.mark.parametrize("target", ["http://www.war.gov/a.pdf", "ftp://www.war.gov/a", "file:///etc/passwd"])
def test_a_downgrade_or_other_scheme_hop_is_refused(monkeypatch, tmp_path, dns, target):
    log = _serve(monkeypatch, {URL: _redirect(target)})
    with pytest.raises(_r2_fetch.FetchLimitError, match="scheme"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log and [u for u, _ in log] == [URL]


def test_an_http_to_https_upgrade_hop_is_allowed_and_logged(capsys):
    _r2_hosts.check_hop("http://www.war.gov/a.pdf", "https://www.war.gov/a.pdf")
    _r2_hosts.log_hop("http://www.war.gov/a.pdf", "https://www.war.gov/a.pdf", 301)
    out = capsys.readouterr().out
    assert "scheme upgrade" in out and "http -> https" in out and "www.war.gov" in out


def test_http_to_other_scheme_hop_is_refused():
    for target in ("ftp://www.war.gov/a", "gopher://www.war.gov/a"):
        with pytest.raises(_r2_hosts.FetchLimitError, match="scheme"):
            _r2_hosts.check_hop("http://www.war.gov/a.pdf", target)


# the real client, against a local server (explicit test-only seam for http + loopback)


class _Local(http.server.BaseHTTPRequestHandler):
    hits: ClassVar[list[str]] = []
    body = b"pursue-real-client-" * 4000

    def do_GET(self) -> None:
        type(self).hits.append(self.path)
        if self.path == "/gz":
            data = gzip.compress(type(self).body)
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *a: object) -> None:
        pass


@pytest.fixture()
def local():
    _Local.hits = []
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Local)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


LOCAL = frozenset({"127.0.0.1"})


def test_real_client_never_requests_an_http_url_without_the_test_seam(local, tmp_path):
    with pytest.raises(_r2_fetch.FetchLimitError, match="scheme"):
        _r2_fetch.fetch_asset(f"{local}/a.pdf", tmp_path / "a", max_bytes=10**6, allowed_hosts=LOCAL)
    assert _Local.hits == []


def test_real_client_refuses_loopback_without_the_test_seam(local, tmp_path, monkeypatch):
    # https URL to a loopback literal: refused on the resolved address, nothing is sent.
    port = local.rsplit(":", 1)[1]
    with pytest.raises(_r2_fetch.FetchLimitError, match=r"private|loopback|address"):
        _r2_fetch.fetch_asset(
            f"https://127.0.0.1:{port}/a.pdf", tmp_path / "a", max_bytes=10**6, allowed_hosts=LOCAL
        )
    assert _Local.hits == []


# --- 3. allowlist from the committed file; resolved addresses ---------------------------


def _approved(tmp_path, hosts):
    p = tmp_path / "approved.json"
    p.write_text(json.dumps({"comment": "c", "hosts": hosts}))
    return p


def test_main_allows_only_the_committed_approved_hosts(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=OLD_BODY)
    seen: dict = {}

    def fetch(u, dest, **kw):
        seen.update(kw)
        Path(dest).write_bytes(OLD_BODY)
        return sha(OLD_BODY), len(OLD_BODY)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    path = _approved(tmp_path, ["www.war.gov", "cdn.example.com"])
    assert w.run("--approved-hosts", str(path)) == 0
    assert seen["allowed_hosts"] == frozenset({"www.war.gov", "cdn.example.com"})


def test_a_manifest_host_missing_from_the_approved_list_stops_the_run(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=OLD_BODY)
    w.cards[0]["asset_url"] = "https://rogue.example.org/x.pdf"
    w.bodies["https://rogue.example.org/x.pdf"] = OLD_BODY
    assert w.run("--approved-hosts", str(_approved(tmp_path, ["www.war.gov"]))) == 1
    err = capsys.readouterr().err
    assert "rogue.example.org" in err and "approved" in err
    assert w.fetched == [] and w.headed == []


def test_the_default_approved_list_covers_the_committed_manifest():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "data" / "manifests" / "latest.json").read_text())
    approved = _r2_hosts.load_approved_hosts(root / "data" / "approved-asset-hosts.json")
    hosts = _r2_hosts.allowed_hosts_from_urls(c.get("asset_url") for c in manifest["cards"])
    assert hosts <= approved


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1", "::"],
)
def test_a_host_resolving_to_a_non_public_address_is_refused(monkeypatch, tmp_path, dns, ip):
    dns["www.war.gov"] = ip
    log = _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError, match=r"www\.war\.gov"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log == []


def test_one_private_answer_among_public_ones_refuses_the_host(monkeypatch, tmp_path):
    import socket

    def mixed(host, port=None, *a, **k):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed)
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)


def test_resolution_failure_refuses_the_request(monkeypatch, tmp_path):
    import socket

    def boom(*a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    log = _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError, match="resolve"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log == []


def test_every_hop_is_resolved_before_it_is_requested(monkeypatch, tmp_path, dns):
    dns["cdn.example.com"] = "10.1.2.3"
    log = _serve(monkeypatch, {URL: _redirect("https://cdn.example.com/a.pdf")})
    hosts = frozenset({"www.war.gov", "cdn.example.com"})
    with pytest.raises(_r2_fetch.FetchLimitError, match=r"cdn\.example\.com"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=hosts)
    assert [u for u, _ in log] == [URL]


def test_head_refuses_a_host_that_resolves_to_loopback(monkeypatch, dns):
    dns["www.war.gov"] = "127.0.0.1"
    calls: list[str] = []
    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", lambda u, **k: calls.append(u))
    assert _r2_fetch.head_asset(URL, allowed_hosts=HOSTS) == (None, None, None)
    assert calls == []


# --- 4. ceilings -----------------------------------------------------------------------


def test_a_known_small_asset_gets_ten_times_its_size_with_a_64_mib_floor():
    ceiling = _r2_fetch.hard_ceiling
    assert ceiling([{"byte_size": 1000}]) == 64 * MIB
    assert ceiling([{"byte_size": 10 * MIB}]) == 100 * MIB
    assert ceiling([{"byte_size": 3_212_900_000}]) == 32_129_000_000
    assert ceiling([]) == _r2_fetch.MAX_ASSET_BYTES
    assert ceiling([{"byte_size": None}]) == _r2_fetch.MAX_ASSET_BYTES


def test_the_growth_alert_stays_at_twice_the_known_size():
    assert _r2_fetch.byte_cap([{"byte_size": 1000}]) == 2000


# --- 5. the drift window skips rows the last passing gate covered ------------------------


def _row(cid, body, when, u=None, **kw):
    return {
        "card_id": cid, "asset_url": u or url(1), "asset_filename": "c.pdf", "byte_sha256": sha(body),
        "byte_size": len(body), "fetched_at": when.isoformat(), **kw,
    }


NOW = datetime.now(UTC)


def test_registry_drift_since_skips_the_gated_rows():
    rows = [_row("c1", OLD_BODY, NOW - timedelta(days=2)), _row("c1", NEW_BODY, NOW - timedelta(days=1))]
    registry = {"c1": rows}
    since = NOW - timedelta(days=3)
    assert r2.registry_drift_since(registry, since) == [("c1", sha(OLD_BODY), sha(NEW_BODY))]
    assert r2.registry_drift_since(registry, since, rows_after=[]) == []
    assert r2.registry_drift_since(registry, since, rows_after=rows[1:]) != []


def test_the_marker_carries_the_gated_row_count_and_the_next_gate_starts_after_it(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    flags = ["--fail-on-drift", "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    marker = tmp_path / "drift-gate-passes.jsonl"
    assert w.run(*flags) == 1, "undisposed drift fails the first gate"
    assert not marker.exists()
    # Suppose a later gate passed (the drift was dispositioned) having covered every row.
    w.rows = w.registry_rows()
    args = SimpleNamespace(registry=w.registry, gate_marker=marker, run_record=w.record)
    _r2_run_state.write_run_record(
        marker,
        {"schema": _r2_run_state.GATE_MARKER_SCHEMA, "completed_at": (NOW - timedelta(days=2)).isoformat(),
         "gated_rows": len(w.rows)},
    )
    assert _r2_drift_scan.gated_row_count(args) == len(w.rows)
    # The drift row is behind the marker's count: the next gate does not rescan it, and its own marker says so.
    assert w.run(*flags) == 0
    last = json.loads(marker.read_text().splitlines()[-1])
    assert last["gated_rows"] == len(w.registry_rows())


def test_a_new_row_after_the_gated_count_is_still_scanned(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    flags = ["--fail-on-drift", "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    marker = tmp_path / "drift-gate-passes.jsonl"
    _r2_run_state.write_run_record(
        marker, {"schema": _r2_run_state.GATE_MARKER_SCHEMA, "completed_at": (NOW - timedelta(days=2)).isoformat(),
                 "gated_rows": len(w.rows)}
    )
    assert w.run(*flags) == 1, "the row this run appended is past the gated count and is drift"


def test_a_missing_or_old_format_marker_falls_back_to_the_whole_window(tmp_path):
    args = SimpleNamespace(registry=tmp_path / "r.jsonl", gate_marker=tmp_path / "m.jsonl", run_record=tmp_path / "x")
    assert _r2_drift_scan.gated_row_count(args) is None
    _r2_run_state.write_run_record(args.gate_marker, {"completed_at": NOW.isoformat()})
    assert _r2_drift_scan.gated_row_count(args) is None
    _r2_run_state.write_run_record(args.gate_marker, {"completed_at": NOW.isoformat(), "gated_rows": "x"})
    assert _r2_drift_scan.gated_row_count(args) is None
    _r2_run_state.write_run_record(args.gate_marker, {"completed_at": NOW.isoformat(), "gated_rows": -3})
    assert _r2_drift_scan.gated_row_count(args) is None


def test_a_registry_shorter_than_the_gated_count_is_scanned_whole(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    flags = ["--fail-on-drift", "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    _r2_run_state.write_run_record(
        tmp_path / "drift-gate-passes.jsonl",
        {"schema": _r2_run_state.GATE_MARKER_SCHEMA, "completed_at": (NOW - timedelta(days=2)).isoformat(),
         "gated_rows": 10_000},
    )
    assert w.run(*flags) == 1


# --- 6. Content-Length against encoded bodies --------------------------------------------


def test_an_encoded_response_is_not_refused_on_its_compressed_length(monkeypatch, tmp_path, dns):
    resp = _Resp(headers={"content-length": "100", "content-encoding": "gzip"}, chunks=[b"x" * 40])
    _serve(monkeypatch, {URL: resp})
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=50, allowed_hosts=HOSTS)[1] == 40


def test_an_encoded_body_is_still_capped_on_its_decoded_bytes(monkeypatch, tmp_path, dns):
    resp = _Resp(headers={"content-length": "10", "content-encoding": "br"}, chunks=[b"x" * 40, b"y" * 40])
    _serve(monkeypatch, {URL: resp})
    with pytest.raises(_r2_fetch.FetchOverCapError) as exc:
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=50, allowed_hosts=HOSTS)
    assert not exc.value.declared


def test_an_identity_response_keeps_the_declared_length_check(monkeypatch, tmp_path, dns):
    resp = _Resp(headers={"content-length": "100", "content-encoding": "identity"}, chunks=[b"x"])
    _serve(monkeypatch, {URL: resp})
    with pytest.raises(_r2_fetch.FetchOverCapError) as exc:
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=50, allowed_hosts=HOSTS)
    assert exc.value.declared and resp.yielded == 0


def test_head_does_not_report_a_compressed_length_as_the_size(monkeypatch, dns):
    resp = _Resp(headers={"content-length": "7", "content-encoding": "gzip", "etag": '"e"'})
    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", lambda u, **k: resp)
    assert _r2_fetch.head_asset(URL, allowed_hosts=HOSTS) == (None, '"e"', None)


@pytest.fixture()
def seam(monkeypatch):
    monkeypatch.setattr(_r2_hosts, "TEST_ONLY_ALLOW_LOCAL", True)


def test_real_client_hashes_the_decoded_bytes_and_caps_them_as_decoded(local, seam, tmp_path):
    body = _Local.body
    dest = tmp_path / "a"
    sha_, size = _r2_fetch.fetch_asset(f"{local}/gz", dest, max_bytes=len(body), allowed_hosts=LOCAL)
    assert (sha_, size) == (hashlib.sha256(body).hexdigest(), len(body))
    assert dest.read_bytes() == body
    assert len(gzip.compress(body)) < len(body) // 4, "the declared length is the compressed one"
    with pytest.raises(_r2_fetch.FetchOverCapError):
        _r2_fetch.fetch_asset(f"{local}/gz", tmp_path / "b", max_bytes=len(body) - 1, allowed_hosts=LOCAL)


def test_real_client_fetches_loopback_http_through_the_test_seam(local, seam, tmp_path):
    assert _r2_fetch.fetch_asset(
        f"{local}/a.pdf", tmp_path / "a", max_bytes=10**6, allowed_hosts=LOCAL
    )[1] == len(_Local.body)


# --- 7. a file-type change is a warning ----------------------------------------------------


def test_a_changed_url_and_file_type_prints_a_type_change_warning(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    old_url = w.cards[0]["asset_url"]
    new_url = "https://www.war.gov/medialink/ufo/c1.mp4"
    w.cards[0].update(asset_url=new_url, asset_filename="c1.mp4", asset_type="VID")
    w.bodies[new_url] = NEW_BODY
    flags = ["--fail-on-drift", "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    assert w.run(*flags) == 0, "net-new under the per-asset rule: a warning, not drift"
    out = capsys.readouterr().out
    assert f"[r2-archive] TYPE CHANGE: {cid} pdf -> mp4 (www.war.gov -> www.war.gov)" in out
    assert old_url not in out


def test_a_same_type_move_is_not_warned(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY, head_matches_prior=False)
    new_url = "https://www.war.gov/elsewhere/c1.pdf"
    w.cards[0]["asset_url"] = new_url
    w.bodies[new_url] = OLD_BODY
    w.run()
    assert "TYPE CHANGE" not in capsys.readouterr().out


def test_a_second_asset_of_another_type_is_not_a_type_change(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    cid = w.add_card(1, prior=OLD_BODY, body=OLD_BODY, head_matches_prior=False)
    extra = "https://www.war.gov/medialink/ufo/c1.mp4"
    w.cards.append({**w.cards[0], "asset_url": extra, "asset_filename": "c1.mp4", "asset_type": "VID"})
    w.bodies[extra] = NEW_BODY
    w.run()
    assert "TYPE CHANGE" not in capsys.readouterr().out and cid


def test_the_scan_side_emits_the_same_warning_and_no_drift(capsys):
    old, new = _row("c1", OLD_BODY, NOW - timedelta(days=3)), _row(
        "c1", NEW_BODY, NOW - timedelta(days=1), u="https://cdn.example.com/c1.mp4", asset_filename="c1.mp4"
    )
    assert r2.registry_drift_since({"c1": [old, new]}, NOW - timedelta(days=2)) == []
    assert "[r2-archive] TYPE CHANGE: c1 pdf -> mp4 (www.war.gov -> cdn.example.com)" in capsys.readouterr().out


def test_the_scan_side_is_quiet_for_rows_before_the_window(capsys):
    old, new = _row("c1", OLD_BODY, NOW - timedelta(days=9)), _row(
        "c1", NEW_BODY, NOW - timedelta(days=8), u="https://www.war.gov/c1.mp4", asset_filename="c1.mp4"
    )
    r2.registry_drift_since({"c1": [old, new]}, NOW - timedelta(days=2))
    assert "TYPE CHANGE" not in capsys.readouterr().out
