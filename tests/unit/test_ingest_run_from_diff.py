"""``pursue ingest run --from-diff`` operator one-command path.

After a needs-review tranche clears the gate, the operator wants one command
that (a) computes the scoped work-list from the tranche-diff and (b) drives the
scoped download -> ocr -> embed stages -- with a ``--dry-run`` that
prints the work-list WITHOUT spending OCR/embed budget so the operator sees
exactly what will be processed before authorizing.

These tests monkeypatch the deep stage functions (``download_all`` / ``ocr_all``
/ ``embed_run``) -- mirroring ``test_cli_worklist.py`` -- so no network/NAS/SDK
is touched and the real ``--worklist`` scoping path is still exercised.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from pursue_index.cli.ingest_cli import ingest_app

runner = CliRunner()

_TRANCHE = "abc123def456" + "0" * 52


def _write_diff(diff_dir: Path, sha: str, new_content: list[dict]) -> Path:
    diff_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {"new_content": len(new_content)},
        "renames_confirmed": [],
        "new_content": new_content,
        "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [],
        "field_only_changes": [],
    }
    p = diff_dir / f"tranche-diff-{sha[:12]}.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _ids(path: Path) -> list[str]:
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def _new_content_two_cards() -> list[dict]:
    return [
        {"new_card_id": "newcard1", "title": "X", "asset_url": "https://x/a.pdf"},
        {"new_card_id": "newcard2", "title": "Y", "asset_url": "https://x/b.pdf"},
    ]


def _patch_gate_and_promote(monkeypatch, snapshot: Path) -> None:
    """Approve the tranche + stub snapshot resolution/promotion (no FS mirrors)."""
    monkeypatch.setattr(
        "pursue_index.cli.ingest_cli.is_tranche_approved", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "pursue_index.cli.ingest_cli.locate_snapshot", lambda *a, **k: snapshot
    )
    monkeypatch.setattr(
        "pursue_index.cli.ingest_cli.promote_snapshot", lambda *a, **k: None
    )


def _patch_stage_executors(monkeypatch, seen: dict) -> None:
    """Capture the manifest card-ids / only_cards each scoped stage receives."""

    async def fake_download_all(m):
        seen.setdefault("download", []).append([c.card_id for c in m.cards])
        return []

    async def fake_ocr_all(m, **kwargs):
        seen.setdefault("ocr", []).append([c.card_id for c in m.cards])
        return None

    def fake_embed_run(**kwargs):
        seen.setdefault("embed", []).append(kwargs.get("only_cards"))
        seen.setdefault("embed_cost_cap", []).append(kwargs.get("cost_cap_usd"))
        return SimpleNamespace(embedded=0, skipped=0, total_tokens=0, cards_seen=0)

    monkeypatch.setattr(
        "pursue_index.download.downloader.download_all", fake_download_all
    )
    monkeypatch.setattr("pursue_index.ocr.pipeline.ocr_all", fake_ocr_all)
    monkeypatch.setattr("pursue_index.cli.embed_cli._make_embedder", lambda *a, **k: object())
    monkeypatch.setattr("pursue_index.embed.pipeline.embed_run", fake_embed_run)


def _write_manifest(tmp_path: Path) -> Path:
    """A deployed manifest superset (the scoped run must subset it to the diff)."""
    from datetime import UTC, datetime

    from pursue_index.scrape.manifest import save_manifest
    from pursue_index.scrape.types import CardMetadata, Manifest

    cards = [
        CardMetadata(card_id=cid, title="t", asset_type="PDF", agency="a")
        for cid in ["newcard1", "newcard2", "oldcard"]
    ]
    m = Manifest(
        source_url="https://example.com/data.csv",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        csv_sha256="deadbeef",
        cards=cards,
    )
    p = tmp_path / "latest.json"
    save_manifest(m, p)
    return p


def _common_args(diff_dir: Path, manifest: Path, snapshot: Path) -> list[str]:
    return [
        "run",
        "--tranche",
        _TRANCHE,
        "--diff-dir",
        str(diff_dir),
        "--manifest",
        str(manifest),
    ]


def _operated(monkeypatch) -> list[str]:
    """Set the operated OCR env key + return the operated engine/concurrency flags.

    The --from-diff spend path now enforces preflight_ocr, so a
    spend test must present the operated config + an ANTHROPIC_API_KEY.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    return ["--engine", "llm-dots", "--concurrency", "8"]


def test_dry_run_writes_worklist_and_runs_no_stage(tmp_path, monkeypatch) -> None:
    diff_dir = tmp_path / "plans"
    _write_diff(diff_dir, _TRANCHE, _new_content_two_cards())
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    worklist = tmp_path / "worklist.txt"
    _patch_gate_and_promote(monkeypatch, snapshot)
    seen: dict = {}
    _patch_stage_executors(monkeypatch, seen)

    res = runner.invoke(
        ingest_app,
        [*_common_args(diff_dir, manifest, snapshot),
         "--from-diff", "--dry-run", "--worklist", str(worklist)],
    )
    assert res.exit_code == 0, res.output
    assert "newcard1" in res.output
    assert "newcard2" in res.output
    # dry-run MATERIALIZES the worklist (credential-free) so a
    # later separately-invoked OCR step consumes the right card set...
    assert worklist.exists()
    written = [
        ln.strip()
        for ln in worklist.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert written == ["newcard1", "newcard2"]
    # ...but no stage may run under --dry-run.
    assert seen == {}


def test_from_diff_refuses_spend_when_engine_not_operated(tmp_path, monkeypatch) -> None:
    """A non-dry --from-diff with a retired engine must refuse
    BEFORE any stage runs (verify-before-spend), even with a key present."""
    diff_dir = tmp_path / "plans"
    _write_diff(diff_dir, _TRANCHE, _new_content_two_cards())
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("PURSUE_OCR_ENGINE", raising=False)
    _patch_gate_and_promote(monkeypatch, snapshot)
    seen: dict = {}
    _patch_stage_executors(monkeypatch, seen)

    res = runner.invoke(
        ingest_app,
        [*_common_args(diff_dir, manifest, snapshot), "--from-diff",
         "--engine", "tesseract", "--concurrency", "8",
         "--worklist", str(tmp_path / "wl.txt")],
    )
    assert res.exit_code == 1, res.output
    assert "refusing to spend" in res.output.lower()
    assert seen == {}  # no download/ocr/embed ran


def test_non_dry_writes_worklist_and_runs_scoped_stages(tmp_path, monkeypatch) -> None:
    diff_dir = tmp_path / "plans"
    _write_diff(diff_dir, _TRANCHE, _new_content_two_cards())
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    worklist = tmp_path / "worklist.txt"
    _patch_gate_and_promote(monkeypatch, snapshot)
    seen: dict = {}
    _patch_stage_executors(monkeypatch, seen)

    res = runner.invoke(
        ingest_app,
        [*_common_args(diff_dir, manifest, snapshot), "--from-diff",
         *_operated(monkeypatch), "--worklist", str(worklist)],
    )
    assert res.exit_code == 0, res.output

    # Worklist file written with exactly the scoped card_ids.
    assert worklist.exists()
    written = [
        ln.strip()
        for ln in worklist.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert written == ["newcard1", "newcard2"]

    # Each stage ran exactly once, scoped to the worklist (oldcard excluded).
    assert seen["download"] == [["newcard1", "newcard2"]]
    assert seen["ocr"] == [["newcard1", "newcard2"]]
    assert seen["embed"] == [{"newcard1", "newcard2"}]


def test_non_dry_metadata_only_runs_no_stage(tmp_path, monkeypatch) -> None:
    """A metadata-only tranche has an empty work-list: nothing to OCR/embed."""
    diff_dir = tmp_path / "plans"
    _write_diff(diff_dir, _TRANCHE, [])
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    worklist = tmp_path / "worklist.txt"
    _patch_gate_and_promote(monkeypatch, snapshot)
    seen: dict = {}
    _patch_stage_executors(monkeypatch, seen)

    res = runner.invoke(
        ingest_app,
        [*_common_args(diff_dir, manifest, snapshot), "--from-diff", "--worklist", str(worklist)],
    )
    assert res.exit_code == 0, res.output
    assert seen == {}


def test_cost_cap_defaults_to_embed_default(tmp_path, monkeypatch) -> None:
    """Without --cost-cap-usd, the embed stage gets embed_cli's own default
    (sourced from _OPT_COST_CAP, not a divergent hardcode)."""
    from pursue_index.cli import embed_cli

    diff_dir = tmp_path / "plans"
    _write_diff(diff_dir, _TRANCHE, _new_content_two_cards())
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    _patch_gate_and_promote(monkeypatch, snapshot)
    seen: dict = {}
    _patch_stage_executors(monkeypatch, seen)

    res = runner.invoke(
        ingest_app,
        [*_common_args(diff_dir, manifest, snapshot), "--from-diff",
         *_operated(monkeypatch), "--worklist", str(tmp_path / "wl.txt")],
    )
    assert res.exit_code == 0, res.output
    assert seen["embed_cost_cap"] == [embed_cli._OPT_COST_CAP.default]


def test_cost_cap_override_threads_to_embed(tmp_path, monkeypatch) -> None:
    """--cost-cap-usd is the operator escape hatch for a large tranche; it must
    reach the embed stage."""
    diff_dir = tmp_path / "plans"
    _write_diff(diff_dir, _TRANCHE, _new_content_two_cards())
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    _patch_gate_and_promote(monkeypatch, snapshot)
    seen: dict = {}
    _patch_stage_executors(monkeypatch, seen)

    res = runner.invoke(
        ingest_app,
        [*_common_args(diff_dir, manifest, snapshot), "--from-diff",
         *_operated(monkeypatch),
         "--worklist", str(tmp_path / "wl.txt"), "--cost-cap-usd", "50"],
    )
    assert res.exit_code == 0, res.output
    assert seen["embed_cost_cap"] == [50.0]


# --- A/V worklist handling ---


def _new_content_mixed() -> list[dict]:
    """2 PDF, 2 VID, 1 AUD for mixed PDF/A/V testing."""
    return [
        {"new_card_id": "pdf1", "title": "PDF 1", "asset_url": "https://x/a.pdf", "asset_type": "PDF", "release_date": "2026-03-15"},
        {"new_card_id": "pdf2", "title": "PDF 2", "asset_url": "https://x/b.pdf", "asset_type": "PDF", "release_date": "2026-03-15"},
        {"new_card_id": "vid1", "title": "Video 1", "asset_url": "https://x/a.mp4", "asset_type": "VID", "release_date": "2026-03-15"},
        {"new_card_id": "vid2", "title": "Video 2", "asset_url": "https://x/b.mp4", "asset_type": "VID", "release_date": "2026-03-15"},
        {"new_card_id": "aud1", "title": "Audio 1", "asset_url": "https://x/a.mp3", "asset_type": "AUD", "release_date": "2026-03-15"},
    ]


def test_dry_run_writes_both_pdf_and_av_worklists(tmp_path, monkeypatch) -> None:
    """--dry-run with mixed PDF/A/V content writes both worklist.txt and worklist-av.txt."""
    diff_dir = tmp_path / "plans"
    _write_diff(diff_dir, _TRANCHE, _new_content_mixed())
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    worklist = tmp_path / "worklist.txt"
    _patch_gate_and_promote(monkeypatch, snapshot)
    seen: dict = {}
    _patch_stage_executors(monkeypatch, seen)

    res = runner.invoke(
        ingest_app,
        [*_common_args(diff_dir, manifest, snapshot),
         "--from-diff", "--dry-run", "--worklist", str(worklist)],
    )
    assert res.exit_code == 0, res.output

    # Check PDF worklist
    assert worklist.exists(), f"PDF worklist not created at {worklist}"
    pdf_lines = [
        ln.strip()
        for ln in worklist.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert pdf_lines == ["pdf1", "pdf2"], f"Expected ['pdf1', 'pdf2'], got {pdf_lines}"

    # Check A/V worklist
    av_worklist = worklist.parent / "worklist-av.txt"
    assert av_worklist.exists(), f"A/V worklist not created at {av_worklist}"
    av_lines = [
        ln.strip()
        for ln in av_worklist.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert av_lines == ["vid1", "vid2", "aud1"], f"Expected ['vid1', 'vid2', 'aud1'], got {av_lines}"

    # No stages ran
    assert seen == {}


def test_dry_run_pdf_only_no_av_worklist(tmp_path, monkeypatch) -> None:
    """--dry-run with PDF-only content writes only worklist.txt, not worklist-av.txt."""
    diff_dir = tmp_path / "plans"
    _write_diff(diff_dir, _TRANCHE, _new_content_two_cards())
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    worklist = tmp_path / "worklist.txt"
    _patch_gate_and_promote(monkeypatch, snapshot)
    seen: dict = {}
    _patch_stage_executors(monkeypatch, seen)

    res = runner.invoke(
        ingest_app,
        [*_common_args(diff_dir, manifest, snapshot),
         "--from-diff", "--dry-run", "--worklist", str(worklist)],
    )
    assert res.exit_code == 0, res.output

    # Check PDF worklist exists
    assert worklist.exists()
    pdf_lines = [
        ln.strip()
        for ln in worklist.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert pdf_lines == ["newcard1", "newcard2"]

    # A/V worklist should NOT exist
    av_worklist = worklist.parent / "worklist-av.txt"
    assert not av_worklist.exists(), f"A/V worklist should not exist, but found at {av_worklist}"


def test_dry_run_av_only_writes_empty_pdf_worklist(tmp_path, monkeypatch) -> None:
    """--dry-run with A/V-only content writes worklist-av.txt and an empty worklist.txt."""
    diff_dir = tmp_path / "plans"
    av_only = [
        {"new_card_id": "vid1", "title": "Video 1", "asset_url": "https://x/a.mp4", "asset_type": "VID", "release_date": "2026-03-15"},
        {"new_card_id": "aud1", "title": "Audio 1", "asset_url": "https://x/a.mp3", "asset_type": "AUD", "release_date": "2026-03-15"},
    ]
    _write_diff(diff_dir, _TRANCHE, av_only)
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    worklist = tmp_path / "worklist.txt"
    _patch_gate_and_promote(monkeypatch, snapshot)
    seen: dict = {}
    _patch_stage_executors(monkeypatch, seen)

    res = runner.invoke(
        ingest_app,
        [*_common_args(diff_dir, manifest, snapshot),
         "--from-diff", "--dry-run", "--worklist", str(worklist)],
    )
    assert res.exit_code == 0, res.output

    # PDF worklist is written empty, so a stale one can never be picked up
    assert worklist.exists()
    assert _ids(worklist) == []

    # A/V worklist should exist
    av_worklist = worklist.parent / "worklist-av.txt"
    assert av_worklist.exists(), f"A/V worklist not created at {av_worklist}"
    av_lines = [
        ln.strip()
        for ln in av_worklist.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert av_lines == ["vid1", "aud1"]


def _av_only_content() -> list[dict]:
    return [
        {"new_card_id": "vid1", "title": "V", "asset_url": "https://x/a.mp4", "asset_type": "VID", "release_date": "2026-03-15"},
        {"new_card_id": "aud1", "title": "A", "asset_url": "https://x/a.mp3", "asset_type": "AUD", "release_date": "2026-04-02"},
    ]


def test_non_dry_av_only_tranche_skips_pdf_stages_and_writes_empty_worklist(
    tmp_path, monkeypatch
) -> None:
    diff_dir = tmp_path / "plans"
    _write_diff(diff_dir, _TRANCHE, _av_only_content())
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    worklist = tmp_path / "worklist.txt"
    # A stale list from an earlier tranche must not survive.
    worklist.write_text("oldcard\n", encoding="utf-8")
    _patch_gate_and_promote(monkeypatch, snapshot)
    seen: dict = {}
    _patch_stage_executors(monkeypatch, seen)
    # No operated env: the OCR preflight must not even run without PDF cards.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PURSUE_OCR_ENGINE", raising=False)

    res = runner.invoke(
        ingest_app,
        [*_common_args(diff_dir, manifest, snapshot), "--from-diff",
         "--worklist", str(worklist)],
    )
    assert res.exit_code == 0, res.output

    assert seen == {}  # no download / ocr / embed
    assert _ids(worklist) == []
    assert _ids(tmp_path / "worklist-av.txt") == ["vid1", "aud1"]
    assert "0 PDF/IMG cards — PDF stages skipped" in res.output
    assert "pursue av-fetch run --release-date 2026-03-15" in res.output
    assert "pursue av-fetch run --release-date 2026-04-02" in res.output


def test_av_worklist_name_is_derived_without_string_replace(tmp_path) -> None:
    from pursue_index.cli.ingest_from_diff import write_worklist_file

    write_worklist_file(tmp_path / "wl.txt.d" / "list.txt", ["a"], "t" * 12, suffix="-av")
    write_worklist_file(tmp_path / "plain", ["b"], "t" * 12, suffix="-av")
    assert (tmp_path / "wl.txt.d" / "list-av.txt").exists()
    assert (tmp_path / "plain-av").exists()
    assert not (tmp_path / "plain").exists()
