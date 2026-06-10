"""Offline snapshot + diff generator CLI (Sprint 6, T6.1).

Thin shell over ``pursue_index.scrape.poll_snapshot.generate_snapshot_diff``
for the credential-free poll lane. Reads already-fetched CSV bytes from a
file (or stdin), parses them, rotates the prior ``latest.json`` into the
snapshot mirror, writes the new ``snapshots/<sha>.json``, and prints a
stable kv summary of the diff.

All testable logic lives in the scrape package; this file exists so the
GH Actions runner can invoke it directly without the full ``pursue`` CLI
(typer + click + rich) installed — see ``requirements-poll.in``. It makes
NO network call (bytes are passed in) and touches no R2 / credential.

Mirrors the ``src/``-injection pattern in ``scripts/pdf_health_check.py``.

Output (stable kv format the workflow log can grep):

* ``poll-snapshot.ok added=<n> removed=<n> field_changes=<n> new_columns=<csv>``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make ``src/`` importable when running as ``python scripts/poll_snapshot.py``
# from the repo root (no install needed in the GH Actions runner).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.scrape.poll_snapshot import generate_snapshot_diff  # noqa: E402

DEFAULT_LATEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_SOURCE_URL = "https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-data.csv"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Path to the already-fetched CSV bytes. Reads stdin if omitted.",
    )
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    args = parser.parse_args(argv)

    raw = args.csv.read_bytes() if args.csv else sys.stdin.buffer.read()

    result = generate_snapshot_diff(
        raw,
        source_url=args.source_url,
        latest_path=args.latest,
    )
    cols = ",".join(result.new_columns) or "-"
    print(
        f"poll-snapshot.ok added={len(result.added)} "
        f"removed={len(result.removed)} "
        f"field_changes={len(result.field_changes)} new_columns={cols}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
