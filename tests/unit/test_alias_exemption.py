"""An alias row excuses a removed card_id only when an operator signed it off."""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.release.alias_exemption import resolve_with_audit

_SHA = "cd" * 32


def _write(tmp_path: Path, rows: list[dict[str, str]], approved: list[str]) -> tuple[Path, Path]:
    aliases = tmp_path / "card-aliases.json"
    aliases.write_text(json.dumps({"aliases": rows}))
    log = tmp_path / "approvals.jsonl"
    log.write_text("".join(json.dumps({"tranche_sha256": s}) + "\n" for s in approved))
    return aliases, log


def _row(method: str = "operator_manual", sha: str = _SHA) -> dict[str, str]:
    return {"old_card_id": "a", "new_card_id": "c", "method": method, "tranche_sha256": sha}


def test_trusted_row_is_exempt_and_audited(tmp_path: Path) -> None:
    aliases, log = _write(tmp_path, [_row()], [_SHA])
    audit = tmp_path / "audit.jsonl"

    renamed, missing = resolve_with_audit("s.py", ["a"], {"c"}, aliases, log, audit)

    assert (renamed, missing) == (["a -> c"], [])
    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    assert len(rows) == 1
    assert (rows[0]["old_card_id"], rows[0]["new_card_id"]) == ("a", "c")
    assert rows[0]["method"] == "operator_manual"
    assert rows[0]["tranche_sha256"] == _SHA


def test_unlisted_method_is_not_exempt(tmp_path: Path) -> None:
    aliases, log = _write(tmp_path, [_row(method="self_declared")], [_SHA])
    audit = tmp_path / "audit.jsonl"

    assert resolve_with_audit("s.py", ["a"], {"c"}, aliases, log, audit) == ([], ["a"])
    assert not audit.exists()


def test_tranche_missing_from_the_approval_log_is_not_exempt(tmp_path: Path) -> None:
    aliases, log = _write(tmp_path, [_row()], ["ef" * 32])
    audit = tmp_path / "audit.jsonl"

    assert resolve_with_audit("s.py", ["a"], {"c"}, aliases, log, audit) == ([], ["a"])
    assert not audit.exists()


def test_row_without_a_tranche_or_without_an_approval_log_is_not_exempt(
    tmp_path: Path,
) -> None:
    aliases, log = _write(tmp_path, [_row(sha="")], [_SHA, ""])
    assert resolve_with_audit("s.py", ["a"], {"c"}, aliases, log, tmp_path / "x") == ([], ["a"])

    aliases, _ = _write(tmp_path, [_row()], [_SHA])
    assert resolve_with_audit("s.py", ["a"], {"c"}, aliases, None, tmp_path / "x") == ([], ["a"])


def test_untrusted_later_row_does_not_override_a_trusted_one(tmp_path: Path) -> None:
    later = {**_row(method="self_declared"), "new_card_id": "z"}
    aliases, log = _write(tmp_path, [_row(), later], [_SHA])

    renamed, _ = resolve_with_audit("s.py", ["a"], {"c"}, aliases, log, tmp_path / "a.jsonl")

    assert renamed == ["a -> c"]


def test_revoke_row_removes_the_exemption(tmp_path: Path) -> None:
    aliases, log = _write(tmp_path, [_row(), _row(method="operator_revoke")], [_SHA])

    assert resolve_with_audit("s.py", ["a"], {"c"}, aliases, log, tmp_path / "a.jsonl") == (
        [], ["a"],
    )


def test_revoke_from_an_unapproved_tranche_still_removes_the_exemption(
    tmp_path: Path,
) -> None:
    """A revoke can only narrow what is excused, so it needs no approval."""
    aliases, log = _write(
        tmp_path, [_row(), _row(method="operator_revoke", sha="ef" * 32)], [_SHA]
    )
    audit = tmp_path / "audit.jsonl"

    assert resolve_with_audit("s.py", ["a"], {"c"}, aliases, log, audit) == ([], ["a"])
    assert not audit.exists()
