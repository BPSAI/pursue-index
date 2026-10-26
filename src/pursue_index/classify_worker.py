"""Child process for ``classify_isolated``: classify one pair under RLIMIT_AS.

``python -m pursue_index.classify_worker OLD NEW --memory-bytes N`` prints the
verdict on stdout and exits 0; the parent treats anything else as
``content-changed``.
"""

from __future__ import annotations

import resource
import sys
from pathlib import Path


def apply_memory_limit(nbytes: int) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))


def main(argv: list[str]) -> int:
    old, new = Path(argv[1]), Path(argv[2])
    apply_memory_limit(int(argv[argv.index("--memory-bytes") + 1]))
    from pursue_index.tranche_bytes import classify_bytes  # after the limit is set

    print(classify_bytes(old, new, isolated=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
