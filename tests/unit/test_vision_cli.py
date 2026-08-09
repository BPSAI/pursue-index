"""``pursue vision run`` CLI surface.

Default run is the *verify-before-spend preflight*: it selects eligible items,
diffs against produced sidecars, and exits non-zero on a coverage shortfall —
no API calls. ``--live-smoke <card_id>`` is the ONLY live path; here it is
exercised with the client/render seams monkeypatched so the suite (and CI)
never spends.
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
