"""Whether a ``http.<url>.*`` config URL applies to a fetch URL, by git's rules.

git (``urlmatch.c``) matches a config URL against the URL being fetched by
scheme (case-insensitive), then host (case-insensitive; ``*`` matches one
whole host label), then port (the scheme's default when absent), then path:
the config path must be a prefix of the fetch path ending at a ``/`` boundary
(case-sensitive). A config URL that names a user only matches a URL with that
user; this module treats it as applying anyway, and an unparseable config URL
too, because the caller refuses on a match and should fail closed.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from urllib.parse import SplitResult, unquote, urlsplit

__all__ = ["config_url_applies"]

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _port(parts: SplitResult) -> int | None:
    return parts.port or _DEFAULT_PORTS.get(parts.scheme.lower())


def _host_matches(pattern: str, host: str) -> bool:
    want, have = pattern.lower().split("."), host.lower().split(".")
    if len(want) != len(have):
        return False
    return all(w == h or ("*" in w and fnmatchcase(h, w)) for w, h in zip(want, have, strict=True))


def _path_matches(prefix: str, path: str) -> bool:
    prefix, path = unquote(prefix) or "/", unquote(path) or "/"
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")


def config_url_applies(config_url: str, target: str) -> bool:
    """True when git would apply ``http.<config_url>.*`` to a fetch of ``target``
    (or when ``config_url`` cannot be read as a URL)."""
    try:
        want, have = urlsplit(config_url.strip()), urlsplit(target)
        if not want.scheme or not want.hostname:
            return True
        return (want.scheme.lower() == have.scheme.lower()
                and _host_matches(want.hostname, have.hostname or "")
                and _port(want) == _port(have)
                and _path_matches(want.path, have.path))
    except ValueError:  # e.g. a non-numeric port
        return True
