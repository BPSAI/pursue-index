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

# libcurl's CURLOPT_RESOLVE (curl_cffi's CurlOpt.RESOLVE), inlined like the other option numbers.
CURLOPT_RESOLVE = 10203

# Test-only seam (see _r2_local_seam): on only inside ``allow_local_for_tests()``.
from _r2_local_seam import _ALLOW_LOCAL, allow_local_for_tests  # noqa: F401
from _r2_url import _DEFAULT_PORTS, FetchLimitError, ParsedUrl, _scheme_of, parse_url


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
    print(f"[r2-archive] redirect: {_CARD.get()} {host_of(current)} -> {host_of(target)} ({status})")


class AnyHost:
    """Marker meaning "no host restriction"; it must be passed on purpose."""

    def __repr__(self) -> str:
        return "ANY_HOST"


ANY_HOST = AnyHost()


def host_of(url: Any) -> str:
    """The strictly parsed, normalized host of ``url``; empty when the URL is refused."""
    try:
        return parse_url(url).host
    except FetchLimitError:
        return ""


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


def unlisted_card_hosts(card: Any, approved: Collection[str], where: Any) -> bool:
    """True, after naming the card and its host on stderr, when the card's asset host is not
    on the approved list. That refuses this card's row only; the run goes on."""
    url = card.asset_url
    unlisted = sorted(allowed_hosts_from_urls([url]) - set(approved))
    if url and not host_of(url):
        unlisted = ["<refused url>"]  # fail closed: a URL the strict parse refuses is never listed
    if unlisted:
        print(
            f"[r2-archive] ERROR: manifest asset host(s) {', '.join(unlisted)} not listed in "
            f"{where} (card {str(card.card_id)[:40]!r} refused); add them there on purpose, "
            "in a reviewed change.",
            file=sys.stderr,
        )
    return bool(unlisted)


def _parsed(url: str | ParsedUrl) -> ParsedUrl:
    return url if isinstance(url, ParsedUrl) else parse_url(url)


def check_host(url: str | ParsedUrl, allowed_hosts: Collection[str] | AnyHost | None) -> None:
    """Refuse a host off ``allowed_hosts``. ``ANY_HOST`` means no allowlist restriction, not no URL
    validation: a string the strict parse refuses raises ``FetchLimitError`` with it too."""
    host = _parsed(url).host
    if allowed_hosts is ANY_HOST:
        return
    if allowed_hosts is None or host not in allowed_hosts:
        raise FetchLimitError(f"host {host or '(none)'!r} is not a manifest or approved asset host")


def check_scheme(url: str) -> None:
    """The URL a fetch starts from must be https (plain http only through the test seam)."""
    scheme = _scheme_of(url)
    if scheme != "https" and not (_ALLOW_LOCAL.get() and scheme == "http"):
        raise FetchLimitError(f"scheme {scheme or '(none)'!r} is refused: a fetch must start on https")


# Ranges ``is_global`` still lets through but a fetch must not reach: NAT64 and 6to4 embed an
# IPv4 address that the gateway then connects to, which could be an internal one.
_TRANSLATION_NETS = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("2002::/16"))


def _public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Globally routable only: ``is_global`` (so CGNAT, benchmarking, documentation and the other
    reserved ranges are out), minus the NAT64 and 6to4 translation prefixes."""
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if ip.version == 6 and any(ip in net for net in _TRANSLATION_NETS):
        return False
    return ip.is_global


def check_resolved(
    url: str | ParsedUrl, allowed_hosts: Collection[str] | AnyHost | None = None
) -> list[str]:
    """Refuse a URL whose host resolves to any address that is not globally routable.

    Every address the name resolves to must be public; a host that does not resolve is refused.
    Returns the checked addresses (de-duplicated, in answer order) for the caller to pin the
    connection to, so the request cannot resolve the name a second time to something else.
    Skipped, returning ``[]``, with ``ANY_HOST`` (the explicit no-restriction opt-out) and
    through the test seam. The URL is strictly parsed first even then: ``ANY_HOST`` lifts the
    allowlist, never the validation, so a URL the parse refuses raises ``FetchLimitError``."""
    parts = _parsed(url)
    if allowed_hosts is ANY_HOST or _ALLOW_LOCAL.get():
        return []
    host = parts.host
    try:
        infos = socket.getaddrinfo(host, parts.port)
    except (OSError, UnicodeError) as exc:
        raise FetchLimitError(f"host {host!r} could not be resolved: {exc}") from exc
    checked: list[str] = []
    for info in infos:
        addr = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as exc:
            raise FetchLimitError(f"host {host!r} resolved to an unreadable address") from exc
        if not _public(ip):
            raise FetchLimitError(f"host {host!r} resolves to a non-public address ({ip})")
        if addr not in checked:
            checked.append(addr)
    if not checked:
        raise FetchLimitError(f"host {host!r} could not be resolved")
    return checked


def pinned(kw: dict[str, Any], url: str | ParsedUrl, addresses: list[str]) -> dict[str, Any]:
    """``kw`` with curl told to connect to the addresses that passed the check.

    ``CURLOPT_RESOLVE`` only fixes where the name goes: TLS still validates the certificate
    against the host name. Nothing is pinned when the address check was skipped."""
    if not addresses:
        return kw
    options = dict(kw.get("curl_options") or {})
    parts = _parsed(url)
    shown = ",".join(f"[{a}]" if ":" in a else a for a in addresses)
    options[CURLOPT_RESOLVE] = [f"{parts.host}:{parts.port}:{shown}"]
    return {**kw, "curl_options": options}


def check_hop(current: str, target: str) -> None:
    """A redirect must stay on https (plain http only through the test seam) and on the port it
    came from, or the default. There is no http to https upgrade: a fetch starts on https."""
    scheme = _scheme_of(target)
    if scheme != "https" and not (_ALLOW_LOCAL.get() and scheme == "http"):
        raise FetchLimitError(f"redirect to scheme {scheme or '(none)'!r} is refused: https only")
    new, old = parse_url(target), parse_url(current)
    if new.port not in (_DEFAULT_PORTS[scheme], old.port):
        raise FetchLimitError(f"redirect to port {new.port} is refused")


def type_change_line(card_id: str, prev: dict[str, Any], old: str, new: str, new_url: Any) -> str:
    """The warning for an asset whose file type changed along with its URL (not a drift failure)."""
    return (
        f"[r2-archive] TYPE CHANGE: {card_id} {old} -> {new} "
        f"({host_of(prev.get('asset_url'))} -> {host_of(new_url)})"
    )
