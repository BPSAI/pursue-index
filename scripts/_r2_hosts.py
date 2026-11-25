"""Where an upstream fetch may go: the host allowlist and the redirect rules."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import sys
from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}
# libcurl's CURLOPT_RESOLVE (curl_cffi's CurlOpt.RESOLVE), inlined like the other option numbers.
CURLOPT_RESOLVE = 10203

# Test-only seam (see _r2_local_seam): on only inside ``allow_local_for_tests()``.
from _r2_local_seam import _ALLOW_LOCAL, allow_local_for_tests  # noqa: F401


class FetchLimitError(Exception):
    """A fetch broke a bound: too large, too many redirects, or a host off the allowlist."""


class ApprovedHostsError(Exception):
    """The approved-host list is missing or malformed; the run must not guess."""


class ParsedUrl(NamedTuple):
    """One URL, parsed once: what every check and the request itself go by."""

    scheme: str
    host: str
    port: int
    url: str  # canonical: lower-cased host without a trailing dot, same path and query


_URL_RE = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<authority>[^/?#]*)(?P<rest>.*)", re.S)
_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*(?=:)")
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def _refuse(url: str, why: str) -> FetchLimitError:
    return FetchLimitError(f"URL refused ({why}): {url[:80]!r}")


def parse_url(url: Any) -> ParsedUrl:
    """The one strict parse. ``urlsplit`` and curl can disagree on the host of an odd URL, so a
    URL that could be read two ways is refused rather than interpreted: userinfo, a backslash,
    whitespace or control characters, a percent sign or non-ASCII character in the host, an
    empty host, a bad port, an IPv6 literal, and an IPv4 form other than four plain decimals."""
    text = str(url)
    if "\\" in text or any(ord(c) <= 0x20 or ord(c) == 0x7F for c in text):
        raise _refuse(text, "backslash, space or control character")
    m = _URL_RE.fullmatch(text)
    if m is None:
        raise _refuse(text, "no scheme and host")
    scheme, authority, rest = m["scheme"].lower(), m["authority"], m["rest"]
    if "@" in authority:
        raise _refuse(text, "userinfo")
    host, sep, port_text = authority.rpartition(":") if ":" in authority else (authority, "", "")
    if sep and not (port_text.isascii() and port_text.isdigit() and 1 <= int(port_text) <= 65535):
        raise _refuse(text, "port")
    port = int(port_text) if sep else _DEFAULT_PORTS.get(scheme, 443)
    host = host.lower().removesuffix(".")
    if not host.isascii() or not host or len(host) > 253:
        raise _refuse(text, "host")
    labels = host.split(".")
    if not all(_LABEL_RE.fullmatch(label) for label in labels):
        raise _refuse(text, "host")
    if labels[-1].isdigit() or labels[-1].startswith("0x") or all(lb.isdigit() for lb in labels):
        try:
            if len(labels) != 4 or str(ipaddress.IPv4Address(host)) != host:
                raise ValueError(host)
        except ValueError as exc:
            raise _refuse(text, "numeric host") from exc
    shown = host if port == _DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
    return ParsedUrl(scheme, host, port, f"{scheme}://{shown}{rest}")


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
    unlisted = sorted(allowed_hosts_from_urls([card.asset_url]) - set(approved))
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
    through the test seam."""
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


def _scheme_of(url: str) -> str:
    m = _SCHEME_RE.match(str(url))
    return m[0].lower() if m else ""


def check_hop(current: str, target: str) -> None:
    """A redirect stays on https (an http to https upgrade is the one scheme change allowed),
    and stays on the port it came from (or the default)."""
    nxt = _scheme_of(target)
    cur = _scheme_of(current)
    if nxt not in _DEFAULT_PORTS or (cur == "https" and nxt != "https"):
        raise FetchLimitError(f"redirect to scheme {nxt!r} from {cur!r} is refused")
    new, old = parse_url(target), parse_url(current)
    if new.port not in (_DEFAULT_PORTS[nxt], old.port):
        raise FetchLimitError(f"redirect to port {new.port} is refused")


def type_change_line(card_id: str, prev: dict[str, Any], old: str, new: str, new_url: Any) -> str:
    """The warning for an asset whose file type changed along with its URL (not a drift failure)."""
    return (
        f"[r2-archive] TYPE CHANGE: {card_id} {old} -> {new} "
        f"({host_of(prev.get('asset_url'))} -> {host_of(new_url)})"
    )
