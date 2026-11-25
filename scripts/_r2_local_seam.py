"""Test-only seam for the upstream fetch: lets a local-server test fetch plain http from a
loopback address.

It is a context variable, not a module global, so it is on only inside
``allow_local_for_tests()``, which a test fixture enters, and can never be left switched on for
production code.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_ALLOW_LOCAL: ContextVar[bool] = ContextVar("allow_local_for_tests", default=False)


@contextmanager
def allow_local_for_tests() -> Iterator[None]:
    """Allow plain http and loopback addresses for the duration of the block (tests only)."""
    token = _ALLOW_LOCAL.set(True)
    try:
        yield
    finally:
        _ALLOW_LOCAL.reset(token)
