"""Where an upstream fetch may go: the host allowlist and the redirect rules."""

from __future__ import annotations

import ipaddress
import json
import socket
import sys
from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}

# Test-only seam: lets a local-server test fetch plain http from a loopback address. Nothing
# in production sets it; a test turns it on explicitly with ``monkeypatch.setattr``.
TEST_ONLY_ALLOW_LOCAL = False


class FetchLimitError(Exception):
    """A fetch broke a bound: too large, too many redirects, or a host off the allowlist."""


class ApprovedHostsError(Exception):
    """The approved-host list is missing or malformed; the run must not guess."""


_CARD: ContextVar[str] = ContextVar("r2_current_card", default="-")


@contextmanager
def for_card(card_id: str) -> Iterator[None]:
    """Label the redirect log lines written inside this block with ``card_id``."""
    token = _CARD.set(card_id)
    try:
        yield
    finally:
        _CARD.reset(token)


def log_hop(current: str, target: str, status: int) -> None:
    """One line per redirect hop: hosts only, never a path or query string.

    An http to https upgrade says so on the same line."""
    upgrade = ""
    if urlsplit(current).scheme == "http" and urlsplit(target).scheme == "https":
        upgrade = " scheme upgrade http -> https"
    print(
        f"[r2-archive] redirect: {_CARD.get()} {host_of(current)} -> {host_of(target)} "
        f"({status}){upgrade}"
    )


class AnyHost:
    """Marker meaning "no host restriction"; it must be passed on purpose."""

    def __repr__(self) -> str:
        return "ANY_HOST"


ANY_HOST = AnyHost()


def host_of(url: Any) -> str:
    return (urlsplit(str(url)).hostname or "").lower()


def allowed_hosts_from_urls(urls: Iterable[Any]) -> frozenset[str]:
    """Lower-cased hostnames of ``urls``; the set every fetch and redirect must stay inside."""
    return frozenset(h for h in (host_of(u) for u in urls if u) if h)


def load_approved_hosts(path: Path) -> frozenset[str]:
    """Hosts a redirect may reach besides the manifest's own: ``{"comment": ..., "hosts": [...]}``.

    A missing file, bad JSON or a wrong shape raises ``ApprovedHostsError``."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApprovedHostsError(f"cannot read approved asset hosts {path}: {exc}") from exc
    hosts = data.get("hosts") if isinstance(data, dict) else None
    if not isinstance(hosts, list) or not all(isinstance(h, str) and h.strip() for h in hosts):
        raise ApprovedHostsError(f"{path}: 'hosts' must be a list of host names")
    return frozenset(h.strip().lower() for h in hosts)


def unlisted_hosts_error(cards: Iterable[Any], approved: Collection[str], where: Any) -> bool:
    """True, after naming them on stderr, when a card's asset host is not on the approved list."""
    unlisted = sorted(allowed_hosts_from_urls(c.asset_url for c in cards) - set(approved))
    if unlisted:
        print(
            f"[r2-archive] ERROR: manifest asset host(s) {', '.join(unlisted)} not listed in "
            f"{where}; add them there on purpose, in a reviewed change.",
            file=sys.stderr,
        )
    return bool(unlisted)


def check_host(url: str, allowed_hosts: Collection[str] | AnyHost | None) -> None:
    if allowed_hosts is ANY_HOST:
        return
    host = host_of(url)
    if allowed_hosts is None or host not in allowed_hosts:
        raise FetchLimitError(f"host {host or '(none)'!r} is not a manifest or approved asset host")


def check_scheme(url: str) -> None:
    """The URL a fetch starts from must be https (plain http only through the test seam)."""
    scheme = urlsplit(url).scheme
    if scheme != "https" and not (TEST_ONLY_ALLOW_LOCAL and scheme == "http"):
        raise FetchLimitError(f"scheme {scheme or '(none)'!r} is refused: a fetch must start on https")


def _public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified
        or ip.is_multicast or ip.is_reserved
    )


def check_resolved(url: str, allowed_hosts: Collection[str] | AnyHost | None = None) -> None:
    """Refuse a URL whose host resolves to a private, loopback, link-local or unspecified address.

    Every address the name resolves to must be public; a host that does not resolve is refused.
    Skipped with ``ANY_HOST`` (the explicit no-restriction opt-out) and through the test seam."""
    if allowed_hosts is ANY_HOST or TEST_ONLY_ALLOW_LOCAL:
        return
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    try:
        infos = socket.getaddrinfo(host, parts.port or _DEFAULT_PORTS.get(parts.scheme, 443))
    except (OSError, UnicodeError) as exc:
        raise FetchLimitError(f"host {host!r} could not be resolved: {exc}") from exc
    for info in infos:
        addr = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as exc:
            raise FetchLimitError(f"host {host!r} resolved to an unreadable address") from exc
        if not _public(ip):
            raise FetchLimitError(f"host {host!r} resolves to a non-public address ({ip})")
    if not infos:
        raise FetchLimitError(f"host {host!r} could not be resolved")


def _port(url: str) -> int | None:
    parts = urlsplit(url)
    return parts.port or _DEFAULT_PORTS.get(parts.scheme)


def check_hop(current: str, target: str) -> None:
    """A redirect stays on https (an http to https upgrade is the one scheme change allowed),
    and stays on the port it came from (or the default)."""
    cur, nxt = urlsplit(current), urlsplit(target)
    if nxt.scheme not in _DEFAULT_PORTS or (cur.scheme == "https" and nxt.scheme != "https"):
        raise FetchLimitError(f"redirect to scheme {nxt.scheme!r} from {cur.scheme!r} is refused")
    if _port(target) not in (_DEFAULT_PORTS[nxt.scheme], _port(current)):
        raise FetchLimitError(f"redirect to port {_port(target)} is refused")


def type_change_line(card_id: str, prev: dict[str, Any], old: str, new: str, new_url: Any) -> str:
    """The warning for an asset whose file type changed along with its URL (not a drift failure)."""
    return (
        f"[r2-archive] TYPE CHANGE: {card_id} {old} -> {new} "
        f"({host_of(prev.get('asset_url'))} -> {host_of(new_url)})"
    )
