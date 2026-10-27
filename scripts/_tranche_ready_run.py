"""Entry point for ``poll_snapshot.py --tranche-ready-dir`` (R7C.31).

Turns the job's two refusals into exit codes and an operator-readable
failure body, without writing any output:

* exit 3 -- an output already exists for this sha and the recompute
  disagrees (append-only, the same code ``--diff-out`` uses);
* exit 4 -- the record does not validate against the vendored schema; the
  message names the failing field.

:func:`publish` validates the record and checks append-only for BOTH
outputs (the diff receipt and the record) before writing either.

``--error-out`` receives the body the workflow's failure step files as the
poll failure issue, so the issue itself names the field.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from _tranche_ready_job import JobConfig, build

from pursue_index.release.rates import JudgeRate
from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv
from pursue_index.scrape.manifest import save_manifest
from pursue_index.scrape.pdf_pages import FetchedPdfs
from pursue_index.tranche_ready.refusal import MAX_BODY_BYTES, cap, neutralize
from pursue_index.tranche_ready.writer import (
    AppendOnlyError,
    InvalidRecordError,
    check_record,
    needs_write,
    write_record,
)
from pursue_index.tranche_report import render_json, render_markdown

EXIT_APPEND_ONLY, EXIT_INVALID = 3, 4


def config_from_args(args: argparse.Namespace) -> JobConfig:
    return JobConfig(
        ready_dir=args.tranche_ready_dir, diff_dir=args.tranche_diff_dir,
        registry=args.registry, poll_state=args.poll_state, csv_archive=args.csv_archive,
        tranche_issue=args.tranche_issue,
        poll_run_id=args.poll_run_id, poll_commit=args.poll_commit,
    )


def publish(diff: dict, record: dict, cfg: JobConfig) -> list[Path]:
    """Validate, check append-only for both outputs, then write what changed.

    Raises ``InvalidRecordError``/``AppendOnlyError`` before writing anything.
    """
    check_record(record)
    sha12 = record["tranche_sha12"]
    receipt = cfg.diff_dir / f"tranche-diff-{sha12}.json"
    target = cfg.ready_dir / f"{sha12}.json"
    write_receipt = needs_write(receipt, json.loads(render_json(diff)), ignore=())
    write_target = needs_write(target, record)
    written = []
    if write_receipt:
        cfg.diff_dir.mkdir(parents=True, exist_ok=True)
        receipt.write_text(render_json(diff) + "\n", encoding="utf-8")
        receipt.with_suffix(".md").write_text(render_markdown(diff), encoding="utf-8")
        written += [receipt, receipt.with_suffix(".md")]
    if write_target:
        write_record(target, record)
        written.append(target)
    return written


def _fail(code: int, message: str, sha12: str, error_out: Path | None,
          full_diff: str | None = None) -> int:
    """Report a refusal. The issue body (``error_out``) is public: value-free,
    neutralized and capped. ``full_diff`` goes to a local gitignored file."""
    safe = cap(neutralize(message), MAX_BODY_BYTES - 1024)
    print(f"poll-snapshot.error {safe}", file=sys.stderr, flush=True)
    if error_out is None:
        return code
    error_out.parent.mkdir(parents=True, exist_ok=True)
    note = ""
    if full_diff is not None:
        diff_path = error_out.with_name(f"{error_out.stem}-{sha12}.diff.json")
        diff_path.write_text(full_diff, encoding="utf-8")
        note = f"\nFull diff (local, not committed): {neutralize(str(diff_path))}\n"
    body = (f"The snapshot job refused to publish the tranche-ready record for "
            f"`{sha12}`; nothing was written or committed.\n\n```\n{safe}\n```\n{note}")
    error_out.write_text(cap(body), encoding="utf-8")
    return code


def run_job(raw: bytes, latest: Path, source_url: str, cfg: JobConfig, fetched: FetchedPdfs,
            judge: JudgeRate | None, *, error_out: Path | None = None) -> int:
    """Build, validate and publish the diff receipt + record; 0, 3 or 4."""
    if not latest.exists():
        print("poll-snapshot.tranche-ready skipped: no prior manifest (bootstrap)", flush=True)
        return 0
    old_m = json.loads(latest.read_text(encoding="utf-8"))
    manifest = build_manifest(raw, parse_csv(raw), source_url)
    new_m = json.loads(manifest.model_dump_json(by_alias=True))
    sha12 = manifest.csv_sha256[:12]
    with tempfile.TemporaryDirectory(prefix="pursue-tranche-manifest-") as tmp:
        new_path = save_manifest(manifest, Path(tmp) / f"{manifest.csv_sha256}.json")
        diff, record = build(new_m, old_m, cfg, fetched, judge, new_path)
    try:
        written = publish(diff, record, cfg)
    except InvalidRecordError as exc:
        return _fail(EXIT_INVALID, str(exc), sha12, error_out)
    except AppendOnlyError as exc:
        return _fail(EXIT_APPEND_ONLY, str(exc), sha12, error_out, exc.full_diff())
    state = "written" if written else "unchanged"
    print(f"poll-snapshot.tranche-ready {state} sha={sha12} status={record['status']}",
          flush=True)
    return 0
