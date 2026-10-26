"""The one validator for every URL the poll lane's PDF fetch may touch.

Page-count fetching takes URLs from the upstream CSV and from ``field_changes``
values, so a hostile or merely mangled row must not be able to point the
fetch at an internal address. A URL passes only when it is https, on the
official host, with no userinfo, on the default port, and not a literal IP.
It is applied to the first URL and to every redirect hop.
"""

from __future__ import annotations

from urllib.parse import urlsplit

__all__ = ["ALLOWED_PDF_HOSTS", "is_allowed_pdf_url"]

ALLOWED_PDF_HOSTS = frozenset({"www.war.gov"})
_FORBIDDEN_CHARS = frozenset("\\ \t\r\n\x00")


def _clean(url: str) -> bool:
    return not any(ch in _FORBIDDEN_CHARS or ord(ch) < 0x20 for ch in url)


def is_allowed_pdf_url(url: object) -> bool:
    """True iff ``url`` may be fetched; never raises on malformed input."""
    if not isinstance(url, str) or not url or not _clean(url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.username is None
        and parts.password is None
        and port in (None, 443)
        and parts.hostname in ALLOWED_PDF_HOSTS
    )
