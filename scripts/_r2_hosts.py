"""Where an upstream fetch may go: the host allowlist and the redirect rules."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


class FetchLimitError(Exception):
    """A fetch broke a bound: too large, too many redirects, or a host off the allowlist."""


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


def check_host(url: str, allowed_hosts: Collection[str] | AnyHost | None) -> None:
    if allowed_hosts is ANY_HOST:
        return
    host = host_of(url)
    if allowed_hosts is None or host not in allowed_hosts:
        raise FetchLimitError(f"host {host or '(none)'!r} is not one of the manifest's asset hosts")


def _port(url: str) -> int | None:
    parts = urlsplit(url)
    return parts.port or _DEFAULT_PORTS.get(parts.scheme)


def check_hop(current: str, target: str) -> None:
    """A redirect never leaves https, and stays on the port it came from (or the default)."""
    cur, nxt = urlsplit(current), urlsplit(target)
    if nxt.scheme not in _DEFAULT_PORTS or (cur.scheme == "https" and nxt.scheme != "https"):
        raise FetchLimitError(f"redirect to scheme {nxt.scheme!r} from {cur.scheme!r} is refused")
    if _port(target) not in (_DEFAULT_PORTS[nxt.scheme], _port(current)):
        raise FetchLimitError(f"redirect to port {_port(target)} is refused")
