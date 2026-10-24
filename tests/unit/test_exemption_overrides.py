"""``--aliases`` / ``--approval-log`` / ``--audit-log`` decide which removed
cards the shrink guard excuses and where that is recorded, so pointing them
away from the repo defaults needs ``--allow-override --reason`` and leaves an
audit row in the default log."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from pursue_index.release.alias_exemption import add_exemption_args, exemption_paths
from pursue_index.release.shrink_guard import add_shrink_args


def _parser(tmp_path: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    add_exemption_args(
        parser,
        aliases=tmp_path / "data" / "card-aliases.json",
        approval_log=tmp_path / "data" / "tranche-approval-log.jsonl",
        audit_log=tmp_path / "data" / "audit-log.jsonl",
    )
    add_shrink_args(parser, "pages.json")
    return parser


def _resolve(tmp_path: Path, argv: list[str]) -> tuple[Path, Path, Path]:
    parser = _parser(tmp_path)
    return exemption_paths(parser, parser.parse_args(argv), "build_x.py")


def test_defaults_pass_without_an_override(tmp_path: Path) -> None:
    aliases, approvals, audit = _resolve(tmp_path, [])

    assert aliases == tmp_path / "data" / "card-aliases.json"
    assert approvals == tmp_path / "data" / "tranche-approval-log.jsonl"
    assert audit == tmp_path / "data" / "audit-log.jsonl"
    assert not (tmp_path / "data" / "audit-log.jsonl").exists()


@pytest.mark.parametrize("flag", ["--aliases", "--approval-log", "--audit-log"])
def test_a_non_default_path_without_the_override_is_a_usage_error(
    tmp_path: Path, flag: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        _resolve(tmp_path, [flag, str(tmp_path / "elsewhere")])

    assert exc.value.code == 2


def test_the_override_flag_alone_is_not_enough(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _resolve(tmp_path, ["--approval-log", str(tmp_path / "x"), "--allow-override"])


def test_an_override_with_a_reason_is_audited_in_the_default_log(tmp_path: Path) -> None:
    mine = tmp_path / "approvals.jsonl"
    other_audit = tmp_path / "scratch-audit.jsonl"

    _, approvals, audit = _resolve(
        tmp_path,
        [
            "--approval-log", str(mine), "--audit-log", str(other_audit),
            "--allow-override", "--reason", "rehearsal against a copy",
        ],
    )

    assert approvals == mine and audit == other_audit
    rows = [
        json.loads(line)
        for line in (tmp_path / "data" / "audit-log.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["event"] == "exemption_input_override"
    assert rows[0]["script"] == "build_x.py"
    assert rows[0]["reason"] == "rehearsal against a copy"
    assert set(rows[0]["overrides"]) == {"approval_log", "audit_log"}
