"""Disk headroom for an upstream fetch: judged on the expected size, never the hard ceiling."""

from __future__ import annotations

import shutil
from pathlib import Path

from _r2_hosts import FetchLimitError

# Free space that must remain beyond a fetch's expected size, before it starts and while it runs.
DISK_MARGIN_BYTES = 256 * 1024**2
# What a fetch is expected to need when neither the response nor the registry says.
DEFAULT_EXPECTED_BYTES = 512 * 1024**2


class InsufficientDiskError(FetchLimitError):
    """The temp directory has no room for the fetch's expected size plus the safety margin."""

    def __init__(self, *, need: int, free: int) -> None:
        self.need, self.free = need, free
        super().__init__(f"insufficient disk: {free} bytes free, {need} needed (expected size + margin)")


def expected_bytes(known_size: int | None, max_bytes: int, growth_factor: int) -> int:
    """What a fetch should need: ``growth_factor`` times the last known size, else a modest
    default; never above ``max_bytes``."""
    if isinstance(known_size, int) and known_size > 0:
        return min(known_size * growth_factor, max_bytes)
    return min(DEFAULT_EXPECTED_BYTES, max_bytes)


def require_disk(dest: Path, expected: int) -> None:
    """Raise ``InsufficientDiskError`` unless ``expected`` plus the margin is free beside ``dest``."""
    free = shutil.disk_usage(dest.parent).free
    if free < expected + DISK_MARGIN_BYTES:
        raise InsufficientDiskError(need=expected + DISK_MARGIN_BYTES, free=free)
