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
from pursue_index.vision.sidecar import DEFAULT_CONTEXT, validate_sidecar
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


@pytest.fixture(autouse=True)
def _assets_resolve(monkeypatch) -> None:
    """These tests are about superseding, not byte lookup: let every card's
    asset path resolve (the resolver itself is covered in test_vision_img_source)."""
    from pursue_index.download.downloader import asset_path_for
    from pursue_index.vision import redescribe

    monkeypatch.setattr(
        redescribe, "resolve_img_path", lambda card, registry=None: (asset_path_for(card), None)
    )


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
    _write_sidecar(out, "a1a1a1a1a1a1a1a1")
    _write_sidecar(out, "d4d4d4d4d4d4d4d4", pages=[{"page": 3, "observations": [{"claim": "o"}]}])
    # Text-bearing PDF: the eligibility filter would never pick this page.
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1"), _pdf_card("d4d4d4d4d4d4d4d4")],
                          ["a1a1a1a1a1a1a1a1", "d4d4d4d4d4d4d4d4"], ["--confirm-live"])
    assert result.exit_code == 0, result.output
    assert sorted((i.card_id, i.page) for i in spy.calls) == [("a1a1a1a1a1a1a1a1", 1), ("d4d4d4d4d4d4d4d4", 3)]
    assert _read(tmp_path, "d4d4d4d4d4d4d4d4")["pages"][0]["page"] == 3
    assert _read(tmp_path, "a1a1a1a1a1a1a1a1")["pages"][0]["observations"][0]["claim"] == "new claim"


def test_new_pass_and_curated_fields_preserved(tmp_path, monkeypatch):
    old = _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    result, _ = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1")], ["a1a1a1a1a1a1a1a1"],
                        ["--confirm-live"])
    assert result.exit_code == 0, result.output
    new = _read(tmp_path, "a1a1a1a1a1a1a1a1")
    assert new["our_pass"]["model"] == "claude-opus-4-8"
    assert new["our_pass"]["method"] == "vision-run"
    assert new["our_pass"]["context"] == DEFAULT_CONTEXT
    assert new["our_pass"]["described_at"]
    for key in CURATED:
        assert new[key] == old[key], key
    validate_sidecar(new)


def test_old_pass_lands_in_superseded_passes(tmp_path, monkeypatch):
    old = _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    result, _ = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1")], ["a1a1a1a1a1a1a1a1"],
                        ["--confirm-live"])
    assert result.exit_code == 0, result.output
    sup = _read(tmp_path, "a1a1a1a1a1a1a1a1")["superseded_passes"]
    assert len(sup) == 1
    assert sup[0]["our_pass"] == OLD_PASS
    assert sup[0]["pages"] == old["pages"]
    assert sup[0]["superseded_at"]


def test_second_redescribe_appends_rather_than_replaces(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    for _ in range(2):
        result, _spy = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1")], ["a1a1a1a1a1a1a1a1"],
                               ["--confirm-live"])
        assert result.exit_code == 0, result.output
    sup = _read(tmp_path, "a1a1a1a1a1a1a1a1")["superseded_passes"]
    assert len(sup) == 2
    assert sup[0]["our_pass"] == OLD_PASS  # the first entry survives
    assert sup[1]["our_pass"]["model"] == "claude-opus-4-8"
    assert sup[1]["pages"][0]["observations"][0]["claim"] == "new claim"


def test_missing_sidecar_is_refused_by_name_before_any_call(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1"), _img_card("b2b2b2b2b2b2b2b2")],
                          ["a1a1a1a1a1a1a1a1", "b2b2b2b2b2b2b2b2"], ["--confirm-live"])
    assert result.exit_code == 2
    assert "b2b2b2b2b2b2b2b2" in result.output and "--run" in result.output
    assert spy.calls == []
    assert "superseded_passes" not in _read(tmp_path, "a1a1a1a1a1a1a1a1")


def test_budget_is_required(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1")], ["a1a1a1a1a1a1a1a1"],
                          ["--confirm-live"], budget=None)
    assert result.exit_code == 2 and "--budget-usd" in result.output
    assert spy.calls == []


def test_budget_is_enforced_and_a_cut_off_card_is_left_untouched(tmp_path, monkeypatch):
    out = tmp_path / "o"
    two = [{"page": 1, "observations": [{"claim": "o1"}]},
           {"page": 2, "observations": [{"claim": "o2"}]}]
    _write_sidecar(out, "c3c3c3c3c3c3c3c3", pages=two)
    before = (out / "c3c3c3c3c3c3c3c3.json").read_text("utf-8")
    # The first call meters ~$0.15, so a second worst-case call (~$0.18) no
    # longer fits under $0.25 and the run must stop before making it.
    dear = _Spy()
    dear.output_tokens = 2000
    result, spy = _invoke(tmp_path, monkeypatch, [_pdf_card("c3c3c3c3c3c3c3c3")], ["c3c3c3c3c3c3c3c3"],
                          ["--confirm-live"], dear, budget="0.25")
    assert result.exit_code == 1, result.output
    assert len(spy.calls) == 1
    # A half-described card must not replace the whole one.
    assert (out / "c3c3c3c3c3c3c3c3.json").read_text("utf-8") == before


def test_ci_is_refused(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    spy = _Spy()
    _patch_seams(monkeypatch, spy)
    monkeypatch.setenv("CI", "true")
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("a1a1a1a1a1a1a1a1")])
    result = runner.invoke(app, [
        "vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "o"),
        "--redescribe", "--worklist", str(_worklist(tmp_path, ["a1a1a1a1a1a1a1a1"])),
        "--budget-usd", "3", "--confirm-live"])
    assert result.exit_code == 2 and "CI" in result.output
    assert spy.calls == []


def test_without_confirm_live_it_is_a_no_spend_preflight(tmp_path, monkeypatch):
    out = tmp_path / "o"
    _write_sidecar(out, "a1a1a1a1a1a1a1a1")
    _write_sidecar(out, "d4d4d4d4d4d4d4d4", pages=[{"page": 2, "observations": [{"claim": "o"}]},
                                       {"page": 5, "observations": [{"claim": "o"}]}])
    before = {p.name: p.read_text("utf-8") for p in out.glob("*.json")}
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1"), _pdf_card("d4d4d4d4d4d4d4d4")],
                          ["a1a1a1a1a1a1a1a1", "d4d4d4d4d4d4d4d4"], [])
    assert result.exit_code == 0, result.output
    assert spy.calls == []
    assert "2 card(s) / 3 page(s)" in result.output
    assert "estimated cost" in result.output
    assert {p.name: p.read_text("utf-8") for p in out.glob("*.json")} == before


def test_preflight_fails_when_estimate_exceeds_budget(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1")], ["a1a1a1a1a1a1a1a1"], [],
                          budget="0.001")
    assert result.exit_code == 1 and spy.calls == []


def test_stale_worklist_is_refused(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    _patch_seams(monkeypatch, _Spy())
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("a1a1a1a1a1a1a1a1")])
    result = runner.invoke(app, [
        "vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "o"),
        "--redescribe", "--worklist", str(_worklist(tmp_path, ["a1a1a1a1a1a1a1a1"], "f" * 64)),
        "--budget-usd", "3", "--confirm-live"])
    assert result.exit_code == 1


@pytest.mark.parametrize("other", ["--run", "--live"])
def test_redescribe_is_exclusive_with_other_live_paths(tmp_path, monkeypatch, other):
    _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1")], ["a1a1a1a1a1a1a1a1"],
                          ["--confirm-live", other])
    assert result.exit_code == 2 and spy.calls == []


def test_redescribe_requires_a_worklist(tmp_path, monkeypatch):
    _patch_seams(monkeypatch, _Spy())
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("a1a1a1a1a1a1a1a1")])
    result = runner.invoke(app, ["vision", "run", "--manifest", str(manifest),
                                 "--redescribe", "--budget-usd", "3", "--confirm-live"])
    assert result.exit_code == 2 and "--worklist" in result.output


def test_empty_result_leaves_card_untouched(tmp_path, monkeypatch):
    out = tmp_path / "o"
    _write_sidecar(out, "a1a1a1a1a1a1a1a1")
    before = (out / "a1a1a1a1a1a1a1a1.json").read_text("utf-8")
    blank = _Spy()
    blank.__class__ = type("_Blank", (_Spy,), {"__call__": lambda self, item, **kw: {
        "image_type": "photo", "description": "", "visible_text": "", "observations": []}})
    result, _ = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1")], ["a1a1a1a1a1a1a1a1"],
                        ["--confirm-live"], blank)
    assert result.exit_code == 1
    assert (out / "a1a1a1a1a1a1a1a1.json").read_text("utf-8") == before


def test_sidecar_schema_accepts_and_checks_superseded_passes():
    base = {"card_id": "c", "schema_version": 1, "our_pass": {"model": "m"},
            "pages": [{"page": 1, "observations": []}]}
    validate_sidecar(base)  # old sidecars still validate unchanged
    validate_sidecar({**base, "superseded_passes": [
        {"our_pass": {"model": "m"}, "pages": [{"page": 1}], "superseded_at": "t"}]})
    with pytest.raises(Exception):  # noqa: B017 - pydantic.ValidationError
        validate_sidecar({**base, "superseded_passes": [{"our_pass": {"model": "m"}}]})


@pytest.mark.parametrize("bad", [None, "two", True, 1.5])
def test_malformed_sidecar_page_is_refused_by_name_others_still_planned(
    tmp_path, bad
):
    from datetime import UTC, datetime

    from pursue_index.scrape.types import Manifest
    from pursue_index.vision.redescribe import plan_redescribe

    out = tmp_path / "obs"
    out.mkdir()
    page = {"observations": []} if bad is None else {"page": bad, "observations": []}
    (out / "badc0de0badc0de0.json").write_text(json.dumps(
        {"card_id": "badc0de0badc0de0", "our_pass": {}, "pages": [page]}))
    (out / "600d600d600d600d.json").write_text(json.dumps(
        {"card_id": "600d600d600d600d", "our_pass": {},
         "pages": [{"page": 1, "observations": []}]}))
    cards = [_img_card("badc0de0badc0de0"), _img_card("600d600d600d600d")]
    manifest = Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC), csv_sha256="0" * 64, cards=cards,
    )
    plan = plan_redescribe(manifest, {"badc0de0badc0de0", "600d600d600d600d"}, out)
    assert "badc0de0badc0de0" not in plan.items_by_card
    assert any("badc0de0badc0de0" in r and "page" in r for r in plan.refusals)
    assert "600d600d600d600d" in plan.items_by_card


def test_superseded_context_never_appears_in_the_new_pass(tmp_path, monkeypatch):
    from pursue_index.vision.sidecar import build_sidecar

    _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    result, _ = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1")],
                        ["a1a1a1a1a1a1a1a1"], ["--confirm-live"])
    assert result.exit_code == 0, result.output
    new = _read(tmp_path, "a1a1a1a1a1a1a1a1")
    assert OLD_PASS["context"] not in json.dumps(new["our_pass"])
    fresh = build_sidecar(card_id="x", title="t", model="m", pages=[])
    assert new["our_pass"]["context"] == fresh["our_pass"]["context"]
    # the old context is kept where it belongs
    assert new["superseded_passes"][0]["our_pass"]["context"] == OLD_PASS["context"]


def test_written_sidecar_ends_with_a_newline(tmp_path, monkeypatch):
    _write_sidecar(tmp_path / "o", "a1a1a1a1a1a1a1a1")
    result, _ = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1")],
                        ["a1a1a1a1a1a1a1a1"], ["--confirm-live"])
    assert result.exit_code == 0, result.output
    text = (tmp_path / "o" / "a1a1a1a1a1a1a1a1.json").read_text("utf-8")
    assert text.endswith("}\n") and not text.endswith("\n\n")


def _plan_for(tmp_path, ids):
    from datetime import UTC, datetime

    from pursue_index.scrape.types import Manifest
    from pursue_index.vision.redescribe import plan_redescribe

    manifest = Manifest(
        source_url="https://www.war.gov/uap-csv.csv", fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64, cards=[_img_card(i) for i in ids],
    )
    return plan_redescribe(manifest, set(ids), tmp_path / "o")


def _redescribe(plan, tmp_path, calls, **kw):
    from pursue_index.vision.redescribe import redescribe_vision

    def examine(item, **_k):
        calls.append(item)
        return {"image_type": "p", "description": "d", "visible_text": "",
                "observations": [{"claim": "c"}], "_usage": {"input_tokens": 10,
                                                              "output_tokens": 10}}

    return redescribe_vision(plan, tmp_path / "o", examine_fn=examine,
                             load_image_fn=lambda i: i, budget_usd=3.0, **kw)


def test_each_card_gets_the_time_of_its_own_examination(tmp_path):
    from datetime import UTC, datetime, timedelta

    ids = ["a1a1a1a1a1a1a1a1", "b2b2b2b2b2b2b2b2"]
    for i in ids:
        _write_sidecar(tmp_path / "o", i)
    ticks = iter(datetime(2026, 11, 22, tzinfo=UTC) + timedelta(minutes=m) for m in range(10))
    calls: list = []
    _redescribe(_plan_for(tmp_path, ids), tmp_path, calls, clock=lambda: next(ticks))
    first, second = (_read(tmp_path, i) for i in ids)
    assert first["our_pass"]["described_at"] != second["our_pass"]["described_at"]
    assert first["our_pass"]["described_at"] < second["our_pass"]["described_at"]
    for doc in (first, second):
        assert doc["superseded_passes"][0]["superseded_at"] == doc["our_pass"]["described_at"]


@pytest.mark.parametrize("bad", ["../x", "A1A1A1A1A1A1A1A1", "abc", "a1a1a1a1a1a1a1a1/..",
                                 "a1a1a1a1a1a1a1a1\n", ""])
def test_worklist_card_id_must_be_16_lowercase_hex(tmp_path, monkeypatch, bad):
    from pursue_index.vision import redescribe

    (tmp_path / "x.json").write_text("{}")  # what "../x" would reach from o/
    seen: list = []
    monkeypatch.setattr(redescribe, "_read_sidecar",
                        lambda path: seen.append(path) or "unreadable")
    plan = redescribe.plan_redescribe(_plan_manifest(["a1a1a1a1a1a1a1a1"]), {bad}, tmp_path / "o")
    assert seen == []
    assert len(plan.refusals) == 1 and repr(bad) in plan.refusals[0]
    assert "16 lowercase hex" in plan.refusals[0]


def _plan_manifest(ids):
    from datetime import UTC, datetime

    from pursue_index.scrape.types import Manifest

    return Manifest(source_url="https://www.war.gov/uap-csv.csv",
                    fetched_at=datetime.now(UTC), csv_sha256="0" * 64,
                    cards=[_img_card(i) for i in ids])


def test_worklist_card_id_must_be_in_the_manifest(tmp_path, monkeypatch):
    from pursue_index.vision import redescribe

    seen: list = []
    monkeypatch.setattr(redescribe, "_read_sidecar",
                        lambda path: seen.append(path) or "unreadable")
    plan = redescribe.plan_redescribe(
        _plan_manifest(["a1a1a1a1a1a1a1a1"]), {"f0f0f0f0f0f0f0f0"}, tmp_path / "o")
    assert seen == []
    assert "f0f0f0f0f0f0f0f0" in plan.refusals[0] and "manifest" in plan.refusals[0]


def test_cli_refuses_a_path_traversal_id_by_name(tmp_path, monkeypatch):
    (tmp_path / "x.json").write_text("{}")
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card("a1a1a1a1a1a1a1a1")],
                          ["../x"], ["--confirm-live"])
    assert result.exit_code == 2 and "../x" in result.output
    assert spy.calls == []


def test_a_sidecar_that_went_bad_since_planning_is_refused_for_free(tmp_path):
    ids = ["a1a1a1a1a1a1a1a1", "b2b2b2b2b2b2b2b2", "c3c3c3c3c3c3c3c3"]
    for i in ids:
        _write_sidecar(tmp_path / "o", i)
    plan = _plan_for(tmp_path, ids)
    (tmp_path / "o" / "a1a1a1a1a1a1a1a1.json").write_text("{not json")
    # valid JSON that the dry supersede rejects (superseded_passes is malformed)
    _write_sidecar(tmp_path / "o", "b2b2b2b2b2b2b2b2", superseded_passes=[{"our_pass": 1}])
    bad_a = (tmp_path / "o" / "a1a1a1a1a1a1a1a1.json").read_text("utf-8")
    bad_b = (tmp_path / "o" / "b2b2b2b2b2b2b2b2.json").read_text("utf-8")
    calls: list = []
    report = _redescribe(plan, tmp_path, calls)
    assert [c.card_id for c in calls] == ["c3c3c3c3c3c3c3c3"]
    named = " ".join(f"{k[0]} {why}" for k, why in report.failures)
    assert "a1a1a1a1a1a1a1a1" in named and "b2b2b2b2b2b2b2b2" in named
    assert (tmp_path / "o" / "a1a1a1a1a1a1a1a1.json").read_text("utf-8") == bad_a
    assert (tmp_path / "o" / "b2b2b2b2b2b2b2b2.json").read_text("utf-8") == bad_b
    assert "superseded_passes" in _read(tmp_path, "c3c3c3c3c3c3c3c3")
    assert report.spent_usd < 0.1  # only the one card's call
