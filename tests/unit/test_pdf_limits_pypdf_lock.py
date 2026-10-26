"""``capped_pypdf`` is serialized and restores the prior pypdf configuration."""

from __future__ import annotations

import threading

from pypdf import get_configuration

from pursue_index import pdf_limits


def _cap() -> int:
    return get_configuration().zlib_maximum_output_length


def test_exit_restores_the_previous_configuration() -> None:
    before = _cap()
    with pdf_limits.capped_pypdf():
        assert _cap() == pdf_limits.MAX_XREF_INFLATED
    assert _cap() == before


def test_nested_use_in_one_thread_keeps_the_cap() -> None:
    with pdf_limits.capped_pypdf():
        with pdf_limits.capped_pypdf():
            assert _cap() == pdf_limits.MAX_XREF_INFLATED
        assert _cap() == pdf_limits.MAX_XREF_INFLATED


def test_a_second_thread_waits_and_then_sees_the_cap() -> None:
    order: list[str] = []
    holding, release, seen = threading.Event(), threading.Event(), []

    def first() -> None:
        with pdf_limits.capped_pypdf():
            holding.set()
            release.wait(5)
            order.append("first-exit")

    def second() -> None:
        holding.wait(5)
        with pdf_limits.capped_pypdf():
            order.append("second-enter")
            seen.append(_cap())

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    holding.wait(5)
    threading.Event().wait(0.2)  # let the second thread reach the lock
    assert order == []  # it is blocked, not running uncapped
    release.set()
    for t in threads:
        t.join(5)
    assert order == ["first-exit", "second-enter"]
    assert seen == [pdf_limits.MAX_XREF_INFLATED]
