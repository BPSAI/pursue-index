"""Passthrough of --engine/--force/--concurrency through `ingest run --from-diff`.

The scoped OCR stage must be able to run the operated forced all-Sonnet
configuration (`--engine llm-dots --force --concurrency 8`); before this,
`run_scoped_stages` hard-coded `ocr_run(engine=None, force=False,
concurrency=None)`, which is why the one-command path could not produce the
Release-4 re-OCR and the operator fell back to a manual command.
"""

from __future__ import annotations


def _stub_stages(monkeypatch, captured: dict) -> None:
    monkeypatch.setattr(
        "pursue_index.cli.download_ocr_cli.download_run", lambda **k: None
    )

    def fake_ocr_run(**k):
        captured.update(k)

    monkeypatch.setattr("pursue_index.cli.download_ocr_cli.ocr_run", fake_ocr_run)
    monkeypatch.setattr("pursue_index.cli.embed_cli.embed_run_cmd", lambda **k: None)


def test_run_scoped_stages_forwards_engine_force_concurrency(tmp_path, monkeypatch):
    captured: dict = {}
    _stub_stages(monkeypatch, captured)
    from pursue_index.cli.ingest_from_diff import run_scoped_stages

    run_scoped_stages(
        tmp_path / "m.json",
        tmp_path / "wl.txt",
        engine="llm-dots",
        force=True,
        concurrency=8,
    )
    assert captured["engine"] == "llm-dots"
    assert captured["force"] is True
    assert captured["concurrency"] == 8


def test_run_scoped_stages_defaults_preserve_legacy_behavior(tmp_path, monkeypatch):
    """Omitting the new args keeps the prior contract (engine=None, force=False)."""
    captured: dict = {}
    _stub_stages(monkeypatch, captured)
    from pursue_index.cli.ingest_from_diff import run_scoped_stages

    run_scoped_stages(tmp_path / "m.json", tmp_path / "wl.txt")
    assert captured["engine"] is None
    assert captured["force"] is False
    assert captured["concurrency"] is None
