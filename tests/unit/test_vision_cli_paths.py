"""Where ``pursue vision run`` writes, and what a live smoke reports.

The sidecar directory lives inside the checkout, so the answer must be the
same wherever the CLI is invoked from: a run started in a subdirectory has to
see the sidecars a run started at the root sees, or it reports everything
uncovered and offers to examine an already-examined corpus.

A live smoke reports the same way the sibling stage's does: a shortfall is a
non-zero exit, so an unattended caller cannot read a failed smoke as a pass.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.cli.vision_cli import default_observations_dir
from pursue_index.scrape.types import CardMetadata, Manifest

runner = CliRunner()


def _write_manifest(path: Path, cards: list[CardMetadata]) -> None:
    m = Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )
    path.write_text(m.model_dump_json(by_alias=True), encoding="utf-8")


def _img_card(card_id: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id, title=f"IMG {card_id}", asset_type="IMG", agency="NASA",
        asset_url="https://www.war.gov/a.jpg", asset_filename="a.jpg",
    )


def test_the_default_sidecar_directory_is_absolute_and_inside_the_checkout() -> None:
    out = default_observations_dir()
    assert out.is_absolute()
    assert (out.parent.parent.parent.parent / "pyproject.toml").is_file()


def test_the_default_sidecar_directory_does_not_move_with_the_working_directory(
    monkeypatch, tmp_path: Path
) -> None:
    before = default_observations_dir()
    monkeypatch.chdir(tmp_path)
    assert default_observations_dir() == before


def test_a_live_smoke_that_produced_nothing_exits_non_zero(
    tmp_path: Path, monkeypatch
) -> None:
    import pursue_index.vision.client as client_mod
    import pursue_index.vision.render as render_mod

    def refusing_examine(_img: object, **_kw) -> dict:
        raise RuntimeError("image could not be examined")

    monkeypatch.setattr(client_mod, "examine_image", refusing_examine)
    monkeypatch.setattr(render_mod, "load_image_for", lambda item, **kw: item)

    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA")])
    result = runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "obs"),
         "--live-smoke", "imgA"],
    )
    assert result.exit_code == 1
