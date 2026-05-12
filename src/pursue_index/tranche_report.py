"""Markdown + JSON rendering for tranche-diff reports.

Extracted from `scripts/tranche_diff.py` to keep that script under the
arch-check size and function-count thresholds. All functions here are
pure (str/dict → str) — testable without filesystem or network.
"""

from __future__ import annotations

import json
from typing import Any


def render_json(diff: dict[str, Any]) -> str:
    return json.dumps(diff, indent=2, sort_keys=False)


def _md_summary(s: dict[str, int]) -> str:
    return (
        f"- **{s['renames_confirmed']}** confirmed renames (Class A — safe to alias)\n"
        f"- **{s['new_content']}** net-new content (Class B — ingest normally)\n"
        f"- **{s['quarantined']}** quarantined (Class C — manual review required)\n"
        f"- **{s.get('restored_unchanged', 0)}** restorations with byte-identical content (safe)\n"
        f"- **{s.get('restored_modified', 0)}** restorations with MODIFIED content (manual review required — possible tampering)\n"
        f"- **{s.get('restored_unknown', 0)}** restorations with unknown bytes (no asset_url to verify)\n"
        f"- **{s['removed']}** removed upstream (no rename match)\n"
        f"- **{s['field_only_changes']}** field-only changes on existing cards\n"
    )


def _md_rename_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_None._\n"
    out = ["| old_card_id | new_card_id | byte_sha256 | new_title |", "|---|---|---|---|"]
    for r in rows:
        out.append(
            f"| `{r['old_card_id']}` | `{r['new_card_id']}` | "
            f"`{(r.get('byte_sha256') or '')[:12]}…` | "
            f"{(r.get('new_title') or '')[:80]} |"
        )
    return "\n".join(out) + "\n"


def _md_quarantined(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_None._\n"
    out: list[str] = []
    for r in rows:
        out.append(f"### `{r['new_card_id']}` — {r.get('new_title') or '(no title)'}")
        out.append(f"- new byte_sha256: `{(r.get('new_byte_sha256') or 'unknown')[:24]}…`")
        out.append(f"- new asset_filename: `{r.get('new_asset_filename') or ''}`")
        out.append(f"- matched against: {', '.join(f'`{c}`' for c in r.get('matched_against', []))}")
        out.append(f"- reasons: {'; '.join(r.get('reasons', []))}")
        out.append("")
    return "\n".join(out)


def _md_simple_rows(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    if not rows:
        return "_None._\n"
    header = "| " + " | ".join(label for _, label in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = []
    for r in rows:
        cells = [str(r.get(k, "") or "")[:80] for k, _ in cols]
        body.append("| " + " | ".join(f"`{c}`" if k in ("new_card_id", "card_id") else c
                                       for c, (k, _) in zip(cells, cols)) + " |")
    return "\n".join([header, sep] + body) + "\n"


def _md_restored(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_None._\n"
    out: list[str] = []
    for r in rows:
        out.append(f"### `{r['new_card_id']}` — {r.get('new_title') or '(no title)'}")
        out.append(
            f"- pinned byte_sha256: `{(r.get('pinned_byte_sha256') or '')[:24]}…` "
            f"(recorded {r.get('pinned_fetched_at') or '?'})"
        )
        new_sha = r.get("new_byte_sha256")
        out.append(f"- new byte_sha256: `{(new_sha or 'unknown')[:24]}…`")
        out.append(f"- new asset_url: `{r.get('new_asset_url') or ''}`")
        out.append("")
    return "\n".join(out)


def _md_field_changes(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_None._\n"
    out: list[str] = []
    for r in rows:
        out.append(f"### `{r['card_id']}`")
        for d in r["diffs"]:
            out.append(f"- **{d['field']}**: `{str(d['old'])[:60]}` → `{str(d['new'])[:60]}`")
        out.append("")
    return "\n".join(out)


def render_markdown(diff: dict[str, Any]) -> str:
    s = diff["summary"]
    parts = [
        f"# Tranche diff — `{(diff.get('tranche_sha256') or 'unknown')[:12]}…`",
        "",
        f"Prior manifest sha: `{(diff.get('prior_manifest_sha') or 'unknown')[:12]}…`",
        "",
        "## Summary",
        "",
        _md_summary(s),
        "## Renames confirmed (Class A — safe to alias)",
        "",
        _md_rename_rows(diff["renames_confirmed"]),
        "## Net-new content (Class B — ingest normally)",
        "",
        _md_simple_rows(diff["new_content"],
                        [("new_card_id", "card_id"), ("title", "title"),
                         ("asset_filename", "filename")]),
        "## Quarantined (Class C — MANUAL REVIEW REQUIRED)",
        "",
        _md_quarantined(diff["quarantined"]),
        "## Restored — byte-identical to previously preserved (safe)",
        "",
        _md_restored(diff.get("restored_unchanged", [])),
        "## Restored — MODIFIED bytes (POSSIBLE TAMPERING — MANUAL REVIEW REQUIRED)",
        "",
        _md_restored(diff.get("restored_modified", [])),
        "## Restored — bytes unknown (no asset_url to verify)",
        "",
        _md_restored(diff.get("restored_unknown", [])),
        "## Removed upstream (no rename match — candidates for /removed)",
        "",
        _md_simple_rows(diff["removed"],
                       [("card_id", "card_id"), ("title", "title"),
                        ("asset_filename", "filename")]),
        "## Field-only changes (same card_id, different metadata)",
        "",
        _md_field_changes(diff["field_only_changes"]),
    ]
    return "\n".join(parts)
