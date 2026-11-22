"""Every upstream fetch is bounded: size, redirects and hosts; a violation is a per-card failure."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_fetch  # noqa: E402

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, sha  # noqa: E402

HOSTS = frozenset({"www.war.gov"})
URL = "https://www.war.gov/a.pdf"


class _Resp:
    def __init__(self, status=200, headers=None, chunks=()):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.closed = False
        self.yielded = 0

    def raise_for_status(self) -> None: ...

    def iter_content(self, chunk_size: int = 0):
        for c in self._chunks:
            self.yielded += 1
            yield c

    def close(self) -> None:
        self.closed = True


def _serve(monkeypatch, routes: dict[str, _Resp]):
    """Replace curl's GET: each URL maps to one response; the request log is returned."""
    log: list[tuple[str, dict]] = []

    def fake_get(url, **kw):
        log.append((url, kw))
        return routes[url]

    monkeypatch.setattr(_r2_fetch.cffi_requests, "get", fake_get)
    return log


def _redirect(to: str, status: int = 302) -> _Resp:
    return _Resp(status, {"location": to})


# --- size ----------------------------------------------------------------------------


def test_a_body_over_the_cap_is_aborted_mid_stream(monkeypatch, tmp_path):
    resp = _Resp(chunks=[b"x" * 10, b"y" * 10, b"z" * 10])
    _serve(monkeypatch, {URL: resp})
    with pytest.raises(_r2_fetch.FetchLimitError, match="cap"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=15, allowed_hosts=HOSTS)
    assert resp.yielded == 2, "the stream stops at the chunk that crosses the cap"


def test_a_declared_length_over_the_cap_is_refused_before_any_byte(monkeypatch, tmp_path):
    resp = _Resp(headers={"content-length": "100"}, chunks=[b"x"])
    _serve(monkeypatch, {URL: resp})
    with pytest.raises(_r2_fetch.FetchLimitError):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=50, allowed_hosts=HOSTS)
    assert resp.yielded == 0


def test_a_body_exactly_at_the_cap_passes(monkeypatch, tmp_path):
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x" * 10])})
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)[1] == 10


def test_the_cap_is_twice_the_last_known_size_and_never_above_the_ceiling():
    assert _r2_fetch.byte_cap([{"byte_size": 1000}]) == 2000
    assert _r2_fetch.byte_cap([{"byte_size": _r2_fetch.MAX_ASSET_BYTES}]) == _r2_fetch.MAX_ASSET_BYTES
    assert _r2_fetch.byte_cap([]) == _r2_fetch.MAX_ASSET_BYTES
    assert _r2_fetch.byte_cap([{"byte_size": None}]) == _r2_fetch.MAX_ASSET_BYTES
    assert _r2_fetch.MAX_ASSET_BYTES == 2 * 1024**3


# --- redirects -----------------------------------------------------------------------


def test_five_redirects_are_followed(monkeypatch, tmp_path):
    routes = {URL: _redirect("https://www.war.gov/r1")}
    for i in range(1, 5):
        routes[f"https://www.war.gov/r{i}"] = _redirect(f"https://www.war.gov/r{i + 1}")
    routes["https://www.war.gov/r5"] = _Resp(chunks=[b"ok"])
    log = _serve(monkeypatch, routes)
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", allowed_hosts=HOSTS)[1] == 2
    assert all(kw["allow_redirects"] is False for _, kw in log)


def test_a_sixth_redirect_is_refused(monkeypatch, tmp_path):
    routes = {URL: _redirect("https://www.war.gov/r1")}
    for i in range(1, 6):
        routes[f"https://www.war.gov/r{i}"] = _redirect(f"https://www.war.gov/r{i + 1}")
    routes["https://www.war.gov/r6"] = _Resp(chunks=[b"never"])
    log = _serve(monkeypatch, routes)
    with pytest.raises(_r2_fetch.FetchLimitError, match="redirect"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", allowed_hosts=HOSTS)
    assert "https://www.war.gov/r6" not in [u for u, _ in log]


def test_a_relative_redirect_is_resolved_against_the_current_url(monkeypatch, tmp_path):
    log = _serve(monkeypatch, {URL: _redirect("/b.pdf"), "https://www.war.gov/b.pdf": _Resp(chunks=[b"k"])})
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", allowed_hosts=HOSTS)[1] == 1
    assert [u for u, _ in log][-1] == "https://www.war.gov/b.pdf"


# --- hosts ---------------------------------------------------------------------------


def test_the_original_url_must_be_on_the_allowlist(monkeypatch, tmp_path):
    log = _serve(monkeypatch, {"https://evil.example/a.pdf": _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError, match="host"):
        _r2_fetch.fetch_asset("https://evil.example/a.pdf", tmp_path / "a", allowed_hosts=HOSTS)
    assert log == []


def test_a_redirect_to_another_host_is_refused_before_it_is_requested(monkeypatch, tmp_path):
    log = _serve(monkeypatch, {URL: _redirect("https://evil.example/a.pdf"),
                               "https://evil.example/a.pdf": _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError, match="host"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", allowed_hosts=HOSTS)
    assert [u for u, _ in log] == [URL]


def test_host_comparison_ignores_case_and_port(monkeypatch, tmp_path):
    _serve(monkeypatch, {"https://WWW.War.GOV:443/a.pdf": _Resp(chunks=[b"x"])})
    assert _r2_fetch.fetch_asset("https://WWW.War.GOV:443/a.pdf", tmp_path / "a", allowed_hosts=HOSTS)[1] == 1


def test_the_allowlist_is_the_hosts_of_the_manifest_urls():
    got = _r2_fetch.allowed_hosts_from_urls([URL, "https://Cdn.Example.com/x", None, ""])
    assert got == {"www.war.gov", "cdn.example.com"}


def test_head_follows_the_same_limits(monkeypatch):
    calls: list[str] = []

    def fake_head(url, **kw):
        calls.append(url)
        return _redirect("https://evil.example/a.pdf") if url == URL else _Resp(headers={"content-length": "5"})

    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", fake_head)
    assert _r2_fetch.head_asset(URL, allowed_hosts=HOSTS) == (None, None, None)
    assert calls == [URL]


# --- per-card failure, never a crash ---------------------------------------------------


def _limit_failing_world(tmp_path, monkeypatch, exc):
    w = World(tmp_path, monkeypatch)
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    ok = w.add_card(2, body=NEW_BODY)

    def fetch(u, dest, **kw):
        if "c1." in str(u):
            raise exc
        Path(dest).write_bytes(NEW_BODY)
        return sha(NEW_BODY), len(NEW_BODY)

    from tests.unit.r2_verify_harness import r2

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    return w, cid, ok


def test_a_limit_violation_is_one_cards_failure_and_the_rest_still_run(tmp_path, monkeypatch, capsys):
    w, cid, ok = _limit_failing_world(tmp_path, monkeypatch, _r2_fetch.FetchLimitError("too big"))
    rc = w.run("--full-hash", "--max-bytes-per-run", "1000", "--run-record", str(w.record))
    out = capsys.readouterr()
    assert rc == 1, "a failed card means an incomplete weekly run"
    assert f"fetch fail {cid}" in out.out and "too big" in out.out
    assert [r["card_id"] for r in w.new_rows()] == [ok]


def test_main_hands_each_card_its_cap_and_the_manifest_hosts(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    w.add_card(2, body=NEW_BODY)
    seen: dict[str, dict] = {}
    from tests.unit.r2_verify_harness import r2

    def fetch(u, dest, **kw):
        seen[str(u)] = kw
        Path(dest).write_bytes(NEW_BODY)
        return sha(NEW_BODY), len(NEW_BODY)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    w.run()
    first, second = seen["https://www.war.gov/medialink/ufo/c1.pdf"], seen["https://www.war.gov/medialink/ufo/c2.pdf"]
    assert first["max_bytes"] == _r2_fetch.hard_ceiling([])
    assert second["max_bytes"] == _r2_fetch.hard_ceiling([])
    assert first["allowed_hosts"] == frozenset({"www.war.gov"})


# --- the hard ceiling scales with the asset's own known size ---------------
# The corpus already holds a 3.2 GB video; a fixed 2 GiB ceiling would fail it
# on every run. An asset with no known size keeps the 2 GiB ceiling.

def test_hard_ceiling_for_an_unknown_size_is_the_absolute_ceiling():
    assert _r2_fetch.hard_ceiling([]) == _r2_fetch.MAX_ASSET_BYTES
    assert _r2_fetch.hard_ceiling([{"byte_size": None}]) == _r2_fetch.MAX_ASSET_BYTES


def test_hard_ceiling_never_drops_below_the_absolute_ceiling():
    assert _r2_fetch.hard_ceiling([{"byte_size": 1000}]) == _r2_fetch.MAX_ASSET_BYTES


def test_a_known_asset_larger_than_the_absolute_ceiling_is_not_refused():
    known = 3_212_900_000  # the largest asset in the registry today
    ceiling = _r2_fetch.hard_ceiling([{"byte_size": known}])
    assert ceiling == known * _r2_fetch.HARD_GROWTH_FACTOR
    assert ceiling > known > _r2_fetch.MAX_ASSET_BYTES
    # the growth alert still fires at 2x, well below the hard ceiling
    assert _r2_fetch.byte_cap([{"byte_size": known}]) < ceiling


def test_every_registered_asset_fits_under_its_own_hard_ceiling():
    import json
    rows = [json.loads(line) for line in (Path(__file__).resolve().parents[2] / "data" / "asset-bytes-registry.jsonl").read_text().splitlines() if line.strip()]
    too_big = [r["card_id"] for r in rows if (r.get("byte_size") or 0) > _r2_fetch.hard_ceiling([r])]
    assert too_big == []
