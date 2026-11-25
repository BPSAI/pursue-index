"""The one strict URL parse, and the error a fetch raises when it breaks a bound."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Any, NamedTuple

_DEFAULT_PORTS = {"http": 80, "https": 443}


class FetchLimitError(Exception):
    """A fetch broke a bound: too large, too many redirects, or a host off the allowlist."""


class ParsedUrl(NamedTuple):
    """One URL, parsed once: what every check and the request itself go by."""

    scheme: str
    host: str
    port: int
    url: str  # canonical: lower-cased host without a trailing dot, same path and query


_URL_RE = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<authority>[^/?#]*)(?P<rest>.*)", re.S)
_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*(?=:)")
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def _clean_host(authority: str) -> str:
    """The host of ``authority`` when it parses cleanly, else ''. Used only to word a refusal."""
    host = authority.rpartition("@")[2]
    if ":" in host:
        host = host.rpartition(":")[0]
    host = host.lower().removesuffix(".")
    ok = host.isascii() and 0 < len(host) <= 253 and all(_LABEL_RE.fullmatch(lb) for lb in host.split("."))
    return host if ok else ""


def _without_userinfo(url: str) -> str:
    """``url`` with everything up to the last ``@`` of its authority removed, so a fingerprint
    never depends on a credential."""
    m = _URL_RE.match(url)
    if not m or "@" not in m["authority"]:
        return url
    return url[: m.start("authority")] + m["authority"].rpartition("@")[2] + m["rest"]


def _redacted(url: str) -> str:
    """The scheme, the host if it parsed cleanly (else ``<unparsed>``) and a short fingerprint:
    never userinfo, port, path, query, fragment or any other raw text."""
    fingerprint = hashlib.sha256(_without_userinfo(url).encode("utf-8", "replace")).hexdigest()[:12]
    m = None if "\\" in url or any(ord(c) <= 0x20 or ord(c) == 0x7F for c in url) else _URL_RE.fullmatch(url)
    scheme = _SCHEME_RE.match(url)
    shown_scheme = scheme[0].lower() if scheme and url[scheme.end() :].startswith("://") else "<none>"
    host = _clean_host(m["authority"]) if m else ""
    return f"{shown_scheme}://{host or '<unparsed>'} [{fingerprint}]"


def _refuse(url: str, why: str) -> FetchLimitError:
    return FetchLimitError(f"URL refused ({why}): {_redacted(url)}")


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


def _scheme_of(url: str) -> str:
    m = _SCHEME_RE.match(str(url))
    return m[0].lower() if m else ""
