"""Lightweight poll for upstream PURSUE CSV changes.

Driven by ``.github/workflows/poll-pursue.yml`` on a 6h cron (Layer 1
of the two-layer auto-poll architecture; the workflow YAML is the
canonical specification). Fetches the upstream CSV via
``pursue_index.scrape.csv_fetcher`` (same curl_cffi + Chrome-TLS
path the CLI uses, so the Akamai bypass is exercised), hashes the
bytes, and compares to the last-known sha stored in
``data/last-known-csv-sha.txt`` (with ``data/manifests/latest.json#csv_sha256``
as fallback when the .txt is missing — keeps the two truth sources in
sync if the operator ran ``pursue scrape run`` manually).

Result variants live in ``_poll_results.py``; ``$GITHUB_OUTPUT``
serialization lives in ``_poll_gh_io.py``. Exit codes:

* unchanged -> 0, status=unchanged
* changed   -> 0, status=changed (commit + tranche-detected issue)
* benign    -> 0, status=benign (commit; encoding-only, no issue)
* pending   -> 0, status=pending (new sha seen once; guard state committed)
* stale     -> 0, status=stale (stale cache edge; nothing committed)
* failed    -> 1, status=failed (tranche-poll-failure issue)

The stale-edge guard (#157, ``_poll_guard.py``) keeps its history in
``data/poll-state.json`` beside the sha file.

Heavy ingest is operator-attended by design. Run manually:

    python scripts/poll_pursue.py [--state ...] [--manifest ...]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

# Make ``src/`` importable when running as ``python scripts/poll_pursue.py``
# from the repo root (no install needed in the GH Actions runner).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Make sibling helper module importable in the same way (scripts/ is not
# a package, so a relative import would fail).
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _poll_gh_io import (  # noqa: E402
    changed_issue_body,
    emit_gh_outputs,
    emit_step_summary,
    failed_issue_body,
    guarded_summary,
    truncate_error,
)
from _poll_guard import (  # noqa: E402
    GuardState,
    encoding_only_vs_archive,
    load_guard,
    save_guard,
)
from _poll_results import (  # noqa: E402
    Benign,
    Changed,
    Failed,
    Pending,
    PollResult,
    Stale,
    Unchanged,
)
from _poll_sha_state import resolve_old_sha, write_state  # noqa: E402

from pursue_index.scrape.csv_fetcher import fetch_raw_csv  # noqa: E402

DEFAULT_STATE_PATH = _REPO_ROOT / "data" / "last-known-csv-sha.txt"
DEFAULT_MANIFEST_PATH = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_CSV_ARCHIVE_DIR = _REPO_ROOT / "data" / "raw" / "csv"
GUARD_STATE_NAME = "poll-state.json"


def sha256_hex(body: bytes) -> str:
    """SHA-256 of the raw bytes, hex-encoded. Pure, deterministic."""
    return hashlib.sha256(body).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _failed(exc_or_msg: BaseException | str, ts: str) -> Failed:
    """Build a Failed result with truncated, sanitized error text."""
    if isinstance(exc_or_msg, BaseException):
        exc_type = type(exc_or_msg).__name__
        raw = f"{exc_type}: {exc_or_msg}"
    else:
        exc_type = "EmptyBody"
        raw = exc_or_msg
    err = truncate_error(raw)
    return Failed(
        error=err,
        fetched_at=ts,
        issue_body=failed_issue_body(err, ts),
        extra={"exception_type": exc_type},
    )


def _fetch_or_failed(ts: str) -> bytes | Failed:
    """Run the upstream fetch, returning the body or a Failed result.

    ``KeyboardInterrupt`` and ``SystemExit`` propagate (they are not
    poll failures and shouldn't open a real GitHub issue).
    """
    try:
        return fetch_raw_csv()
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 — surface any transport failure
        return _failed(exc, ts)


def _archive_csv_bytes(body: bytes, sha: str, archive_dir: Path) -> Path:
    """Write the fetched CSV bytes to ``<archive_dir>/<sha>.csv``.

    Content-addressed by sha, so this is idempotent: a future poll on
    an unchanged CSV will hit the same path and find the file already
    exists. Returns the path either way so the caller can log it.

    Why this exists: the poll already has the bytes in memory (it has
    to, to compute the hash). Without this step the bytes are
    discarded after the hash is recorded, and a transient upstream
    state shorter than the gap between attended scrapes (the
    f07601ebed0f tranche on 2026-05-11, ~5 hours between detection at
    18:40Z and the next operator-attended scrape at 23:35Z) goes
    permanently unrecoverable. Saving bytes inline at fetch time
    closes that integrity gap with one filesystem write per poll.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{sha}.csv"
    if not path.exists():
        path.write_bytes(body)
    return path


def poll(
    state_path: Path,
    manifest_path: Path | None = DEFAULT_MANIFEST_PATH,
    csv_archive_dir: Path | None = None,
    guard_path: Path | None = None,
) -> PollResult:
    """Fetch upstream, compare to ``state_path``, return a result.

    Does NOT mutate ``state_path`` or the guard file, and discards the
    guard-state update (``poll_guarded`` returns it; ``main`` persists it).
    Not a single request: a first sighting of a new sha is re-fetched once
    to confirm it.
    """
    return poll_guarded(state_path, manifest_path, csv_archive_dir, guard_path)[0]


def poll_guarded(
    state_path: Path,
    manifest_path: Path | None = DEFAULT_MANIFEST_PATH,
    csv_archive_dir: Path | None = None,
    guard_path: Path | None = None,
) -> tuple[PollResult, GuardState | None]:
    """``poll`` plus the guard state to persist (``None``: write nothing).

    ``manifest_path=None`` disables the manifest fallback (test-only);
    ``guard_path`` defaults to ``poll-state.json`` beside ``state_path``.

    Side effect: when ``csv_archive_dir`` is set (the default), the
    fetched bytes are written to ``<dir>/<sha>.csv`` content-addressed
    and idempotent. This is the byte-preservation guarantee — without
    it we could only ever know the sha changed, not what the changed
    bytes looked like.
    """
    ts = _now_iso()
    old_sha = resolve_old_sha(state_path, manifest_path)
    guard_path = guard_path or state_path.with_name(GUARD_STATE_NAME)
    # Load before fetching: a missing guard is seeded from the archive as
    # it was before this poll wrote the fetched bytes into it.
    guard = load_guard(guard_path, old_sha, csv_archive_dir)

    fetched = _fetch_body(ts, csv_archive_dir)
    if isinstance(fetched, Failed):
        return fetched, None
    body, new_sha, last_modified = fetched

    if not old_sha:
        guard.promote(new_sha, last_modified)
        return _changed(old_sha, new_sha, ts), guard

    seen_kind = guard.classify(new_sha, last_modified)
    if seen_kind == "current":
        learned = guard.learn_last_modified(last_modified)
        return Unchanged(sha=new_sha), guard if learned else None
    if seen_kind == "stale":
        return Stale(sha=new_sha, current_sha=old_sha, last_modified=last_modified), None

    guard.observe(new_sha)
    if guard.pending_sha != new_sha:
        refetch = _fetch_body(ts, csv_archive_dir)
        again = None if isinstance(refetch, Failed) else refetch[1:]
        if not guard.confirm_by_refetch(new_sha, last_modified, again, ts):
            return Pending(sha=guard.pending_sha or new_sha, current_sha=old_sha, fetched_at=ts), guard

    guard.promote(new_sha, last_modified)
    if encoding_only_vs_archive(csv_archive_dir, old_sha, body):
        return Benign(old_sha=old_sha, new_sha=new_sha, fetched_at=ts), guard
    return _changed(old_sha, new_sha, ts), guard


def _fetch_body(ts: str, csv_archive_dir: Path | None) -> tuple[bytes, str, str | None] | Failed:
    """Fetch, reject an empty body, hash, and archive the bytes.

    Archive BEFORE branching on the outcome. Idempotent — same sha means
    same path, write skips if file exists. We archive even on Unchanged
    so that on the very first poll after the operator runs a manual
    scrape (which doesn't currently archive to git-tracked storage), the
    bytes for the current upstream state land in the repo without waiting
    for the next CSV change.
    """
    body = _fetch_or_failed(ts)
    if isinstance(body, Failed):
        return body
    if not body:
        return _failed("fetch returned empty body", ts)
    sha = sha256_hex(body)
    if csv_archive_dir is not None:
        _archive_csv_bytes(body, sha, csv_archive_dir)
    return body, sha, getattr(body, "last_modified", None)


def _changed(old_sha: str, new_sha: str, ts: str) -> Changed:
    boot = old_sha == ""
    body = changed_issue_body(old_sha, new_sha, ts, boot)
    return Changed(old_sha=old_sha, new_sha=new_sha, fetched_at=ts, is_bootstrap=boot, issue_body=body)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="Path to the last-known-sha file.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Path to the latest manifest (used as fallback sha source).",
    )
    parser.add_argument(
        "--csv-archive-dir",
        type=Path,
        default=DEFAULT_CSV_ARCHIVE_DIR,
        help=(
            "Directory to write each fetched CSV body to, named "
            "<sha>.csv. Content-addressed so re-fetches are idempotent. "
            "Default is data/raw/csv/ in the repo root."
        ),
    )
    parser.add_argument(
        "--guard-state",
        type=Path,
        default=None,
        help=(
            "Stale-edge guard state (seen shas, current Last-Modified, "
            f"pending sha). Default: {GUARD_STATE_NAME} beside --state."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    state: Path = args.state
    guard_path: Path = args.guard_state or state.with_name(GUARD_STATE_NAME)

    result, guard = poll_guarded(
        state,
        manifest_path=args.manifest,
        csv_archive_dir=args.csv_archive_dir,
        guard_path=guard_path,
    )
    if guard is not None:
        save_guard(guard_path, guard)

    if isinstance(result, (Changed, Benign)):
        write_state(state, result.new_sha, result.fetched_at)
    if isinstance(result, Changed):
        print(
            f"changed: {result.old_sha or '(bootstrap)'} -> {result.new_sha}",
            flush=True,
        )
        emit_gh_outputs(result)
        return 0
    if isinstance(result, Unchanged):
        print(f"unchanged: {result.sha}", flush=True)
        emit_gh_outputs(result)
        return 0
    summary = guarded_summary(result)
    if summary is not None:
        print(summary, flush=True)
        emit_step_summary(summary)
        emit_gh_outputs(result)
        return 0
    # Failed
    print(f"failed: {result.error}", file=sys.stderr, flush=True)
    emit_gh_outputs(result)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
