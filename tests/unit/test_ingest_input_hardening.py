"""Operator input to `pursue ingest` is checked before it is used.

`--reason` (for --allow-behind and --skip-audit) is echoed and written to the
audit logs, so non-printable characters (terminal escapes, newlines) are
dropped before its length is checked. `--tranche` must be 12-64 lowercase hex
on `check` and `run` too, before it reaches a path or glob.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.poll_freshness import require_reason

runner = CliRunner()


def test_a_reason_loses_control_and_escape_characters() -> None:
    raw = "\x1b[31mupstream down\x1b[0m;\nbytes checked\x07 by hand"
    cleaned = require_reason(raw)
    assert "\x1b" not in cleaned and "\n" not in cleaned and "\x07" not in cleaned
    assert cleaned == "[31mupstream down[0m;bytes checked by hand"


def test_a_reason_that_is_only_control_characters_is_too_thin() -> None:
    with pytest.raises(ValueError, match="at least"):
        require_reason("\x1b\x1b\x1b\x1b\x1b\x1b\x1b\x1b\x1b\x1b\x1b\x1b\x1b")


@pytest.mark.parametrize("command", [["ingest", "check"], ["ingest", "run", "--dry-run"]])
def test_check_and_run_refuse_a_malformed_tranche(command: list[str]) -> None:
    result = runner.invoke(app, [*command, "--tranche", "ab*"])
    assert result.exit_code == 2, result.output
    assert "12-64 lowercase hex" in result.output
