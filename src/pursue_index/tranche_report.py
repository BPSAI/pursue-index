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
        matches = r.get("matches", [])
        if matches:
            out.append("- candidate matches (ranked by signal strength — more reasons firing = stronger):")
            for m in matches:
                stars = "★" * min(m["strength"], 4)
                reasons = "; ".join(m["reasons"])
                title = m.get("title") or "(no title)"
                out.append(f"  - {stars} `{m['card_id']}` — {title} — _{reasons}_")
        else:
            # Backwards-compat for older diff payloads.
            out.append(f"- matched against: {', '.join(f'`{c}`' for c in r.get('matched_against', []))}")
        out.append("")
    return "\n".join(out)


def _build_rename_candidate_index(quarantined: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Reverse-index: {old_card_id: [{quarantined_new_id, strength}, ...]}.

    Used to annotate the removed section with "also a candidate rename
    source for: ..." backlinks. An old card_id can appear as a candidate
    for multiple quarantined new card_ids; we show all.
    """
    idx: dict[str, list[dict[str, Any]]] = {}
    for q in quarantined:
        for m in q.get("matches", []):
            idx.setdefault(m["card_id"], []).append({
                "quarantined_new_id": q["new_card_id"],
                "new_title": q.get("new_title"),
                "strength": m["strength"],
            })
    # Within each old card's list, sort strongest-first so the operator
    # sees the most-likely rename target first.
    for entries in idx.values():
        entries.sort(key=lambda e: -e["strength"])
    return idx


def _md_removed_with_backlinks(
    removed: list[dict[str, Any]],
    rename_candidates: dict[str, list[dict[str, Any]]],
) -> str:
    if not removed:
        return "_None._\n"
    out: list[str] = []
    out.append("| card_id | title | filename | candidate rename source for |")
    out.append("|---|---|---|---|")
    for r in removed:
        cid = r["card_id"]
        title = (r.get("title") or "")[:80]
        filename = (r.get("asset_filename") or "")[:80]
        candidates = rename_candidates.get(cid, [])
        if candidates:
            cell = "<br>".join(
                f"{'★' * min(c['strength'], 4)} `{c['quarantined_new_id']}`"
                for c in candidates
            )
        else:
            cell = "(no rename candidate — likely genuine removal)"
        out.append(f"| `{cid}` | {title} | `{filename}` | {cell} |")
    return "\n".join(out) + "\n"


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
        "## Removed upstream (candidates for /removed — or candidate rename sources)",
        "",
        "_An old card_id can appear here AND in the Quarantined section's 'candidate matches' list — that's by design while operator review is pending. Once you `--approve-rename <new>=<old>`, that pairing materializes as an alias and the old card_id is no longer a candidate for /removed. The 'candidate rename source for' column shows the reverse view: which quarantined cards (if any) are hypothesized to be this old card's new identity._",
        "",
        _md_removed_with_backlinks(
            diff["removed"],
            _build_rename_candidate_index(diff.get("quarantined", [])),
        ),
        "## Field-only changes (same card_id, different metadata)",
        "",
        _md_field_changes(diff["field_only_changes"]),
    ]
    return "\n".join(parts)
