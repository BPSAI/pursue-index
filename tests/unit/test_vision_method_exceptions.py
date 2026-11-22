"""The curated multi-frame study stays on its curated passes.

``data/vision-method-exceptions.json`` lists cards that a ``--redescribe`` must
not touch. The loader fails closed (a missing or malformed file refuses the
run), and ``--override-method-exception`` needs ``--reason``. No test spends:
the vision client is a spy.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

from pursue_index.vision import method_exceptions
from pursue_index.vision.method_exceptions import MethodExceptionsError, load_method_exceptions
from tests.unit.test_vision_cli import _img_card
from tests.unit.test_vision_redescribe import _invoke, _read, _write_sidecar

CARD = "a1a1a1a1a1a1a1a1"
OTHER = "b2b2b2b2b2b2b2b2"


def _entry(card_id: str = CARD, **kw: str) -> dict[str, str]:
    base = {"card_id": card_id, "reason": "curated multi-frame study",
            "cluster_label": "helicopter-case-2025-imagery-a-series",
            "decided_at": "2026-11-22"}
    return {**base, **kw}


def _file(tmp_path, monkeypatch, entries) -> None:
    path = tmp_path / "exceptions.json"
    path.write_text(entries if isinstance(entries, str) else json.dumps(entries))
    monkeypatch.setattr(method_exceptions, "default_exceptions_path", lambda: path)


def test_committed_file_has_exactly_the_32_unique_study_cards() -> None:
    entries = load_method_exceptions()
    assert len(entries) == 32
    assert len({e.card_id for e in entries}) == 32
    assert Counter(e.cluster_label for e in entries) == {
        "helicopter-case-2025-imagery-a-series": 8,
        "helicopter-case-2025-imagery-b-series": 24,
    }
    assert {e.reason for e in entries} == {"curated multi-frame study"}
    assert {e.decided_at for e in entries} == {"2026-11-22"}


@pytest.mark.parametrize("bad", [
    "{not json", "[]", "{}", '{"exceptions": {}}', '{"exceptions": ["x"]}',
    json.dumps({"exceptions": [_entry(), _entry()]}),
    json.dumps({"exceptions": [_entry("../x")]}),
    json.dumps({"exceptions": [_entry(reason="")]}),
    json.dumps({"exceptions": [{k: v for k, v in _entry().items() if k != "decided_at"}]}),
    json.dumps({"exceptions": [_entry(cluster_label=7)]}),
])
def test_malformed_file_fails_closed(tmp_path, bad) -> None:
    path = tmp_path / "e.json"
    path.write_text(bad)
    with pytest.raises(MethodExceptionsError):
        load_method_exceptions(path)


def test_missing_file_fails_closed(tmp_path) -> None:
    with pytest.raises(MethodExceptionsError):
        load_method_exceptions(tmp_path / "nope.json")


def test_listed_card_is_refused_by_name_in_preflight_and_live(tmp_path, monkeypatch) -> None:
    _file(tmp_path, monkeypatch, {"exceptions": [_entry()]})
    _write_sidecar(tmp_path / "o", CARD)
    before = (tmp_path / "o" / f"{CARD}.json").read_text("utf-8")
    for extra in ([], ["--confirm-live"]):
        result, spy = _invoke(tmp_path, monkeypatch, [_img_card(CARD)], [CARD], extra)
        assert result.exit_code == 2, result.output
        assert CARD in result.output and "method exception" in result.output
        assert "curated multi-frame study" in result.output
        assert "--override-method-exception" in result.output
        assert spy.calls == []
    assert (tmp_path / "o" / f"{CARD}.json").read_text("utf-8") == before


def test_unlisted_cards_are_unaffected(tmp_path, monkeypatch) -> None:
    _file(tmp_path, monkeypatch, {"exceptions": [_entry()]})
    _write_sidecar(tmp_path / "o", OTHER)
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card(OTHER)], [OTHER], ["--confirm-live"])
    assert result.exit_code == 0, result.output
    assert len(spy.calls) == 1


def test_override_with_reason_proceeds_and_says_so(tmp_path, monkeypatch) -> None:
    _file(tmp_path, monkeypatch, {"exceptions": [_entry()]})
    _write_sidecar(tmp_path / "o", CARD)
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card(CARD)], [CARD],
                          ["--override-method-exception", "--reason", "rehearsal"])
    assert result.exit_code == 0, result.output
    assert "1 card(s) / 1 page(s)" in result.output
    assert "rehearsal" in result.output and CARD in result.output
    assert spy.calls == []
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card(CARD)], [CARD],
                          ["--confirm-live", "--override-method-exception",
                           "--reason", "rehearsal"])
    assert result.exit_code == 0, result.output
    assert len(spy.calls) == 1
    assert "superseded_passes" in _read(tmp_path, CARD)


@pytest.mark.parametrize("flags", [
    ["--override-method-exception"],
    ["--override-method-exception", "--reason", "  "],
    ["--reason", "because"],
])
def test_override_needs_a_reason_and_a_reason_needs_the_override(
    tmp_path, monkeypatch, flags
) -> None:
    _file(tmp_path, monkeypatch, {"exceptions": [_entry()]})
    _write_sidecar(tmp_path / "o", CARD)
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card(CARD)], [CARD],
                          ["--confirm-live", *flags])
    assert result.exit_code == 2, result.output
    assert spy.calls == []


def test_a_malformed_file_refuses_the_run_before_any_call(tmp_path, monkeypatch) -> None:
    _file(tmp_path, monkeypatch, "{broken")
    _write_sidecar(tmp_path / "o", OTHER)
    result, spy = _invoke(tmp_path, monkeypatch, [_img_card(OTHER)], [OTHER], ["--confirm-live"])
    assert result.exit_code == 2 and spy.calls == []
    assert "method exceptions" in result.output


