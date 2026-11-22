"""A published PDF card with no registry row cannot stay unverified for ever."""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import check_ocr_input_freshness as gate  # noqa: E402

TODAY = date(2026, 11, 21)


def _cid(n: int) -> str:
    return f"{n:016x}"


def _released(days_ago: int) -> str:
    d = TODAY - timedelta(days=days_ago)
    return f"{d.month}/{d.day}/{d.year}"


class Env:
    def __init__(self, root: Path) -> None:
        self.data_root = root / "dataroot"
        (self.data_root / "ocr").mkdir(parents=True)
        self.manifest = root / "latest.json"
        self.registry = root / "registry.jsonl"
        self.dispositions = root / "byte-change-dispositions.jsonl"
        self.registry.write_text("")
        self.cards: list[dict] = []

    def card(self, n: int, days_ago: int | None, asset_type: str = "PDF") -> str:
        c = {"card_id": _cid(n), "asset_type": asset_type}
        if days_ago is not None:
            c["release_date"] = _released(days_ago)
        self.cards.append(c)
        return _cid(n)

    def run(self, capsys, *extra: str) -> tuple[int, str]:
        self.manifest.write_text(json.dumps({"cards": self.cards}))
        code = gate.main([
            "--manifest", str(self.manifest), "--registry", str(self.registry),
            "--dispositions", str(self.dispositions), "--data-root", str(self.data_root),
            *extra,
        ], today=TODAY)
        got = capsys.readouterr()
        return code, got.out + got.err


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_a_card_unregistered_for_more_than_n_days_is_flagged_and_counted(env, capsys):
    cid = env.card(1, days_ago=4)
    code, out = env.run(capsys)
    assert code == 0, "warn-only without a ceiling"
    assert f"unregistered-stale: {cid}" in out and "unregistered-stale: 1" in out
    assert "2026-11-17" in out, "the line says which date was used"


def test_a_fresh_unregistered_card_is_only_unregistered(env, capsys):
    env.card(1, days_ago=2)
    code, out = env.run(capsys)
    assert code == 0 and "unregistered-stale: 0" in out and "unregistered: 1" in out


def test_exactly_n_days_old_is_not_yet_stale(env, capsys):
    env.card(1, days_ago=3)
    _, out = env.run(capsys)
    assert "unregistered-stale: 0" in out


def test_n_is_configurable(env, capsys):
    env.card(1, days_ago=2)
    _, out = env.run(capsys, "--unregistered-days", "1")
    assert "unregistered-stale: 1" in out


def test_above_the_ceiling_the_gate_fails_and_at_it_passes(env, capsys):
    env.card(1, days_ago=9)
    env.card(2, days_ago=9)
    code, out = env.run(capsys, "--max-unregistered-stale", "1")
    assert code == 1 and "exceeds the ceiling 1 (--max-unregistered-stale)" in out
    code, _ = env.run(capsys, "--max-unregistered-stale", "2")
    assert code == 0


def test_a_card_with_a_registry_row_is_never_unregistered_stale(env, capsys):
    cid = env.card(1, days_ago=30)
    env.registry.write_text(json.dumps({"card_id": cid, "byte_sha256": "b" * 64,
                                        "current_key": f"{cid}.pdf"}) + "\n")
    _, out = env.run(capsys)
    assert "unregistered-stale: 0" in out


def test_non_pdf_cards_are_not_flagged(env, capsys):
    env.card(1, days_ago=30, asset_type="VID")
    _, out = env.run(capsys)
    assert "unregistered-stale: 0" in out


def test_a_card_without_a_usable_release_date_is_not_aged(env, capsys):
    env.card(1, days_ago=None)
    env.cards.append({"card_id": _cid(2), "asset_type": "PDF", "release_date": "soon"})
    code, out = env.run(capsys)
    assert code == 0 and "unregistered-stale: 0" in out and "unregistered: 2" in out


def test_the_release_record_lists_the_stale_cards(env, capsys, tmp_path):
    cid = env.card(1, days_ago=5)
    rec = tmp_path / "rec.json"
    env.run(capsys, "--record", str(rec))
    got = json.loads(rec.read_text())["unregistered_stale_pdf_cards"]
    assert got == {"count": 1, "cards": [cid], "days": 3}


def test_a_card_without_a_usable_release_date_is_unregistered_undated(env, capsys):
    cid = env.card(1, days_ago=None)
    env.cards.append({"card_id": _cid(2), "asset_type": "PDF", "release_date": "soon"})
    code, out = env.run(capsys)
    assert code == 0, "warn-only without a ceiling"
    assert f"unregistered-undated: {cid}" in out and "unregistered-undated: 2" in out


def test_undated_cards_fail_above_the_same_ceiling_as_stale(env, capsys):
    env.card(1, days_ago=None)
    env.card(2, days_ago=9)
    code, out = env.run(capsys, "--max-unregistered-stale", "1")
    assert code == 1 and "exceeds the ceiling 1 (--max-unregistered-stale)" in out
    code, _ = env.run(capsys, "--max-unregistered-stale", "2")
    assert code == 0


def test_an_undated_card_with_a_registry_row_is_not_listed(env, capsys):
    cid = env.card(1, days_ago=None)
    env.registry.write_text(json.dumps({"card_id": cid, "byte_sha256": "b" * 64,
                                        "current_key": f"{cid}.pdf"}) + "\n")
    _, out = env.run(capsys)
    assert "unregistered-undated: 0" in out


def test_the_release_record_lists_the_undated_cards(env, capsys, tmp_path):
    cid = env.card(1, days_ago=None)
    rec = tmp_path / "rec.json"
    env.run(capsys, "--record", str(rec))
    got = json.loads(rec.read_text())["unregistered_undated_pdf_cards"]
    assert got == {"count": 1, "cards": [cid]}


def test_today_is_not_a_command_line_argument(env, capsys):
    env.manifest.write_text(json.dumps({"cards": []}))
    with pytest.raises(SystemExit) as exc:
        gate.main(["--manifest", str(env.manifest), "--today", "2026-01-01"])
    assert exc.value.code == 2
    assert "--today" in capsys.readouterr().err
