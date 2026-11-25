"""An unlisted asset host fails its own row, not the run, and turns every lane red."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tests.unit.r2_verify_harness import NEW_BODY, World, card_id

ROOT = Path(__file__).resolve().parents[2]


def _world_with_unlisted(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1)
    w.add_card(2)
    bad = w.cards[1]
    bad["asset_url"] = "https://evil.example.net/c2.pdf"
    w.bodies[bad["asset_url"]] = NEW_BODY
    return w


def test_the_other_card_is_still_processed_and_the_unlisted_one_gets_no_row(tmp_path, monkeypatch, capsys):
    w = _world_with_unlisted(tmp_path, monkeypatch)
    w.run()
    assert [r["card_id"] for r in w.new_rows()] == [card_id(1)]
    assert not any("evil.example.net" in u for u in w.fetched + w.headed)


def test_the_error_line_names_the_card_and_the_host(tmp_path, monkeypatch, capsys):
    w = _world_with_unlisted(tmp_path, monkeypatch)
    w.run()
    err = capsys.readouterr().err
    line = next(ln for ln in err.splitlines() if "not listed in" in ln)
    assert "ERROR" in line and "evil.example.net" in line and card_id(2) in line


def test_the_done_line_counts_the_unlisted_card(tmp_path, monkeypatch, capsys):
    w = _world_with_unlisted(tmp_path, monkeypatch)
    w.run()
    assert "unlisted_host=1" in capsys.readouterr().out


def test_the_poll_mode_exit_is_nonzero_with_no_drift_flag(tmp_path, monkeypatch):
    w = _world_with_unlisted(tmp_path, monkeypatch)
    assert w.run("--asset-types", "PDF,IMG") != 0


def test_an_all_listed_run_still_exits_zero(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1)
    w.add_card(2)
    assert w.run() == 0


def test_the_poll_workflow_goes_red_when_the_archive_step_fails():
    wf = yaml.safe_load((ROOT / ".github/workflows/poll-pursue.yml").read_text())
    steps = [s for j in wf["jobs"].values() for s in j["steps"]]
    archive = next(s for s in steps if s.get("id") == "r2_archive")
    propagate = next(s for s in steps if s.get("name") == "Propagate failure exit code")
    assert "|| true" not in archive["run"]
    assert re.search(r"steps\.r2_archive\.outcome\s*==\s*'failure'", str(propagate["if"]))
    commit = next(s for s in steps if s.get("id") == "registry_commit")
    assert "failure" in commit["if"], "rows written before a refused card are still committed"


def test_an_unlisted_host_still_fails_a_run_with_no_credentials(tmp_path, monkeypatch, capsys):
    """Without R2 credentials the archive step is skipped, but an unlisted host must not
    pass silently: the run names it and exits non-zero."""
    w = _world_with_unlisted(tmp_path, monkeypatch)
    w.creds = False
    rc = w.run()
    err = capsys.readouterr().err
    assert rc != 0
    assert "evil.example.net" in err and "not listed in" in err


def test_a_run_with_no_credentials_and_only_listed_hosts_still_warns_and_skips(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add_card(1)
    w.creds = False
    assert w.run() == 0
    assert "skipping the archive step" in capsys.readouterr().err
