"""``scripts/check_ocr_input_freshness.py``: OCR input must match the registry's latest PDF."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import check_ocr_input_freshness as gate  # noqa: E402

CARD = "7d1b50162c29378a"
OLD, NEW, REF = "a" * 64, "b" * 64, "3" * 64


class Env:
    def __init__(self, root: Path) -> None:
        self.data_root = root / "dataroot"
        (self.data_root / "ocr").mkdir(parents=True)
        self.manifest = root / "latest.json"
        self.registry = root / "registry.jsonl"
        self.dispositions = root / "byte-change-dispositions.jsonl"
        self.manifest.write_text(json.dumps({"cards": [{"card_id": CARD, "asset_type": "PDF"}]}))
        self.registry.write_text(
            json.dumps({"card_id": CARD, "byte_sha256": NEW, "current_key": f"{CARD}.pdf"}) + "\n"
        )

    def meta(self, sha: str, card: str = CARD) -> None:
        d = self.data_root / "ocr" / card
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps({"pdf_sha256": sha}))

    def disposition(self, **over) -> None:
        row = {
            "card_id": CARD, "old_sha256": OLD, "new_sha256": NEW,
            "disposition": "resave-content-verified", "reviewed_at": "2026-11-21",
            "evidence": "re-save", "evidence_ref": REF, "ocr_from": OLD,
        }
        row.update(over)
        self.dispositions.write_text(json.dumps(row) + "\n")

    def run(self, capsys) -> tuple[int, str]:
        code = gate.main([
            "--manifest", str(self.manifest), "--registry", str(self.registry),
            "--dispositions", str(self.dispositions), "--data-root", str(self.data_root),
        ])
        captured = capsys.readouterr()
        return code, captured.out + captured.err


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_fresh_ocr_passes(env, capsys):
    env.meta(NEW)
    code, out = env.run(capsys)
    assert code == 0 and "OK" in out


def test_stale_ocr_without_disposition_fails_and_lists_both_shas(env, capsys):
    env.meta(OLD)
    code, out = env.run(capsys)
    assert code == 1
    assert CARD in out and OLD in out and NEW in out and "no disposition" in out


def test_matching_disposition_passes(env, capsys):
    env.meta(OLD)
    env.disposition()
    code, out = env.run(capsys)
    assert code == 0 and "covered" in out


def test_content_changed_disposition_does_not_cover(env, capsys):
    env.meta(OLD)
    env.disposition(disposition="content-changed")
    code, _ = env.run(capsys)
    assert code == 1


def test_disposition_for_another_ocr_sha_does_not_cover(env, capsys):
    env.meta("c" * 64)
    env.disposition()
    code, _ = env.run(capsys)
    assert code == 1


def test_missing_meta_is_unverifiable_not_failed(env, capsys):
    code, out = env.run(capsys)
    assert code == 0
    assert f"unverifiable provenance: {CARD} (no meta.json)" in out
    assert "unverifiable provenance: 1" in out and "0 stale" in out
    assert "OK" in out


def test_meta_without_pdf_sha256_is_unverifiable_not_failed(env, capsys):
    d = env.data_root / "ocr" / CARD
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"pages": 3}))
    code, out = env.run(capsys)
    assert code == 0
    assert f"unverifiable provenance: {CARD} (no pdf_sha256)" in out


def test_real_mismatch_still_fails_alongside_unverifiable(env, capsys):
    other = "1234567890abcdef"
    env.manifest.write_text(json.dumps({"cards": [
        {"card_id": CARD, "asset_type": "PDF"}, {"card_id": other, "asset_type": "PDF"},
    ]}))
    env.registry.write_text(
        json.dumps({"card_id": CARD, "byte_sha256": NEW, "current_key": f"{CARD}.pdf"}) + "\n"
        + json.dumps({"card_id": other, "byte_sha256": NEW, "current_key": f"{other}.pdf"}) + "\n"
    )
    env.meta(OLD)  # CARD: real mismatch; `other`: no meta.json
    code, out = env.run(capsys)
    assert code == 1
    assert f"stale OCR input: {CARD}" in out and f"unverifiable provenance: {other}" in out


def test_record_lists_unverifiable_cards_and_count(env, capsys, tmp_path):
    record = tmp_path / "rec.json"
    code = gate.main([
        "--manifest", str(env.manifest), "--registry", str(env.registry),
        "--dispositions", str(env.dispositions), "--data-root", str(env.data_root),
        "--record", str(record),
    ])
    assert code == 0
    rec = json.loads(record.read_text())
    assert rec["unverifiable_provenance"] == {
        "count": 1, "cards": [{"card_id": CARD, "reason": "no meta.json"}],
    }
    assert rec["stale"] == 0 and rec["checked"] == 1


def test_gate_and_scoping_agree_on_stale(env, capsys):
    """A card the gate calls stale is exactly one rule 4 scopes ``bytes-changed``."""
    from pursue_index.ingest_scope import REASON_BYTES_CHANGED, _bytes_changed_ids

    env.meta(OLD)
    code, out = env.run(capsys)
    assert code == 1 and f"stale OCR input: {CARD}" in out
    assert list(_bytes_changed_ids({CARD: NEW}, {CARD: OLD}, {})) == [(CARD, REASON_BYTES_CHANGED)]


def test_gate_and_scoping_agree_unverifiable_is_never_scoped(env, capsys):
    from pursue_index.ingest_scope import _bytes_changed_ids

    code, out = env.run(capsys)  # no meta.json: nothing recorded
    assert code == 0 and "unverifiable provenance" in out
    assert list(_bytes_changed_ids({CARD: NEW}, {}, {})) == []


def test_pdf_card_with_no_registry_row_is_listed_not_silently_skipped(env, capsys):
    env.registry.write_text("")
    code, out = env.run(capsys)
    assert code == 0
    assert f"PDF card with no registry PDF row: {CARD}" in out and "unregistered: 1" in out


def test_missing_registry_fails_closed(env, capsys):
    env.registry.unlink()
    code, out = env.run(capsys)
    assert code == 1 and "registry" in out and "missing" in out


@pytest.mark.parametrize("bad", ["../x", "/etc", "ABCDEF0123456789", "abc", "7d1b50162c29378"])
def test_invalid_manifest_card_id_fails_before_any_path_is_built(env, capsys, bad):
    env.manifest.write_text(json.dumps({"cards": [{"card_id": bad, "asset_type": "PDF"}]}))
    code, out = env.run(capsys)
    assert code == 1 and "ERROR" in out


def test_unreadable_meta_fails_closed(env, capsys):
    d = env.data_root / "ocr" / CARD
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{nope")
    code, _ = env.run(capsys)
    assert code == 1


def test_missing_data_root_fails_closed_and_says_what_to_set(env, capsys):
    shutil.rmtree(env.data_root)
    code, out = env.run(capsys)
    assert code == 1
    assert "PURSUE_DATA_ROOT must point at the data root containing ocr/" in out
    assert str(env.data_root) in out


def test_non_pdf_cards_are_ignored(env, capsys):
    env.manifest.write_text(json.dumps({"cards": [{"card_id": CARD, "asset_type": "VID"}]}))
    env.registry.write_text(
        json.dumps({"card_id": CARD, "byte_sha256": NEW, "current_key": f"{CARD}.mp4"}) + "\n"
    )
    env.meta(OLD)
    code, _ = env.run(capsys)
    assert code == 0


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_gate_is_in_ship_ready_right_after_release_completeness():
    proc = subprocess.run(
        ["make", "-n", "ship-ready"], cwd=_REPO_ROOT, capture_output=True, text=True,
        check=False, timeout=60,
    )
    lines = [ln for ln in proc.stdout.splitlines() if "scripts/check_" in ln]
    assert "check_release_completeness.py" in lines[0]
    assert "check_ocr_input_freshness.py" in lines[1]
