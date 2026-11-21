"""``pursue vision run --redescribe``: re-examine exactly the listed cards' pages.

Every test stubs the vision client and the render seam, so none can spend. The
mode bypasses the image-only eligibility filter and the already-produced skip,
and it supersedes (never overwrites) the old provenance: the previous
``our_pass`` + ``pages`` are appended to ``superseded_passes`` while every
curated key is left alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.scrape.types import CardMetadata
from pursue_index.vision.sidecar import validate_sidecar
from tests.unit.test_vision_cli import _img_card, _patch_seams, _write_manifest

runner = CliRunner()
TRANCHE = "0" * 64  # what _write_manifest stamps as csv_sha256

OLD_PASS = {
    "model": "claude-opus-4-7",
    "method": "direct-examination-via-claude-code",
    "context": "phase2-multi-frame-cluster-with-narrative-grounding",
}
CURATED = {
    "title": "FBI Photo A004",
    "virin": "260508-O-D0360-1024",
    "schema_version": 1,
    "operator": "primary",
    "decided_at": "2026-05-25T17:00:00+00:00",
    "session_id": "phase2-helicopter-case-2026-05-25",
    "prior_pass": {"model": "someone-else", "note": "kept"},
    "cluster_label": "helicopter-case-2025-imagery-a-series",
    "cross_card_refs": ["x1", "x2"],
    "sensor_system_note": "A-series note",
}


def _pdf_card(card_id: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id, title=f"PDF {card_id}", asset_type="PDF", agency="FBI",
        asset_url="https://media.defense.gov/x.pdf", asset_filename=f"{card_id}.pdf",
    )


def _write_sidecar(out: Path, card_id: str, pages: list[dict] | None = None,
                   **extra: object) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    doc = {
        "card_id": card_id, **CURATED, "our_pass": dict(OLD_PASS),
        "pages": pages or [{"page": 1, "observations": [{"claim": "old claim"}],
                            "narrative_grounding": "old"}],
        **extra,
    }
    (out / f"{card_id}.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


def _worklist(tmp_path: Path, ids: list[str], tranche: str = TRANCHE) -> Path:
    path = tmp_path / "wl.txt"
    path.write_text(f"# tranche: {tranche}\n" + "\n".join(ids) + "\n")
    return path


class _Spy:
    output_tokens = 300

    def __init__(self) -> None:
        self.calls: list[object] = []

    def __call__(self, item: object, **_kw: object) -> dict:
        self.calls.append(item)
        return {"image_type": "photo", "description": "new desc", "visible_text": "",
                "observations": [{"claim": "new claim"}],
                "_usage": {"input_tokens": 1500, "output_tokens": self.output_tokens}}


def _invoke(tmp_path: Path, monkeypatch, cards: list[CardMetadata], ids: list[str],
            extra: list[str], spy: _Spy | None = None, *, budget: str | None = "3.0"):
    spy = spy or _Spy()
    _patch_seams(monkeypatch, spy)
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, cards)
    args = ["vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "o"),
            "--redescribe", "--worklist", str(_worklist(tmp_path, ids))]
    if budget is not None:
        args += ["--budget-usd", budget]
    result = runner.invoke(app, [*args, *extra])
    return result, spy


def _read(tmp_path: Path, card_id: str) -> dict:
    return json.loads((tmp_path / "o" / f"{card_id}.json").read_text("utf-8"))


def test_img_and_text_bearing_pdf_cards_are_both_reexamined(tmp_path, monkeypatch):
    out = tmp_path / "o"
    _write_sidecar(out, "imgA")
    _write_sidecar(out, "pdfB", pages=[{"page": 3, "observations": [{"claim": "o"}]}])
    # Text-bearing PDF: the eligibility filter would never pick this page.
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("imgA"), _pdf_card("pdfB")],
                          ["imgA", "pdfB"], ["--confirm-live"])
    assert result.exit_code == 0, result.output
    assert sorted((i.card_id, i.page) for i in spy.calls) == [("imgA", 1), ("pdfB", 3)]
    assert _read(tmp_path, "pdfB")["pages"][0]["page"] == 3
    assert _read(tmp_path, "imgA")["pages"][0]["observations"][0]["claim"] == "new claim"


def test_new_pass_and_curated_fields_preserved(tmp_path, monkeypatch):
    old = _write_sidecar(tmp_path / "o", "imgA")
    result, _ = _invoke(tmp_path, monkeypatch, [_img_card("imgA")], ["imgA"],
                        ["--confirm-live"])
    assert result.exit_code == 0, result.output
    new = _read(tmp_path, "imgA")
    assert new["our_pass"]["model"] == "claude-opus-4-8"
    assert new["our_pass"]["method"] == "vision-run"
    assert new["our_pass"]["context"] == OLD_PASS["context"]
    assert new["our_pass"]["described_at"]
    for key in CURATED:
        assert new[key] == old[key], key
    validate_sidecar(new)


def test_old_pass_lands_in_superseded_passes(tmp_path, monkeypatch):
    old = _write_sidecar(tmp_path / "o", "imgA")
    result, _ = _invoke(tmp_path, monkeypatch, [_img_card("imgA")], ["imgA"],
                        ["--confirm-live"])
    assert result.exit_code == 0, result.output
    sup = _read(tmp_path, "imgA")["superseded_passes"]
    assert len(sup) == 1
    assert sup[0]["our_pass"] == OLD_PASS
    assert sup[0]["pages"] == old["pages"]
    assert sup[0]["superseded_at"]


def test_second_redescribe_appends_rather_than_replaces(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "imgA")
    for _ in range(2):
        result, _spy = _invoke(tmp_path, monkeypatch, [_img_card("imgA")], ["imgA"],
                               ["--confirm-live"])
        assert result.exit_code == 0, result.output
    sup = _read(tmp_path, "imgA")["superseded_passes"]
    assert len(sup) == 2
    assert sup[0]["our_pass"] == OLD_PASS  # the first entry survives
    assert sup[1]["our_pass"]["model"] == "claude-opus-4-8"
    assert sup[1]["pages"][0]["observations"][0]["claim"] == "new claim"


def test_missing_sidecar_is_refused_by_name_before_any_call(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "imgA")
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("imgA"), _img_card("imgB")],
                          ["imgA", "imgB"], ["--confirm-live"])
    assert result.exit_code == 2
    assert "imgB" in result.output and "--run" in result.output
    assert spy.calls == []
    assert "superseded_passes" not in _read(tmp_path, "imgA")


def test_budget_is_required(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "imgA")
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("imgA")], ["imgA"],
                          ["--confirm-live"], budget=None)
    assert result.exit_code == 2 and "--budget-usd" in result.output
    assert spy.calls == []


def test_budget_is_enforced_and_a_cut_off_card_is_left_untouched(tmp_path, monkeypatch):
    out = tmp_path / "o"
    two = [{"page": 1, "observations": [{"claim": "o1"}]},
           {"page": 2, "observations": [{"claim": "o2"}]}]
    _write_sidecar(out, "pdfA", pages=two)
    before = (out / "pdfA.json").read_text("utf-8")
    # The first call meters ~$0.15, so a second worst-case call (~$0.18) no
    # longer fits under $0.25 and the run must stop before making it.
    dear = _Spy()
    dear.output_tokens = 2000
    result, spy = _invoke(tmp_path, monkeypatch, [_pdf_card("pdfA")], ["pdfA"],
                          ["--confirm-live"], dear, budget="0.25")
    assert result.exit_code == 1, result.output
    assert len(spy.calls) == 1
    # A half-described card must not replace the whole one.
    assert (out / "pdfA.json").read_text("utf-8") == before


def test_ci_is_refused(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "imgA")
    spy = _Spy()
    _patch_seams(monkeypatch, spy)
    monkeypatch.setenv("CI", "true")
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA")])
    result = runner.invoke(app, [
        "vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "o"),
        "--redescribe", "--worklist", str(_worklist(tmp_path, ["imgA"])),
        "--budget-usd", "3", "--confirm-live"])
    assert result.exit_code == 2 and "CI" in result.output
    assert spy.calls == []


def test_without_confirm_live_it_is_a_no_spend_preflight(tmp_path, monkeypatch):
    out = tmp_path / "o"
    _write_sidecar(out, "imgA")
    _write_sidecar(out, "pdfB", pages=[{"page": 2, "observations": [{"claim": "o"}]},
                                       {"page": 5, "observations": [{"claim": "o"}]}])
    before = {p.name: p.read_text("utf-8") for p in out.glob("*.json")}
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("imgA"), _pdf_card("pdfB")],
                          ["imgA", "pdfB"], [])
    assert result.exit_code == 0, result.output
    assert spy.calls == []
    assert "2 card(s) / 3 page(s)" in result.output
    assert "estimated cost" in result.output
    assert {p.name: p.read_text("utf-8") for p in out.glob("*.json")} == before


def test_preflight_fails_when_estimate_exceeds_budget(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "imgA")
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("imgA")], ["imgA"], [],
                          budget="0.001")
    assert result.exit_code == 1 and spy.calls == []


def test_stale_worklist_is_refused(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "imgA")
    _patch_seams(monkeypatch, _Spy())
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA")])
    result = runner.invoke(app, [
        "vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "o"),
        "--redescribe", "--worklist", str(_worklist(tmp_path, ["imgA"], "f" * 64)),
        "--budget-usd", "3", "--confirm-live"])
    assert result.exit_code == 1


@pytest.mark.parametrize("other", ["--run", "--live"])
def test_redescribe_is_exclusive_with_other_live_paths(tmp_path, monkeypatch, other):
    _write_sidecar(tmp_path / "o", "imgA")
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("imgA")], ["imgA"],
                          ["--confirm-live", other])
    assert result.exit_code == 2 and spy.calls == []


def test_redescribe_requires_a_worklist(tmp_path, monkeypatch):
    _patch_seams(monkeypatch, _Spy())
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA")])
    result = runner.invoke(app, ["vision", "run", "--manifest", str(manifest),
                                 "--redescribe", "--budget-usd", "3", "--confirm-live"])
    assert result.exit_code == 2 and "--worklist" in result.output


def test_empty_result_leaves_card_untouched(tmp_path, monkeypatch):
    out = tmp_path / "o"
    _write_sidecar(out, "imgA")
    before = (out / "imgA.json").read_text("utf-8")
    blank = _Spy()
    blank.__class__ = type("_Blank", (_Spy,), {"__call__": lambda self, item, **kw: {
        "image_type": "photo", "description": "", "visible_text": "", "observations": []}})
    result, _ = _invoke(tmp_path, monkeypatch, [_img_card("imgA")], ["imgA"],
                        ["--confirm-live"], blank)
    assert result.exit_code == 1
    assert (out / "imgA.json").read_text("utf-8") == before


def test_sidecar_schema_accepts_and_checks_superseded_passes():
    base = {"card_id": "c", "schema_version": 1, "our_pass": {"model": "m"},
            "pages": [{"page": 1, "observations": []}]}
    validate_sidecar(base)  # old sidecars still validate unchanged
    validate_sidecar({**base, "superseded_passes": [
        {"our_pass": {"model": "m"}, "pages": [{"page": 1}], "superseded_at": "t"}]})
    with pytest.raises(Exception):  # noqa: B017 - pydantic.ValidationError
        validate_sidecar({**base, "superseded_passes": [{"our_pass": {"model": "m"}}]})
