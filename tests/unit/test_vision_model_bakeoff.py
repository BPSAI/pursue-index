"""The vision model bake-off harness: selection, scoring, dry-run and the cap.

The examine function is always a stub; nothing here reaches the API.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "vision_model_bakeoff.py"
spec = importlib.util.spec_from_file_location("vision_model_bakeoff", SCRIPT)
assert spec and spec.loader
bk = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bk
spec.loader.exec_module(bk)

_TYPES = (["black-and-white photograph"] * 12 + ["digital illustration / composite"] * 8
          + ["scanned typed document page"] * 6 + ["blank white image"] * 6)


def _write_obs(root: Path, n: int = 32, model: str = "claude-opus-4-8") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        side = {
            "card_id": f"card{i:03d}", "schema_version": 1,
            "our_pass": {"model": model},
            "pages": [{"page": 1, "row_key": "", "image_type": _TYPES[i % len(_TYPES)],
                       "description": f"desc {i}", "visible_text": "ABC" if i % 3 == 0 else "",
                       "observations": [{"claim": f"a red car number {i}",
                                         "kind": "observation"}]}],
        }
        (root / f"card{i:03d}.json").write_text(json.dumps(side))
    other = {"card_id": "old", "our_pass": {"model": "claude-opus-4-7"},
             "pages": [{"page": 1, "description": "x", "image_type": "photograph"}]}
    (root / "old.json").write_text(json.dumps(other))
    (root / "bad.json").write_text("[]")
    return root


def test_selection_is_deterministic_and_seed_dependent(tmp_path: Path) -> None:
    pool = bk.load_baselines(_write_obs(tmp_path / "o"), "claude-opus-4-8")
    a = bk.select_sample(pool, 25, seed=7)
    assert [b.card_id for b in a] == [b.card_id for b in bk.select_sample(pool[::-1], 25, seed=7)]
    assert [b.card_id for b in a] != [b.card_id for b in bk.select_sample(pool, 25, seed=8)]
    assert len(a) == 25 and len({b.card_id for b in a}) == 25


def test_only_the_baseline_model_is_loaded_and_variety_is_covered(tmp_path: Path) -> None:
    pool = bk.load_baselines(_write_obs(tmp_path / "o"), "claude-opus-4-8")
    assert "old" not in {b.card_id for b in pool}
    cats = {bk.categorize(b.image_type) for b in bk.select_sample(pool, 30, seed=1)}
    assert {"photograph", "illustration", "document"} <= cats


def test_blank_pages_are_capped(tmp_path: Path) -> None:
    pool = bk.load_baselines(_write_obs(tmp_path / "o"), "claude-opus-4-8")
    sample = bk.select_sample(pool, 30, seed=1)
    assert sum(bk.categorize(b.image_type) == "blank" for b in sample) <= 2


def test_text_agreement_is_normalized_edit_distance() -> None:
    assert bk.text_agreement("", "") == 1.0
    assert bk.text_agreement("Hello  World", "hello world") == 1.0
    assert bk.text_agreement("abcd", "abce") == pytest.approx(0.75)
    assert bk.text_agreement("abc", "") == 0.0


def test_claim_overlap_is_a_symmetric_token_match() -> None:
    base = ["a red car parked", "two people standing"]
    assert bk.claim_overlap(base, base) == 1.0
    assert bk.claim_overlap(base, []) == 0.0
    assert bk.claim_overlap([], []) == 1.0
    half = bk.claim_overlap(base, ["a red car parked near", "unrelated words only"])
    assert 0.0 < half < 1.0


def test_completeness_counts_the_four_fields() -> None:
    full = {"image_type": "p", "description": "d", "visible_text": "", "observations": [{"claim": "c"}]}
    assert bk.completeness(full) == 1.0
    assert bk.completeness({"description": "d"}) == pytest.approx(0.25)
    assert bk.completeness({}) == 0.0


def test_cost_uses_each_models_own_rates() -> None:
    use = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert bk.call_cost_usd("claude-opus-4-8", use) == pytest.approx(30.0)
    assert bk.call_cost_usd("claude-opus-5-5", use) == pytest.approx(24.0)


def _stub(calls: list[dict[str, Any]], stop: str = "end_turn"):
    def examine(img: Any, *, model: str, max_tokens: int, effort: str | None = None) -> dict[str, Any]:
        calls.append({"model": model, "max_tokens": max_tokens, "effort": effort})
        return {"image_type": "photo", "description": "desc 0", "visible_text": "ABC",
                "observations": [{"claim": "a red car number 0"}],
                "_usage": {"input_tokens": 5000, "output_tokens": 1000,
                           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                "_stop_reason": stop}
    return examine


def _resolver(tmp_path: Path):
    from pursue_index.vision.eligibility import EligibleItem

    asset = tmp_path / "asset.png"
    asset.write_bytes(b"x")

    def resolve(b: Any) -> Any:
        return EligibleItem(card_id=b.card_id, page=b.page, kind="img_card",
                            image_path=asset, title="T", row_key=b.row_key)
    return resolve


def _setup(tmp_path: Path) -> list[str]:
    obs = _write_obs(tmp_path / "o")
    return ["--observations-dir", str(obs), "--manifest", str(tmp_path / "none.json"),
            "--out-dir", str(tmp_path / "out"), "--sample-size", "4"]


def test_dry_run_is_the_default_and_calls_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []
    rc = bk.main(_setup(tmp_path), examine_fn=_stub(calls), load_image_fn=lambda _i: object(), resolve_fn=_resolver(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0 and calls == []
    assert "DRY RUN" in out and "claude-opus-4-8" in out and "claude-opus-5-5" in out
    assert "estimated total" in out and "--hard-cap-usd" in out
    assert not (tmp_path / "out").exists()


def test_live_without_a_cap_refuses(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    with pytest.raises(SystemExit):
        bk.main([*_setup(tmp_path), "--live"], examine_fn=_stub(calls),
                load_image_fn=lambda _i: object(), resolve_fn=_resolver(tmp_path))
    assert calls == []


def test_live_refuses_under_ci(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    with pytest.raises(SystemExit):
        bk.main([*_setup(tmp_path), "--live", "--hard-cap-usd", "5"],
                examine_fn=_stub([]), load_image_fn=lambda _i: object(), resolve_fn=_resolver(tmp_path))


def test_live_refuses_before_spending_when_an_image_is_missing(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    with pytest.raises(SystemExit):
        bk.main([*_setup(tmp_path), "--live", "--hard-cap-usd", "5"],
                examine_fn=_stub(calls), load_image_fn=lambda _i: object(),
                resolve_fn=lambda _b: None)
    assert calls == []


def test_live_run_calls_both_models_with_a_larger_budget_for_5_5(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    rc = bk.main([*_setup(tmp_path), "--live", "--hard-cap-usd", "50"],
                 examine_fn=_stub(calls), load_image_fn=lambda _i: object(), resolve_fn=_resolver(tmp_path))
    assert rc == 0
    by = {m: [c for c in calls if c["model"] == m] for m in
          ("claude-opus-4-8", "claude-opus-5-5")}
    assert len(by["claude-opus-4-8"]) == len(by["claude-opus-5-5"]) == 4
    assert by["claude-opus-5-5"][0]["max_tokens"] > by["claude-opus-4-8"][0]["max_tokens"]
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    assert results["stopped_by_cap"] is False
    rec = results["pages"][0]["models"]["claude-opus-5-5"]
    assert rec["stop_reason"] == "end_turn" and rec["scores"]["completeness"] == 1.0
    report = (tmp_path / "out" / "report.md").read_text()
    assert "desc 0" in report and "claude-opus-5-5" in report


def test_the_cap_stops_the_run_before_a_call_that_could_cross_it(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    worst_48 = bk.worst_case_call_usd("claude-opus-4-8")
    cap = worst_48 * 1.5  # room for one worst-case call, not for the second
    bk.main([*_setup(tmp_path), "--live", "--hard-cap-usd", str(cap)],
            examine_fn=_stub(calls), load_image_fn=lambda _i: object(), resolve_fn=_resolver(tmp_path))
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    assert results["stopped_by_cap"] is True
    assert len(calls) < 8
    assert results["spent_usd"] <= cap


def test_a_refusal_is_recorded_and_not_scored(tmp_path: Path) -> None:
    bk.main([*_setup(tmp_path), "--live", "--hard-cap-usd", "50"],
            examine_fn=_stub([], stop="refusal"), load_image_fn=lambda _i: object(), resolve_fn=_resolver(tmp_path))
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    rec = results["pages"][0]["models"]["claude-opus-4-8"]
    assert rec["stop_reason"] == "refusal" and rec["scores"] is None
    assert results["summary"]["claude-opus-4-8"]["refusals"] == 4
