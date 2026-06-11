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

When ``--diff-out`` is given, also writes a diff+verdict JSON artifact
(verdict + added/removed/field-change counts + new column names, keyed by
new_sha) — the snapshot job commits this and the gh-comment step reads the
verdict back onto the ``tranche-detected`` issue (T6.4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make ``src/`` importable when running as ``python scripts/poll_snapshot.py``
# from the repo root (no install needed in the GH Actions runner).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.scrape.classify_tranche import (  # noqa: E402
    build_verdict_artifact,
    render_verdict_summary,
)
from pursue_index.scrape.poll_snapshot import (  # noqa: E402
    generate_snapshot_diff,
)

DEFAULT_LATEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_DIFF_OUT = _REPO_ROOT / "data" / "manifests" / "snapshots" / "latest-diff.json"
DEFAULT_SOURCE_URL = "https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-data.csv"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Path to the already-fetched CSV bytes. Reads stdin if omitted.",
    )
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument(
        "--diff-out",
        type=Path,
        default=None,
        help="Write the diff+verdict JSON artifact here (T6.4). Skipped if omitted.",
    )
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=None,
        help="Write the rendered verdict markdown here (T6.4). Skipped if omitted.",
    )
    parser.add_argument("--canonical-dir", type=Path, default=None)
    parser.add_argument("--public-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    raw = args.csv.read_bytes() if args.csv else sys.stdin.buffer.read()

    mirror_dirs: dict[str, Path] = {}
    if args.canonical_dir is not None:
        mirror_dirs["canonical_dir"] = args.canonical_dir
    if args.public_dir is not None:
        mirror_dirs["public_dir"] = args.public_dir

    result = generate_snapshot_diff(
        raw,
        source_url=args.source_url,
        latest_path=args.latest,
        **mirror_dirs,
    )
    new_sha = build_manifest_sha(raw, args.source_url)
    artifact = build_verdict_artifact(result, new_sha=new_sha)
    if args.diff_out is not None:
        args.diff_out.parent.mkdir(parents=True, exist_ok=True)
        args.diff_out.write_text(
            json.dumps(artifact, indent=2) + "\n", encoding="utf-8"
        )
    if args.summary_out is not None:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            render_verdict_summary(result), encoding="utf-8"
        )
    cols = ",".join(result.new_columns) or "-"
    print(
        f"poll-snapshot.ok added={len(result.added)} "
        f"removed={len(result.removed)} "
        f"field_changes={len(result.field_changes)} "
        f"new_columns={cols} verdict={artifact['verdict']}",
        flush=True,
    )
    return 0


def build_manifest_sha(raw_csv: bytes, source_url: str) -> str:
    """The new manifest's ``csv_sha256`` — keys the verdict artifact to the
    detected change, matching ``snapshots/<new_sha>.json``."""
    from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv

    return build_manifest(raw_csv, parse_csv(raw_csv), source_url).csv_sha256


if __name__ == "__main__":
    raise SystemExit(main())
