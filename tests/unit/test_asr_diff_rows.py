"""Shared AUD row logic behind the ``asr-diff run`` preview and the ``asr-diff live`` plan."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.card_id import InvalidCardIdError
from pursue_index.cli import asr_diff_cli, asr_diff_live_cli
from pursue_index.cli.commands import app
from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.transcribe import asr_diff_live
from pursue_index.transcribe import asr_diff_sidecar as sidecar
from pursue_index.transcribe.asr_diff_rows import aud_card_ids, row_duration

runner = CliRunner()
CID = "a1" * 8


def _manifest(tmp_path: Path, card_ids: list[str]) -> Path:
    path = tmp_path / "m.json"
    path.write_text(Manifest(
        source_url="https://www.war.gov/uap-csv.csv", fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=[CardMetadata(card_id=c, title=f"AUD {c}", asset_type="AUD", agency="NASA")
               for c in card_ids],
    ).model_dump_json(by_alias=True))
    return path


def _meta(tmp_path: Path, card_id: str, meta: dict) -> Path:
    card_dir = tmp_path / "ocr" / card_id
    card_dir.mkdir(parents=True, exist_ok=True)
    (card_dir / "meta.json").write_text(json.dumps(
        {"card_id": card_id, "engine": "assemblyai", "status": "ok", **meta}))
    return card_dir


def _preview(tmp_path: Path, manifest: Path, engine_b: str = "fake") -> str:
    result = runner.invoke(app, [
        "transcribe", "asr-diff", "run", "--manifest", str(manifest),
        "--out", str(tmp_path / "ocr"), "--engine-b", engine_b, "--rate-usd-per-minute", "1",
    ])
    assert result.exit_code == 0, result.output
    return " ".join(result.output.split())


# -- row 2: one duration fallback ------------------------------------------------

@pytest.mark.parametrize(("meta", "row", "want"), [
    ({"audio_duration_s": 90.0}, {}, 90.0),                                   # single-row, top level
    ({"audio_duration_s": 90.0, "rows": [{"audio_duration_s": 30.0}]},
     {"audio_duration_s": 30.0}, 30.0),                                       # row value wins
    ({"audio_duration_s": 90.0, "rows": [{"audio_duration_s": 0.0}]},
     {"audio_duration_s": 0.0}, 0.0),                                         # an explicit 0 is kept
    ({"audio_duration_s": 90.0, "rows": [{}, {}]}, {}, 0.0),                  # multi-row: no top-level fallback
    ({"rows": [{"audio_duration_s": 40.0}, {}]}, {"audio_duration_s": 40.0}, 40.0),
    ({}, {}, 0.0),                                                            # missing everywhere
    ({}, {"audio_duration_s": "n/a"}, 0.0),                                   # unreadable
    ({}, {"audio_duration_s": -5.0}, 0.0),                                    # negative clamps to 0
])
def test_row_duration(meta: dict, row: dict, want: float) -> None:
    assert row_duration(meta, row) == want


def test_preview_keeps_an_explicit_zero_row_duration(tmp_path: Path) -> None:
    """The old inline fallback read a row's 0.0 as missing and costed the top level."""
    _meta(tmp_path, CID, {"audio_duration_s": 600.0, "rows": [{"row_key": "", "audio_duration_s": 0.0}]})
    out = _preview(tmp_path, _manifest(tmp_path, [CID]))
    assert "total projected $0.00" in out


def test_preview_survives_an_unreadable_duration(tmp_path: Path) -> None:
    _meta(tmp_path, CID, {"rows": [{"row_key": "", "audio_duration_s": "n/a"}]})
    out = _preview(tmp_path, _manifest(tmp_path, [CID]))
    assert "total projected $0.00" in out


def test_preview_and_live_plan_agree_on_durations(tmp_path: Path) -> None:
    cases = {"b1" * 8: {"audio_duration_s": 120.0},
             "b2" * 8: {"rows": [{"row_key": "", "audio_duration_s": 0.0}], "audio_duration_s": 60.0},
             "b3" * 8: {}}
    for cid, meta in cases.items():
        _meta(tmp_path, cid, meta)
    out = _preview(tmp_path, _manifest(tmp_path, list(cases)))
    plan = asr_diff_live.plan_rows([(c, "", None) for c in cases], tmp_path / "ocr",
                                   tmp_path / "audio", "fake")
    total_min = sum(r.duration_s for r in plan if r.state == "pending") / 60
    assert f"total projected ${total_min:.2f}" in out


# -- row 3: public row/card selection ------------------------------------------

def test_aud_card_ids_selects_aud_cards_and_honours_the_filter(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text(Manifest(
        source_url="https://www.war.gov/uap-csv.csv", fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=[CardMetadata(card_id="c1" * 8, title="a", asset_type="AUD", agency="NASA"),
               CardMetadata(card_id="c2" * 8, title="b", asset_type="VID", agency="NASA"),
               CardMetadata(card_id="c3" * 8, title="c", asset_type="AUD", agency="NASA")],
    ).model_dump_json(by_alias=True))
    assert aud_card_ids(path, None) == ["c1" * 8, "c3" * 8]
    assert aud_card_ids(path, f" {'c3' * 8} , {'c2' * 8},") == ["c3" * 8]
    with pytest.raises(InvalidCardIdError):
        aud_card_ids(path, "not-a-card")


def test_both_clis_use_the_public_selection() -> None:
    assert not hasattr(asr_diff_cli, "_aud_card_ids")
    assert not hasattr(asr_diff_live_cli, "_aud_card_ids")
    assert asr_diff_cli.aud_card_ids is aud_card_ids
    assert asr_diff_live_cli.aud_card_ids is aud_card_ids


# -- row 1: one "already compared" check ---------------------------------------

def _compared(card_dir: Path, engine_b: str, **extra: object) -> None:
    (card_dir / sidecar.SIDECAR_FILE).write_text(json.dumps({
        "row_key": "", "engine_a": "assemblyai", "engine_b": engine_b,
        "status": "judged", "agreement": 1.0, **extra}) + "\n")


def _plan_split(tmp_path: Path, card_ids: list[str], engine_b: str = "fake") -> dict[str, float]:
    plan = asr_diff_live.plan_rows([(c, "", None) for c in card_ids], tmp_path / "ocr",
                                   tmp_path / "audio", engine_b)
    return asr_diff_live.estimate(plan)


def test_a_multi_row_card_is_skipped_by_the_preview_as_by_the_live_plan(tmp_path: Path) -> None:
    """The old preview costed each row of a multi-row card; the live plan skips them."""
    _meta(tmp_path, CID, {"rows": [{"row_key": "r1", "audio_duration_s": 60.0},
                                   {"row_key": "r2", "audio_duration_s": 60.0}]})
    out = _preview(tmp_path, _manifest(tmp_path, [CID]))
    split = _plan_split(tmp_path, [CID])
    assert split["pending"] == 0 and split["skipped"] == 2
    assert "0 row(s) would be compared" in out
    assert "0 already compared, 2 skipped" in out


def test_a_comparison_of_older_pages_is_pending_in_the_preview_as_in_the_live_plan(
    tmp_path: Path,
) -> None:
    """The old preview ignored the pages digest, so a comparison of pages since
    re-written still read as compared there while the live plan re-runs it."""
    card_dir = _meta(tmp_path, CID, {"audio_duration_s": 60.0})
    (card_dir / "pages.jsonl").write_text(json.dumps({"page": 1, "text": "new text"}) + "\n")
    _compared(card_dir, "fake", pages_digest="0" * 64)
    out = _preview(tmp_path, _manifest(tmp_path, [CID]))
    split = _plan_split(tmp_path, [CID])
    assert split["pending"] == 1
    assert "1 row(s) would be compared" in out


def test_preview_reports_the_live_plans_split(tmp_path: Path) -> None:
    ids = ["d1" * 8, "d2" * 8, "d3" * 8, "d4" * 8]
    _meta(tmp_path, ids[0], {"audio_duration_s": 60.0})                      # pending
    _compared(_meta(tmp_path, ids[1], {"audio_duration_s": 60.0}), "fake")   # compared
    _meta(tmp_path, ids[2], {"rows": [{"row_key": "a"}, {"row_key": "b"}]})  # 2 skipped
    # ids[3]: no transcript -> skipped
    out = _preview(tmp_path, _manifest(tmp_path, ids))
    s = _plan_split(tmp_path, ids)
    assert (s["pending"], s["compared"], s["skipped"]) == (1, 1, 3)
    assert "1 row(s) would be compared" in out
    assert "1 already compared, 3 skipped" in out


def test_a_card_listed_twice_is_one_row_in_the_preview_as_in_the_live_plan(tmp_path: Path) -> None:
    _meta(tmp_path, CID, {"audio_duration_s": 60.0})
    manifest = _manifest(tmp_path, [CID, CID])
    assert aud_card_ids(manifest, None) == [CID]
    assert "1 row(s) would be compared" in _preview(tmp_path, manifest)


# -- row 4: the cap-stop notice names the row that stopped the pass -------------

class _RefuseThird:
    """A budget that affords two rows and refuses the third."""

    def __init__(self, cap_usd: float) -> None:
        self.cap_usd, self.spent_usd, self.asked = cap_usd, 0.0, 0

    def can_afford(self, cost_usd: float) -> bool:
        self.asked += 1
        return self.asked < 3

    def charge(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd


def test_the_cap_stop_notice_names_the_row_that_stopped_the_pass(tmp_path, monkeypatch) -> None:
    ids = ["e1" * 8, "e2" * 8, "e3" * 8, "e4" * 8]
    audio = tmp_path / "audio"
    (audio / "by-card").mkdir(parents=True)
    for cid in ids:
        card_dir = _meta(tmp_path, cid, {"audio_duration_s": 60.0})
        (card_dir / "pages.jsonl").write_text(json.dumps({"page": 1, "text": "roger"}) + "\n")
        (audio / "by-card" / f"{cid}.mp4").write_bytes(b"x")
    plan = asr_diff_live.plan_rows([(c, "", None) for c in ids], tmp_path / "ocr", audio, "fake")
    assert [r.state for r in plan] == ["pending"] * 4
    monkeypatch.setattr(asr_diff_live, "AsrDiffBudget", _RefuseThird)
    heard: list[Path] = []
    notices: list[tuple[str, str]] = []
    reports = asr_diff_live.run_pending(
        plan, tmp_path / "ocr", "fake", lambda p: heard.append(p) or "roger",
        on_row=lambda row, report, problem: notices.append((row.card_id, problem)),
    )
    assert len(reports) == 2 and len(heard) == 2
    assert (ids[2], "stopped: budget cap reached") in notices
    assert all(cid != ids[0] for cid, problem in notices if problem.startswith("stopped"))
