"""The differential fuzz harness for ``classify_bytes``: clean on the current
classifier, and able to see each class of mistake it exists to catch."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

from pursue_index import classify_fuzz, tranche_bytes
from pursue_index.classify_fuzz import generate_case, oracle_difference, run_fuzz

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import fuzz_classify_bytes  # type: ignore[import-not-found] # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


def test_a_bounded_run_on_the_current_classifier_has_no_findings() -> None:
    report = run_fuzz(400, seed=20261111)
    assert report.findings == []
    assert report.verdicts["metadata-only"] > 50
    assert report.verdicts["content-changed"] > 50
    assert report.ok


def test_generation_is_deterministic_per_seed() -> None:
    a = generate_case(random.Random(5), 0)
    b = generate_case(random.Random(5), 0)
    assert (a.ops, a.old, a.new) == (b.ops, b.old, b.new)


def test_the_oracle_sees_no_difference_in_a_metadata_only_pair() -> None:
    rng = random.Random(3)
    old, layout = classify_fuzz.build_base(rng)
    update = classify_fuzz.Update(next_num=layout.size)
    classify_fuzz.BENIGN_OPS["info-new"](rng, layout, update)
    classify_fuzz.BENIGN_OPS["xmp-new"](rng, layout, update)
    assert oracle_difference(old, classify_fuzz.append(old, layout, update, rng)) is None


@pytest.mark.parametrize("op", sorted(classify_fuzz.CONTENT_OPS))
def test_the_oracle_sees_every_content_operator(op: str) -> None:
    for seed in range(40):
        rng = random.Random(seed)
        old, layout = classify_fuzz.build_base(rng)
        if op == "dangling-define" and layout.dangling is None:
            continue
        if op == "appearance" and not layout.appearances:
            continue
        update = classify_fuzz.Update(next_num=layout.size)
        classify_fuzz.CONTENT_OPS[op](rng, layout, update)
        assert oracle_difference(old, classify_fuzz.append(old, layout, update, rng)) is not None
        return
    pytest.fail(f"no base layout exercised {op}")


def test_the_harness_catches_a_classifier_that_ignores_the_reference_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tranche_bytes, "_leaf_referenced_outside", lambda *a, **k: False)
    report = run_fuzz(1500, seed=11)
    assert report.findings, report.summary()
    assert all("dangling-define" in case.ops for case, _ in report.findings)


def test_the_harness_catches_a_classifier_that_waves_everything_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(tranche_bytes, "_is_metadata_only", lambda *a, **k: True)
    monkeypatch.setattr(tranche_bytes, "crosscheck", lambda *a, **k: ())
    report = run_fuzz(60, seed=2, findings_dir=tmp_path)
    assert report.findings and not report.ok
    saved = sorted(p.name for p in tmp_path.iterdir())
    assert any(n.endswith("-old.pdf") for n in saved) and any(n.endswith(".txt") for n in saved)


def test_the_time_budget_stops_the_run() -> None:
    report = run_fuzz(10_000, seed=1, time_budget=0.0)
    assert report.cases == 0 and report.timed_out


def test_script_exit_codes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    assert fuzz_classify_bytes.main(["--iterations", "40", "--seed", "4"]) == 0
    assert "findings 0" in capsys.readouterr().out
    monkeypatch.setattr(tranche_bytes, "_is_metadata_only", lambda *a, **k: True)
    monkeypatch.setattr(tranche_bytes, "crosscheck", lambda *a, **k: ())
    assert fuzz_classify_bytes.main(["--iterations", "40", "--seed", "4"]) == 1


def test_script_flags_a_vacuous_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tranche_bytes, "_is_metadata_only", lambda *a, **k: False)
    assert fuzz_classify_bytes.main(["--iterations", "20", "--seed", "4"]) == 2


def test_the_resources_operator_always_changes_content() -> None:
    # Every page, every seed: the middle page of an odd page count used to
    # swap its image for itself, a silent no-op the harness counted as a change.
    op = next(k for k, v in classify_fuzz.CONTENT_OPS.items() if v.__name__ == "_op_resources")
    for seed in range(200):
        rng = random.Random(seed)
        old, layout = classify_fuzz.build_base(rng)
        update = classify_fuzz.Update(next_num=layout.size)
        classify_fuzz.CONTENT_OPS[op](rng, layout, update)
        assert oracle_difference(old, classify_fuzz.append(old, layout, update, rng)) is not None, seed
