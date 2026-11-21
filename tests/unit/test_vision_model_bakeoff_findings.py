"""Structure, page keys, path checks, spot-check set and load errors for the bake-off harness.

Every examine and load function here is a stub; nothing reaches the API.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _not_under_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--live`` is refused whenever ``CI`` is set; these tests drive a stubbed
    client, so they run with ``CI`` cleared."""
    monkeypatch.delenv("CI", raising=False)

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
spec = importlib.util.spec_from_file_location("vision_model_bakeoff_f", SCRIPTS / "vision_model_bakeoff.py")
assert spec and spec.loader
bk = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bk
spec.loader.exec_module(bk)

CARD = "0123456789abcdef"
_OUT = {"image_type": "photo", "description": "d", "visible_text": "",
        "observations": [{"claim": "a red car"}]}


def _harness_files() -> list[Path]:
    return [SCRIPTS / "vision_model_bakeoff.py", *sorted(SCRIPTS.glob("_bakeoff_*.py"))]


def test_harness_modules_respect_the_size_limits() -> None:
    assert len(_harness_files()) >= 5  # entry point plus the sibling modules
    for path in _harness_files():
        text = path.read_text()
        tree = ast.parse(text)
        assert len(text.splitlines()) <= 400, path.name
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        assert len(funcs) <= 15, path.name
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert (node.end_lineno or 0) - node.lineno + 1 <= 50, f"{path.name}:{node.name}"


def _sidecar(root: Path, card: str, pages: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    rows = [{"page": p, "row_key": "", "image_type": "photograph", "description": f"desc {card} {p}",
             "visible_text": "", "observations": [{"claim": "a red car"}]} for p in range(1, pages + 1)]
    (root / f"{card}.json").write_text(json.dumps(
        {"card_id": card, "our_pass": {"model": "claude-opus-4-8"}, "pages": rows}))
    return root


def _two_page_resolver(tmp_path: Path):
    from pursue_index.vision.eligibility import EligibleItem

    def resolve(b: Any) -> Any:
        path = tmp_path / f"p{b.page}.png"
        path.write_bytes(b"x")
        return EligibleItem(card_id=b.card_id, page=b.page, kind="image_only_page",
                            image_path=path, title="T", row_key=b.row_key)
    return resolve


def _examine(img: Any, **kw: Any) -> dict[str, Any]:
    return {**_OUT, "_usage": {"input_tokens": 100, "output_tokens": 100}, "_stop_reason": "end_turn"}


def _args(obs: Path, tmp_path: Path, size: int) -> list[str]:
    return ["--observations-dir", str(obs), "--manifest", str(tmp_path / "none.json"),
            "--out-dir", str(tmp_path / "out"), "--sample-size", str(size), "--live",
            "--hard-cap-usd", "50"]


def test_pages_of_one_card_keep_their_own_paths_and_spot_marks(tmp_path: Path) -> None:
    obs = _sidecar(tmp_path / "o", CARD, 2)
    bk.main(_args(obs, tmp_path, 2), examine_fn=_examine, load_image_fn=lambda _i: object(),
            resolve_fn=_two_page_resolver(tmp_path))
    report = (tmp_path / "out" / "report.md").read_text()
    assert f"## {CARD} page 1 (SPOT-CHECK)" in report and f"## {CARD} page 2 (SPOT-CHECK)" in report
    assert "p1.png" in report and "p2.png" in report
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    assert results["spot_check"] == [[CARD, 1], [CARD, 2]]


def test_the_spot_check_set_is_the_first_ten_pages_of_the_seeded_sample(tmp_path: Path) -> None:
    obs = tmp_path / "o"
    for i in range(8):
        _sidecar(obs, f"{i:016x}", 2)
    resolve = _two_page_resolver(tmp_path)
    pool = bk.load_baselines(obs, "claude-opus-4-8")
    sample = bk.select_sample(pool, 14, 2026, resolvable=lambda b: True)
    bk.main(_args(obs, tmp_path, 14), examine_fn=_examine, load_image_fn=lambda _i: object(),
            resolve_fn=resolve)
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    assert results["spot_check"] == [[b.card_id, b.page] for b in sample[:10]]
    report = (tmp_path / "out" / "report.md").read_text()
    assert report.count("(SPOT-CHECK)") == 10


def test_the_spot_check_set_is_always_ten_pages_for_a_larger_sample(tmp_path: Path) -> None:
    obs = tmp_path / "o"
    for i in range(8):
        _sidecar(obs, f"{i:016x}", 2)

    def unmetered(img: Any, **kw: Any) -> dict[str, Any]:
        return {**_OUT, "_stop_reason": "end_turn"}

    argv = _args(obs, tmp_path, 14)
    argv[argv.index("--hard-cap-usd") + 1] = "8"
    bk.main([*argv, "--models", "claude-opus-4-8"], examine_fn=unmetered,
            load_image_fn=lambda _i: object(), resolve_fn=_two_page_resolver(tmp_path))
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    assert len(results["spot_check"]) == 10


def test_one_failed_image_load_is_recorded_and_the_run_continues(tmp_path: Path) -> None:
    obs = _sidecar(tmp_path / "o", CARD, 3)
    calls: list[str] = []

    def load(item: Any) -> Any:
        if item.page == 2:
            raise OSError("corrupt page")
        return object()

    def examine(img: Any, **kw: Any) -> dict[str, Any]:
        calls.append(kw["model"])
        return _examine(img, **kw)

    rc = bk.main([*_args(obs, tmp_path, 3), "--models", "claude-opus-4-8"], examine_fn=examine,
                 load_image_fn=load, resolve_fn=_two_page_resolver(tmp_path))
    assert rc == 0 and len(calls) == 2
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    bad = next(p for p in results["pages"] if p["baseline"]["page"] == 2)
    rec = bad["models"]["claude-opus-4-8"]
    assert "corrupt page" in rec["load_error"] and rec["scores"] is None
    assert results["summary"]["claude-opus-4-8"]["load_errors"] == 1
    assert "corrupt page" in (tmp_path / "out" / "report.md").read_text()


def _manifest(cards: list[dict[str, Any]]) -> Any:
    from pursue_index.scrape.types import CardMetadata, Manifest

    return Manifest.model_construct(cards=[CardMetadata.model_validate({
        "title": "t", "agency": "A", "asset_url": "https://www.war.gov/x/f", **c}) for c in cards])


def _resolver_for(tmp_path: Path, cards: list[dict[str, Any]], registry_rows: list[dict[str, str]]):
    registry = tmp_path / "registry.jsonl"
    registry.write_text("".join(json.dumps(r) + "\n" for r in registry_rows))
    return bk.build_resolver(_manifest(cards), pdf_dir=tmp_path / "pdfs", image_dir=tmp_path / "images",
                             mirror_dir=tmp_path / "mirror", registry=registry)


def _base(card: str, page: int = 1) -> Any:
    return bk.Baseline(card, "", page, "photo", "d", "", ())


def test_a_valid_card_resolves_and_a_bad_page_does_not(tmp_path: Path) -> None:
    (tmp_path / "pdfs" / CARD).mkdir(parents=True)
    (tmp_path / "pdfs" / CARD / "a.pdf").write_bytes(b"%PDF")
    resolve = _resolver_for(tmp_path, [{"card_id": CARD, "asset_type": "PDF", "asset_filename": "a.pdf"}], [])
    assert resolve(_base(CARD, 2)).image_path == tmp_path / "pdfs" / CARD / "a.pdf"
    assert resolve(_base(CARD, 0)) is None and resolve(_base(CARD, -3)) is None


def test_a_card_id_that_is_not_16_lowercase_hex_is_refused(tmp_path: Path) -> None:
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "a.pdf").write_bytes(b"%PDF")
    for cid in ("../outside", "ABCDEF0123456789", "0123456789abcde", "0123456789abcdef0"):
        (tmp_path / "pdfs" / cid).mkdir(parents=True, exist_ok=True)
        (tmp_path / "pdfs" / cid / "a.pdf").write_bytes(b"%PDF")  # present, so only the id check can refuse
        resolve = _resolver_for(tmp_path, [{"card_id": cid, "asset_type": "PDF", "asset_filename": "a.pdf"}], [])
        assert resolve(_base(cid)) is None, cid


def test_a_filename_or_hash_that_escapes_its_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / "secret.pdf").write_bytes(b"%PDF")
    (tmp_path / "images" / CARD).mkdir(parents=True)
    img = _resolver_for(tmp_path, [{"card_id": CARD, "asset_type": "IMG",
                                    "asset_filename": "../../../secret.pdf"}], [])
    assert img(_base(CARD)) is None
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "archive").mkdir()
    (tmp_path / "mirror" / "x.pdf").write_bytes(b"%PDF")
    mirrored = _resolver_for(
        tmp_path, [{"card_id": CARD, "asset_type": "PDF", "asset_filename": "gone.pdf"}],
        [{"card_id": CARD, "byte_sha256": "../x"}])
    assert mirrored(_base(CARD)) is None
