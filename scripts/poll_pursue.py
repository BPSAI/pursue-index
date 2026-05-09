"""Lightweight poll for upstream PURSUE CSV changes.

Driven by ``.github/workflows/poll-pursue.yml`` on a 6h cron (Layer 1
of the two-layer architecture in
``.paircoder/plans/auto-poll-tranches.md``). Fetches the upstream CSV
via ``pursue_index.scrape.csv_fetcher`` (same curl_cffi + Chrome-TLS
path the CLI uses, so the Akamai bypass is exercised), hashes the
bytes, and compares to the last-known sha stored in
``data/last-known-csv-sha.txt`` (with ``data/manifests/latest.json#csv_sha256``
as fallback when the .txt is missing — keeps the two truth sources in
sync if the operator ran ``pursue scrape run`` manually).

Result variants live in ``_poll_results.py``; ``$GITHUB_OUTPUT``
serialization lives in ``_poll_gh_io.py``. Exit codes:

* unchanged -> 0, status=unchanged
* changed   -> 0, status=changed (commit + tranche-detected issue)
* failed    -> 1, status=failed (tranche-poll-failure issue)

Heavy ingest is operator-attended by design. Run manually:

    python scripts/poll_pursue.py [--state ...] [--manifest ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
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

from pursue_index.scrape.csv_fetcher import fetch_raw_csv  # noqa: E402

from _poll_gh_io import (  # noqa: E402
    changed_issue_body,
    emit_gh_outputs,
    failed_issue_body,
    truncate_error,
)
from _poll_results import Changed, Failed, PollResult, Unchanged  # noqa: E402

DEFAULT_STATE_PATH = _REPO_ROOT / "data" / "last-known-csv-sha.txt"
DEFAULT_MANIFEST_PATH = _REPO_ROOT / "data" / "manifests" / "latest.json"


def sha256_hex(body: bytes) -> str:
    """SHA-256 of the raw bytes, hex-encoded. Pure, deterministic."""
    return hashlib.sha256(body).hexdigest()


def _read_last_known(state_path: Path) -> str:
    """Sha from the state file, or ``""`` if missing/empty.

    File format: ``{sha256}  {iso8601}\n`` (two spaces between fields).
    """
    if not state_path.exists():
        return ""
    text = state_path.read_text().strip()
    return text.split()[0] if text else ""


def _read_manifest_sha(manifest_path: Path) -> str:
    """``csv_sha256`` from ``manifest_path``, or ``""`` on miss/parse-error.

    Fallback used when the state file is missing — keeps the state
    file and the manifest in agreement so a manual ``pursue scrape
    run`` doesn't look like an upstream change on the next tick.
    """
    if not manifest_path.exists():
        return ""
    try:
        data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    sha = data.get("csv_sha256", "") if isinstance(data, dict) else ""
    return sha if isinstance(sha, str) else ""


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_old_sha(state_path: Path, manifest_path: Path | None) -> str:
    """State file wins; manifest is fallback; both missing => bootstrap."""
    sha = _read_last_known(state_path)
    if sha:
        return sha
    return _read_manifest_sha(manifest_path) if manifest_path is not None else ""


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
    poll failures and shouldn't open a real GitHub issue). (nayru P2 #7)
    """
    try:
        return fetch_raw_csv()
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 — surface any transport failure
        return _failed(exc, ts)


def poll(state_path: Path, manifest_path: Path | None = DEFAULT_MANIFEST_PATH) -> PollResult:
    """Fetch upstream, compare to ``state_path``, return a result.

    Pure observation: does NOT mutate ``state_path``. The caller decides
    whether to commit. ``manifest_path=None`` disables the manifest
    fallback (test-only).
    """
    ts = _now_iso()
    old_sha = _resolve_old_sha(state_path, manifest_path)

    body_or_failed = _fetch_or_failed(ts)
    if isinstance(body_or_failed, Failed):
        return body_or_failed
    body = body_or_failed

    if not body:
        return _failed("fetch returned empty body", ts)

    new_sha = sha256_hex(body)
    if new_sha == old_sha:
        return Unchanged(sha=new_sha)

    bootstrap = old_sha == ""
    return Changed(
        old_sha=old_sha,
        new_sha=new_sha,
        fetched_at=ts,
        is_bootstrap=bootstrap,
        issue_body=changed_issue_body(old_sha, new_sha, ts, bootstrap),
    )


def _write_state(state_path: Path, sha: str, ts: str) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(f"{sha}  {ts}\n")


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
    state: Path = args.state
    manifest: Path = args.manifest

    result = poll(state, manifest_path=manifest)

    if isinstance(result, Changed):
        _write_state(state, result.new_sha, result.fetched_at)
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
    # Failed
    print(f"failed: {result.error}", file=sys.stderr, flush=True)
    emit_gh_outputs(result)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
