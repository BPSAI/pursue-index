"""Post-ingest TOCTOU audit (plan step 5).

Between when `tranche_diff` recorded a byte_sha for a candidate
classification (Class A rename, restored_unchanged event) and when
`pursue ingest approve` is run by the operator, upstream could in
principle serve different bytes — turning a confirmed safe-to-alias
event into a content swap done under cover of metadata change.

This module re-fetches the upstream bytes at approval time and
compares against the recorded sha. Any mismatch causes the approval
to refuse, preventing the alias from being materialized and the
deployed manifest from incorporating the new content.

Three target classes:

  * byte_collision_rename — Class A entries. expected_sha is the sha
    computed at tranche-diff time. Re-fetch; if upstream now serves a
    different sha, the rename was being used as cover for content
    substitution.

  * restored_unchanged — Class D entries. expected_sha is the pinned
    byte_sha from when the card was archived (typically via
    r2_pin_removed). Re-fetch; if upstream now serves different
    bytes, the restoration is actually a *modified* restoration.

  * operator_manual_rename — Class C entries approved by operator
    flag. These typically lack an asset_url (metadata-only PR/VID
    cards). When asset_url is None, the target is skipped with a
    note (audit-impossible by design); when present, re-fetch and
    record the sha for the audit log but do NOT refuse on mismatch
    (operator already accepted by judgment, not by byte-collision).

The audit is a pure function over (targets, fetcher); the network
call lives in the fetcher. Production callers pass a curl_cffi-based
fetcher; tests inject a synthetic map.
"""

from __future__ import annotations

from typing import Any, Callable


def collect_audit_targets(
    enriched_aliases: list[dict[str, Any]],
    diff: dict[str, Any],
    new_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the list of audit targets from the approval inputs.

    Each target carries:
      - card_id: the new card_id being audited
      - kind: byte_collision_rename | restored_unchanged | operator_manual_rename
      - asset_url: where to fetch (may be None for metadata-only cards)
      - expected_sha: what to compare against (None when no expectation)
    """
    new_by_id = {c["card_id"]: c for c in new_manifest.get("cards", [])}
    targets: list[dict[str, Any]] = []
    for alias in enriched_aliases:
        cid = alias["new_card_id"]
        card = new_by_id.get(cid, {})
        method = alias.get("method")
        if method == "byte_collision":
            targets.append({
                "card_id": cid,
                "kind": "byte_collision_rename",
                "asset_url": card.get("asset_url"),
                "expected_sha": alias.get("byte_sha256"),
            })
        elif method == "operator_manual":
            targets.append({
                "card_id": cid,
                "kind": "operator_manual_rename",
                "asset_url": card.get("asset_url"),
                "expected_sha": None,
            })
    for r in diff.get("restored_unchanged", []) or []:
        targets.append({
            "card_id": r["new_card_id"],
            "kind": "restored_unchanged",
            "asset_url": r.get("new_asset_url"),
            "expected_sha": r.get("pinned_byte_sha256"),
        })
    return targets


def _audit_one_target(
    target: dict[str, Any],
    fetch_byte_sha: Callable[[str], str | None],
) -> dict[str, Any]:
    """Re-fetch one target and classify the outcome."""
    cid = target["card_id"]
    kind = target["kind"]
    url = target.get("asset_url")
    expected = target.get("expected_sha")
    base = {"card_id": cid, "kind": kind, "expected_sha": expected,
            "asset_url": url}

    if not url:
        return {**base, "status": "skipped",
                "note": "no asset_url to audit (metadata-only card)"}

    actual = fetch_byte_sha(url)
    if actual is None:
        return {**base, "status": "fetch_failed", "actual_sha": None,
                "note": "upstream fetch failed at audit time"}

    base["actual_sha"] = actual
    if expected is None:
        # operator_manual with an asset_url — record sha for the audit
        # trail but don't refuse approval on it.
        return {**base, "status": "ok",
                "note": "operator_manual alias; sha recorded for audit trail"}

    if actual == expected:
        return {**base, "status": "ok"}
    return {**base, "status": "mismatch",
            "note": "upstream sha differs from sha recorded at tranche-diff time"}


def audit_targets(
    targets: list[dict[str, Any]],
    fetch_byte_sha: Callable[[str], str | None],
) -> list[dict[str, Any]]:
    """Run the audit across every target. Returns one result per target."""
    return [_audit_one_target(t, fetch_byte_sha) for t in targets]


def has_blocking_mismatch(results: list[dict[str, Any]]) -> bool:
    """Return True iff any result requires refusing the approval.

    `mismatch` for byte_collision_rename or restored_unchanged is
    blocking. Other statuses (ok, skipped, fetch_failed) are not
    blocking by themselves — though fetch_failed warrants operator
    attention and is surfaced in the audit report.
    """
    return any(
        r["status"] == "mismatch"
        and r["kind"] in ("byte_collision_rename", "restored_unchanged")
        for r in results
    )


def render_audit_summary(results: list[dict[str, Any]]) -> str:
    """One-screen human summary of audit outcomes."""
    if not results:
        return "[audit] no targets to verify (no byte-collision aliases, no restored_unchanged)\n"
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    lines = ["[audit] re-verification results:"]
    for status in ("ok", "mismatch", "fetch_failed", "skipped"):
        if status in by_status:
            lines.append(f"  {status}: {by_status[status]}")
    for r in results:
        if r["status"] in ("mismatch", "fetch_failed"):
            lines.append(
                f"  - {r['status'].upper()} {r['card_id']} ({r['kind']}) "
                f"expected={(r.get('expected_sha') or '')[:12]}… "
                f"actual={(r.get('actual_sha') or 'none')[:12]}…"
            )
    return "\n".join(lines) + "\n"
