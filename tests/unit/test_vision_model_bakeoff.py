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


@pytest.fixture(autouse=True)
def _not_under_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """The harness refuses ``--live`` whenever ``CI`` is set, a deliberate guard
    against spending from CI. The live-path tests drive a stubbed client, so
    they run with ``CI`` cleared; the guard's own test sets it back."""
    monkeypatch.delenv("CI", raising=False)

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
    assert bk.call_cost_usd("claude-opus-4-8", use, bk.DEFAULT_PRICES) == pytest.approx(30.0)
    assert bk.call_cost_usd("claude-opus-5-5", use, bk.DEFAULT_PRICES) == pytest.approx(24.0)


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
    assert "summed expected" in out and "--hard-cap-usd" in out
    assert not (tmp_path / "out").exists()


def test_live_with_a_non_positive_cap_refuses(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    with pytest.raises(SystemExit):
        bk.main([*_setup(tmp_path), "--live", "--hard-cap-usd", "0"], examine_fn=_stub(calls),
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
    inner = _stub(calls)

    def no_usage(img: Any, **kw: Any) -> dict[str, Any]:
        out = inner(img, **kw)
        del out["_usage"]  # an unmetered response costs its worst case
        return out

    cap = 0.8  # passes the pre-flight for 4 pages, but not for 4 worst-case pairs
    bk.main([*_setup(tmp_path), "--live", "--hard-cap-usd", str(cap)],
            examine_fn=no_usage, load_image_fn=lambda _i: object(), resolve_fn=_resolver(tmp_path))
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


# --- resolvable pages, arms as input, and the cap pre-flight -------------------------------


def _pdf_manifest(tmp_path: Path) -> tuple[Any, Path]:
    """One PDF card with an on-disk file, one whose file is absent, one whose bytes are mirrored."""
    from pursue_index.scrape.types import CardMetadata, Manifest

    def card(cid: str, name: str) -> Any:
        return CardMetadata.model_validate({
            "card_id": cid, "title": cid, "asset_type": "PDF", "agency": "A",
            "asset_url": f"https://www.war.gov/x/{name}", "asset_filename": name})

    cards = [card("aaaaaaaaaaaaaaaa", "a.pdf"), card("bbbbbbbbbbbbbbbb", "b.pdf"), card("cccccccccccccccc", "c.pdf")]
    return Manifest.model_construct(cards=cards), tmp_path


def test_page_resolution_covers_text_bearing_pages_of_multi_page_pdfs(tmp_path: Path) -> None:
    manifest, root = _pdf_manifest(tmp_path)
    pdf = root / "pdfs" / "aaaaaaaaaaaaaaaa"
    pdf.mkdir(parents=True)
    (pdf / "a.pdf").write_bytes(b"%PDF")
    mirror = root / "mirror"
    (mirror / "archive").mkdir(parents=True)
    (mirror / "archive" / ("ab" * 32 + ".pdf")).write_bytes(b"%PDF")
    registry = root / "registry.jsonl"
    registry.write_text(
        json.dumps({"card_id": "cccccccccccccccc", "byte_sha256": "00" * 32}) + "\n"
        + json.dumps({"card_id": "cccccccccccccccc", "byte_sha256": "ab" * 32}) + "\n")
    resolve = bk.build_resolver(manifest, pdf_dir=root / "pdfs", image_dir=root / "images",
                                mirror_dir=mirror, registry=registry)

    def base(cid: str, page: int) -> Any:
        return bk.Baseline(cid, "", page, "photo", "d", "", ())

    on_disk = resolve(base("aaaaaaaaaaaaaaaa", 4))
    assert on_disk.kind == "image_only_page" and on_disk.page == 4  # not limited to image-only pages
    assert on_disk.image_path == pdf / "a.pdf"
    via_mirror = resolve(base("cccccccccccccccc", 9))  # last registry row wins
    assert via_mirror.image_path == mirror / "archive" / ("ab" * 32 + ".pdf") and via_mirror.page == 9
    assert resolve(base("bbbbbbbbbbbbbbbb", 1)) is None
    assert resolve(base("not_in_manifest", 1)) is None


def test_the_selector_never_returns_an_unresolvable_page_and_stays_deterministic(tmp_path: Path) -> None:
    pool = bk.load_baselines(_write_obs(tmp_path / "o"), "claude-opus-4-8")
    ok = {b.card_id for b in pool[::2]}  # half the pool is unresolvable

    def resolvable(b: Any) -> bool:
        return b.card_id in ok

    a = bk.select_sample(pool, 15, seed=3, resolvable=resolvable)
    assert len(a) == 15 and all(b.card_id in ok for b in a)  # replaced, so the size holds
    assert a == bk.select_sample(pool[::-1], 15, seed=3, resolvable=resolvable)
    short = bk.select_sample(pool, 40, seed=3, resolvable=resolvable)
    assert len(ok) - bk.BLANK_MAX <= len(short) <= len(ok) and all(b.card_id in ok for b in short)


def test_dry_run_lists_only_resolved_pages(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    resolver = _resolver(tmp_path)
    bk.main([*_setup(tmp_path), "--sample-size", "6"],
            resolve_fn=lambda b: resolver(b) if b.card_id < "card020" else None)
    out = capsys.readouterr().out
    assert "asset not resolved" not in out and "6 pages" in out


def test_models_default_to_the_two_opus_arms_and_are_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bk.main(_setup(tmp_path), resolve_fn=_resolver(tmp_path))
    out = capsys.readouterr().out
    assert "claude-opus-4-8" in out and "claude-opus-5-5" in out
    bk.main([*_setup(tmp_path), "--models", "claude-sonnet-5-5", "--price", "claude-sonnet-5-5=3/15"],
            resolve_fn=_resolver(tmp_path))
    out = capsys.readouterr().out
    assert "claude-sonnet-5-5" in out and "claude-opus-5-5" not in out


def test_default_prices_and_price_overrides() -> None:
    assert bk.DEFAULT_PRICES["claude-opus-4-8"] == (5.0, 25.0)
    assert bk.DEFAULT_PRICES["claude-opus-5-5"] == (4.0, 20.0)
    got = bk.parse_prices(["claude-x-1=2/10", "claude-opus-5-5=1.5/7.5"])
    assert got["claude-x-1"] == (2.0, 10.0) and got["claude-opus-5-5"] == (1.5, 7.5)
    assert got["claude-opus-4-8"] == (5.0, 25.0)
    with pytest.raises(ValueError):
        bk.parse_prices(["claude-x-1=oops"])


def test_a_non_claude_model_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        bk.main([*_setup(tmp_path), "--models", "claude-opus-4-8,gpt-9"], resolve_fn=_resolver(tmp_path))
    assert exc.value.code != 0


def test_a_model_without_a_price_is_flagged_in_dry_run_and_refused_live(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = bk.main([*_setup(tmp_path), "--models", "claude-new-9"], resolve_fn=_resolver(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0 and "claude-new-9" in out and "NO PRICE" in out and "REFUSE" in out
    calls: list[dict[str, Any]] = []
    with pytest.raises(SystemExit):
        bk.main([*_setup(tmp_path), "--models", "claude-new-9", "--live", "--hard-cap-usd", "8"],
                examine_fn=_stub(calls), load_image_fn=lambda _i: object(),
                resolve_fn=_resolver(tmp_path))
    assert calls == []


def test_live_runs_the_chosen_arms_and_summarizes_each(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    bk.main([*_setup(tmp_path), "--models", "claude-opus-5-5", "--live", "--hard-cap-usd", "8"],
            examine_fn=_stub(calls), load_image_fn=lambda _i: object(), resolve_fn=_resolver(tmp_path))
    assert {c["model"] for c in calls} == {"claude-opus-5-5"}
    results = json.loads((tmp_path / "out" / "results.json").read_text())
    assert list(results["summary"]) == ["claude-opus-5-5"]


def test_worst_case_comes_from_max_tokens_and_5_5_is_capped_at_8000_with_medium_effort() -> None:
    assert bk.max_tokens_for("claude-opus-5-5") == 8000
    assert bk.max_tokens_for("claude-opus-4-8") == 2048
    in_tok = bk.IMAGE_TOKENS + bk.PROMPT_TOKENS
    want = (in_tok * 4.0 + 8000 * 20.0) / 1e6
    assert bk.worst_case_call_usd("claude-opus-5-5", bk.DEFAULT_PRICES) == pytest.approx(want)
    est = bk.estimate(30, ("claude-opus-4-8", "claude-opus-5-5"), bk.DEFAULT_PRICES)
    assert est["claude-opus-5-5"]["worst_case_total_usd"] == pytest.approx(30 * want)
    assert est["claude-opus-5-5"]["worst_case_total_usd"] < 8.0


def test_the_default_cap_is_8_and_5_5_calls_send_medium_effort(tmp_path: Path) -> None:
    assert bk.DEFAULT_HARD_CAP_USD == 8.0
    calls: list[dict[str, Any]] = []
    bk.main([*_setup(tmp_path), "--sample-size", "2", "--live", "--hard-cap-usd", "8"],
            examine_fn=_stub(calls), load_image_fn=lambda _i: object(), resolve_fn=_resolver(tmp_path))
    five = [c for c in calls if c["model"] == "claude-opus-5-5"]
    assert five and all(c["effort"] == "medium" and c["max_tokens"] == 8000 for c in five)


def test_preflight_passes_under_the_cap_and_refuses_over_it() -> None:
    models = ("claude-opus-4-8", "claude-opus-5-5")
    est = bk.estimate(30, models, bk.DEFAULT_PRICES)
    assert bk.preflight(est, 8.0) == []
    over_sum = bk.preflight(est, 3.0)  # expected sum is ~3.2
    assert over_sum and "expected" in over_sum[0]
    over_arm = bk.preflight(est, 5.0)  # the 5.5 arm's worst case is ~5.4
    assert over_arm and "claude-opus-5-5" in over_arm[0] and "worst" in over_arm[0]


def test_live_refuses_to_start_over_the_cap_naming_the_arm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []
    with pytest.raises(SystemExit) as exc:
        bk.main([*_setup(tmp_path), "--sample-size", "30", "--live", "--hard-cap-usd", "5"],
                examine_fn=_stub(calls), load_image_fn=lambda _i: object(),
                resolve_fn=_resolver(tmp_path))
    assert exc.value.code != 0 and calls == []
    assert "claude-opus-5-5" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_dry_run_prints_both_figures_per_arm_and_a_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bk.main([*_setup(tmp_path), "--sample-size", "30"], resolve_fn=_resolver(tmp_path))
    out = capsys.readouterr().out
    assert "expected $" in out and "worst case $" in out and "PASS" in out
    bk.main([*_setup(tmp_path), "--sample-size", "30", "--hard-cap-usd", "2"],
            resolve_fn=_resolver(tmp_path))
    assert "REFUSE" in capsys.readouterr().out


def test_dry_run_warns_when_fewer_pages_resolve_than_requested(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bk.main([*_setup(tmp_path), "--sample-size", "6"], resolve_fn=lambda _b: None)
    out = capsys.readouterr().out
    assert "WARNING" in out and "0 of 6" in out and "PURSUE_DATA_ROOT" in out
