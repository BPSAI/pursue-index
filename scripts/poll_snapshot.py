"""Offline snapshot + diff generator CLI.

Thin shell over ``pursue_index.scrape.poll_snapshot.generate_snapshot_diff``
for the credential-free poll lane. Reads already-fetched CSV bytes from a
file (or stdin), parses them, rotates the prior ``latest.json`` into the
snapshot mirror, writes the new ``snapshots/<sha>.json``, and prints a
stable kv summary of the diff.

All testable logic lives in the scrape package; this file exists so the
GH Actions runner can invoke it directly without the full ``pursue`` CLI
(typer + click + rich) installed — see ``requirements-poll.in``. The CSV
bytes are passed in, and it touches no R2 / credential. Its one network use
is ``--summary-out``: each new PDF is fetched (public URL, the PDF health
check's Chrome-impersonation client) into a temp dir to count its pages for
the per-page estimate; a failed fetch falls back per card, never fails the run.

Mirrors the ``src/``-injection pattern in ``scripts/pdf_health_check.py``.

Output (stable kv format the workflow log can grep):

* ``poll-snapshot.ok added=<n> removed=<n> field_changes=<n> new_columns=<csv>``

Exit 3 (nothing written to ``--diff-out``) when a diff record for the sha
already exists and the recompute disagrees: records are append-only.

When ``--diff-out`` is given, also writes a diff+verdict JSON artifact
(verdict + added/removed/field-change counts + new column names, keyed by
new_sha) — the snapshot job commits this and the gh-comment step reads the
verdict back onto the ``tranche-detected`` issue.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import json
import tempfile

# Make ``src/`` importable when running as ``python scripts/poll_snapshot.py``
# from the repo root (no install needed in the GH Actions runner).
from pursue_index.paths import repo_root

_REPO_ROOT = repo_root()

from pursue_index.release.rates import read_judge_rate
from pursue_index.scrape.classify_tranche import (
    build_verdict_artifact,
    render_verdict_summary,
)
from pursue_index.scrape.pdf_pages import fetch_and_count, page_targets
from pursue_index.scrape.poll_snapshot import (
    generate_snapshot_diff,
)

DEFAULT_LATEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
# Diffs live in a SIBLING dir of snapshots/, never inside it: the ingest
# snapshot-locator globs snapshots/<sha>*.json and the index rebuild globs
# snapshots/*.json — a diff artifact inside snapshots/ would collide with both.
DEFAULT_DIFF_OUT = _REPO_ROOT / "data" / "manifests" / "diffs" / "latest-diff.json"
DEFAULT_QC_BUNDLE = _REPO_ROOT / "web" / "public" / "data" / "clean-qc-bundle.json"
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
        help="Write the diff+verdict JSON artifact here. Skipped if omitted.",
    )
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=None,
        help="Write the rendered verdict markdown here. Skipped if omitted.",
    )
    parser.add_argument(
        "--qc-bundle",
        type=Path,
        default=DEFAULT_QC_BUNDLE,
        help="Committed clean-qc bundle; source of the judge's metered per-page rate.",
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

    if args.diff_out is not None and args.diff_out.exists():
        # A record already exists: this sha was processed before. Recompute
        # against throwaway mirrors so neither outcome touches the real
        # snapshots/ or index.json (#157, append-only).
        with tempfile.TemporaryDirectory() as scratch:
            mirror_dirs = {
                "canonical_dir": Path(scratch) / "canonical",
                "public_dir": Path(scratch) / "public",
            }
            result = generate_snapshot_diff(
                raw, source_url=args.source_url, latest_path=args.latest, **mirror_dirs
            )
    else:
        result = generate_snapshot_diff(
            raw, source_url=args.source_url, latest_path=args.latest, **mirror_dirs
        )
    new_sha = build_manifest_sha(raw, args.source_url)
    artifact = build_verdict_artifact(result, new_sha=new_sha)
    if args.diff_out is not None and not _write_diff_record(args.diff_out, artifact):
        return 3
    if args.summary_out is not None:
        _write_summary(args.summary_out, result, new_sha, args.qc_bundle)
    cols = ",".join(result.new_columns) or "-"
    print(
        f"poll-snapshot.ok added={len(result.added)} "
        f"removed={len(result.removed)} "
        f"field_changes={len(result.field_changes)} "
        f"new_columns={cols} verdict={artifact['verdict']}",
        flush=True,
    )
    return 0


def _write_summary(path: Path, result, new_sha: str, qc_bundle: Path) -> None:
    """Render the verdict + tranche-ready block, priced per page.

    Each new PDF is fetched (credential-free, Chrome-impersonated) into a
    temp dir that lives only for this block, and its pages counted.
    """
    judge = read_judge_rate(qc_bundle)
    with fetch_and_count(page_targets(result)) as fetched:
        text = render_verdict_summary(
            result, tranche=new_sha, page_counts=fetched.page_counts,
            fallback_card_ids=fetched.fallback_card_ids, judge=judge,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_diff_record(path: Path, artifact: dict) -> bool:
    """Write ``artifact`` to ``path`` unless a record is already there.

    Diff records are append-only (#157): an existing record is the diff
    as first observed, and a recompute against a later ``latest.json``
    would silently rewrite history. An equal recompute is a no-op; a
    disagreeing one is reported and returns ``False`` without writing.
    """
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored = None
        if stored == artifact:
            print(f"poll-snapshot.diff-record unchanged path={path}", flush=True)
            return True
        print(
            f"poll-snapshot.error diff records are append-only: {path} already"
            " exists and the recomputed diff disagrees with it; refusing to"
            f" rewrite.\n  stored:     {json.dumps(stored, sort_keys=True)}"
            f"\n  recomputed: {json.dumps(artifact, sort_keys=True)}",
            file=sys.stderr,
            flush=True,
        )
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return True


def build_manifest_sha(raw_csv: bytes, source_url: str) -> str:
    """The new manifest's ``csv_sha256`` — keys the verdict artifact to the
    detected change, matching ``snapshots/<new_sha>.json``."""
    from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv

    return build_manifest(raw_csv, parse_csv(raw_csv), source_url).csv_sha256


if __name__ == "__main__":
    raise SystemExit(main())
