"""Lightweight poll for upstream PURSUE CSV changes.

This script runs from a GitHub Actions cron schedule (see
``.github/workflows/poll-pursue.yml``). It is the lightweight half of
the two-layer architecture in ``.paircoder/plans/auto-poll-tranches.md``:

* Fetch the upstream CSV via ``pursue_index.scrape.csv_fetcher`` —
  same curl_cffi + Chrome-TLS path as ``pursue scrape run``, so the
  Akamai bypass is exercised and we get an early signal if it stops
  working.
* SHA-256 the bytes; compare to the previously-observed value stored
  in ``data/last-known-csv-sha.txt`` (committed to the repo so drift
  is visible from ``git log``).
* On unchanged: exit 0 with status=unchanged.
* On change: exit 0 with status=changed and emit an issue payload tagged
  ``tranche-detected`` so the operator runs the heavy pipeline.
* On fetch failure: exit 1 with status=failed and emit an issue payload
  tagged ``tranche-poll-failure``.

The script never auto-runs the heavy ingest pipeline. Per the plan:
"GPU provisioning, cost, content review" — operator-attended is the
right policy.

Run manually:

    python scripts/poll_pursue.py [--state data/last-known-csv-sha.txt]

Set ``GITHUB_OUTPUT`` to the path of an output kv-pairs file to have
``status``, ``old_sha``, ``new_sha``, ``issue_title``, ``issue_body``,
and ``issue_labels`` written for the surrounding workflow to consume.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Make ``src/`` importable when running as ``python scripts/poll_pursue.py``
# from the repo root (no install needed in the GH Actions runner).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.scrape.csv_fetcher import fetch_raw_csv  # noqa: E402

DEFAULT_STATE_PATH = _REPO_ROOT / "data" / "last-known-csv-sha.txt"


@dataclass(frozen=True)
class Unchanged:
    """The upstream sha matches the last-known sha."""

    sha: str


@dataclass(frozen=True)
class Changed:
    """The upstream sha differs from last-known (or there is no last-known)."""

    old_sha: str
    new_sha: str
    fetched_at: str
    is_bootstrap: bool = False
    issue_labels: tuple[str, ...] = ("tranche-detected",)
    issue_body: str = ""


@dataclass(frozen=True)
class Failed:
    """The fetch raised, returned non-200, or returned an empty body."""

    error: str
    fetched_at: str
    issue_labels: tuple[str, ...] = ("tranche-poll-failure",)
    issue_body: str = ""
    extra: dict[str, str] = field(default_factory=dict)


PollResult = Unchanged | Changed | Failed


def sha256_hex(body: bytes) -> str:
    """SHA-256 of the raw bytes, hex-encoded. Pure, deterministic."""
    return hashlib.sha256(body).hexdigest()


def _read_last_known(state_path: Path) -> str:
    """Return the previously-observed sha, or ``""`` if there isn't one.

    File format: ``{sha256}  {iso8601}\n`` (two spaces between fields).
    """
    if not state_path.exists():
        return ""
    text = state_path.read_text().strip()
    if not text:
        return ""
    return text.split()[0]


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _changed_issue_body(old_sha: str, new_sha: str, ts: str, bootstrap: bool) -> str:
    if bootstrap:
        return (
            "First observation of upstream CSV. Recording sha for future"
            f" change detection.\n\n* new_sha: `{new_sha}`\n"
            f"* observed_at: {ts}\n"
        )
    return (
        "Upstream PURSUE CSV changed. The operator should run the heavy"
        " ingest pipeline (`pursue scrape run` -> download -> ocr -> embed).\n\n"
        f"* old_sha: `{old_sha}`\n"
        f"* new_sha: `{new_sha}`\n"
        f"* observed_at: {ts}\n"
    )


def _failed_issue_body(error: str, ts: str) -> str:
    return (
        "Polling the upstream CSV failed. This may indicate Akamai has"
        " changed defenses, the upstream is down, or our curl_cffi"
        " impersonation has drifted. Investigate before assuming the"
        " corpus is stable.\n\n"
        f"* error: {error}\n"
        f"* observed_at: {ts}\n"
    )


def poll(state_path: Path) -> PollResult:
    """Fetch upstream, compare to ``state_path``, return a result.

    Pure observation: does NOT mutate ``state_path``. The caller (the
    CLI / workflow) decides whether to commit a new sha.
    """
    ts = _now_iso()
    old_sha = _read_last_known(state_path)

    try:
        body = fetch_raw_csv()
    except Exception as exc:  # noqa: BLE001 — surface any transport failure
        err = f"{type(exc).__name__}: {exc}"
        return Failed(error=err, fetched_at=ts, issue_body=_failed_issue_body(err, ts))

    if not body:
        err = "fetch returned empty body"
        return Failed(error=err, fetched_at=ts, issue_body=_failed_issue_body(err, ts))

    new_sha = sha256_hex(body)
    if new_sha == old_sha:
        return Unchanged(sha=new_sha)

    bootstrap = old_sha == ""
    return Changed(
        old_sha=old_sha,
        new_sha=new_sha,
        fetched_at=ts,
        is_bootstrap=bootstrap,
        issue_body=_changed_issue_body(old_sha, new_sha, ts, bootstrap),
    )


def _write_state(state_path: Path, sha: str, ts: str) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(f"{sha}  {ts}\n")


def _emit_gh_outputs(result: PollResult) -> None:
    """Write step-output kv pairs if GITHUB_OUTPUT is set."""
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        return
    lines: list[str] = []
    if isinstance(result, Unchanged):
        lines.append("status=unchanged")
        lines.append(f"new_sha={result.sha}")
    elif isinstance(result, Changed):
        lines.append("status=changed")
        lines.append(f"old_sha={result.old_sha}")
        lines.append(f"new_sha={result.new_sha}")
        lines.append(f"is_bootstrap={'true' if result.is_bootstrap else 'false'}")
        lines.append(f"issue_labels={','.join(result.issue_labels)}")
        lines.append(f"issue_title=PURSUE tranche detected: {result.new_sha[:12]}")
        lines.append("issue_body<<EOF")
        lines.append(result.issue_body.rstrip("\n"))
        lines.append("EOF")
    else:  # Failed
        lines.append("status=failed")
        lines.append(f"error={result.error}")
        lines.append(f"issue_labels={','.join(result.issue_labels)}")
        lines.append("issue_title=PURSUE poll failed")
        lines.append("issue_body<<EOF")
        lines.append(result.issue_body.rstrip("\n"))
        lines.append("EOF")
    with open(out_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="Path to the last-known-sha file.",
    )
    args = parser.parse_args(argv)
    state: Path = args.state

    result = poll(state)

    if isinstance(result, Changed):
        _write_state(state, result.new_sha, result.fetched_at)
        print(
            f"changed: {result.old_sha or '(bootstrap)'} -> {result.new_sha}",
            flush=True,
        )
        _emit_gh_outputs(result)
        return 0
    if isinstance(result, Unchanged):
        print(f"unchanged: {result.sha}", flush=True)
        _emit_gh_outputs(result)
        return 0
    # Failed
    print(f"failed: {result.error}", file=sys.stderr, flush=True)
    _emit_gh_outputs(result)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
