"""Where an upstream fetch may go: the host allowlist and the redirect rules."""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


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
    """One line per redirect hop: hosts only, never a path or query string."""
    print(
        f"[r2-archive] redirect: {_CARD.get()} {host_of(current)} -> {host_of(target)} ({status})"
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


def check_host(url: str, allowed_hosts: Collection[str] | AnyHost | None) -> None:
    if allowed_hosts is ANY_HOST:
        return
    host = host_of(url)
    if allowed_hosts is None or host not in allowed_hosts:
        raise FetchLimitError(f"host {host or '(none)'!r} is not a manifest or approved asset host")


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
