"""``pursue vision run`` CLI surface.

Default run is the *verify-before-spend preflight*: it selects eligible items,
diffs against produced sidecars, and exits non-zero on a coverage shortfall —
no API calls. Live work is reached only by naming it: ``--live-smoke <card_id>``
for a single card, ``--run`` for the operator-attended bulk pass over a
worklist. Both are exercised here with the client/render seams monkeypatched so
the suite (and CI) never spends.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.scrape.types import CardMetadata, Manifest

runner = CliRunner()


def _write_manifest(path: Path, cards: list[CardMetadata]) -> None:
    m = Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )
    path.write_text(m.model_dump_json(by_alias=True))


def _img_card(card_id: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id, title=f"IMG {card_id}", asset_type="IMG", agency="FBI",
        asset_url="https://media.defense.gov/x.jpg", asset_filename=f"{card_id}.jpg",
    )


def test_preflight_exits_nonzero_on_shortfall(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA")])
    result = runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "obs")],
    )
    assert result.exit_code == 1
    assert "imgA" in result.stdout or "1" in result.stdout


def test_preflight_passes_when_covered(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "obs"
    out.mkdir()
    (out / "imgA.json").write_text(
        json.dumps(
            {
                "card_id": "imgA", "schema_version": 1,
                "our_pass": {"model": "claude-opus-4-8"},
                "pages": [{"page": 1, "observations": []}],
            }
        )
    )
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA")])
    result = runner.invoke(
        app, ["vision", "run", "--manifest", str(manifest), "--out", str(out)]
    )
    assert result.exit_code == 0


def test_live_smoke_produces_single_sidecar(tmp_path: Path, monkeypatch) -> None:
    import pursue_index.vision.client as client_mod
    import pursue_index.vision.render as render_mod

    calls: list[str] = []

    def fake_examine(_img, **_kw):
        calls.append("x")
        return {"image_type": "photo", "description": "smoke desc",
                "visible_text": "", "observations": []}

    monkeypatch.setattr(client_mod, "examine_image", fake_examine)
    monkeypatch.setattr(render_mod, "load_image_for", lambda item, **kw: object())

    out = tmp_path / "obs"
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA"), _img_card("imgB")])
    result = runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--out", str(out),
         "--live-smoke", "imgA"],
    )
    assert result.exit_code == 0
    # Exactly one card examined (the smoke target), not the whole worklist.
    assert len(calls) == 1
    assert (out / "imgA.json").exists()
    assert not (out / "imgB.json").exists()


def test_live_smoke_unknown_card_errors(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA")])
    result = runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "o"),
         "--live-smoke", "ghost"],
    )
    assert result.exit_code != 0


def _patch_seams(monkeypatch, examine) -> None:
    """Replace the two spending seams so the CLI's live paths stay offline."""
    import pursue_index.vision.client as client_mod
    import pursue_index.vision.render as render_mod

    monkeypatch.setattr(client_mod, "examine_image", examine)
    monkeypatch.setattr(render_mod, "load_image_for", lambda item, **kw: item)


def _examination(_img: object, **_kw) -> dict:
    return {"image_type": "photo", "description": "bulk desc",
            "visible_text": "", "observations": []}


def test_bulk_run_produces_a_sidecar_for_every_eligible_item(
    tmp_path: Path, monkeypatch
) -> None:
    """``--run`` covers the whole worklist, one sidecar per eligible card."""
    _patch_seams(monkeypatch, _examination)
    out = tmp_path / "obs"
    manifest = tmp_path / "m.json"
    _write_manifest(
        manifest, [_img_card("imgA"), _img_card("imgB"), _img_card("imgC")]
    )
    result = runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--out", str(out), "--run"],
    )
    assert result.exit_code == 0, result.output
    assert {p.name for p in out.glob("*.json")} == {
        "imgA.json", "imgB.json", "imgC.json"
    }
    assert "3 produced / 3 eligible" in result.stdout


def test_bulk_run_honors_the_worklist_scope(tmp_path: Path, monkeypatch) -> None:
    """A worklist scopes the bulk pass to the cards it names."""
    _patch_seams(monkeypatch, _examination)
    out = tmp_path / "obs"
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA"), _img_card("imgB")])
    worklist = tmp_path / "w.txt"
    worklist.write_text("imgA\n")
    result = runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--out", str(out),
         "--worklist", str(worklist), "--run"],
    )
    assert result.exit_code == 0, result.output
    assert (out / "imgA.json").exists()
    assert not (out / "imgB.json").exists()


def test_bulk_run_counts_a_failed_item_and_exits_nonzero(
    tmp_path: Path, monkeypatch
) -> None:
    """One item's failure is counted; its siblings still land, the run reports short."""
    def flaky(item, **_kw) -> dict:
        if getattr(item, "card_id", "") == "imgB":
            raise RuntimeError("image could not be examined")
        return _examination(item)

    _patch_seams(monkeypatch, flaky)
    out = tmp_path / "obs"
    manifest = tmp_path / "m.json"
    _write_manifest(
        manifest, [_img_card("imgA"), _img_card("imgB"), _img_card("imgC")]
    )
    result = runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--out", str(out), "--run"],
    )
    assert result.exit_code == 1
    assert (out / "imgA.json").exists()
    assert (out / "imgC.json").exists()
    assert not (out / "imgB.json").exists()
    assert "1 item(s) could not be examined" in result.stdout
    assert "imgB" in result.stdout


def test_default_invocation_previews_coverage_and_makes_no_calls(
    tmp_path: Path, monkeypatch
) -> None:
    """Neither flag: coverage preview only — the spending seams stay untouched."""
    calls: list[str] = []

    def forbidden(item, **_kw) -> dict:
        calls.append("called")
        raise AssertionError("the default invocation must not examine anything")

    _patch_seams(monkeypatch, forbidden)
    out = tmp_path / "obs"
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA"), _img_card("imgB")])
    result = runner.invoke(
        app, ["vision", "run", "--manifest", str(manifest), "--out", str(out)]
    )
    assert result.exit_code == 1  # two eligible, none produced
    assert calls == []
    assert not out.exists() or list(out.glob("*.json")) == []


def test_run_and_live_smoke_together_are_refused(tmp_path: Path, monkeypatch) -> None:
    """The two live paths are distinct; naming both is ambiguous, so it is refused."""
    _patch_seams(monkeypatch, _examination)
    out = tmp_path / "obs"
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA")])
    result = runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--out", str(out),
         "--run", "--live-smoke", "imgA"],
    )
    assert result.exit_code == 2
    assert not out.exists() or list(out.glob("*.json")) == []
