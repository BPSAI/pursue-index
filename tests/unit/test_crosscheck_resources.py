"""The cross-check covers a page's resolved /Resources, not only its content
streams and text: swapping what an XObject reference points at is a content
change even when the content stream is byte-identical."""

from __future__ import annotations

import pytest

from pursue_index import pdf_crosscheck
from pursue_index.pdf_crosscheck import CrossCheckError, crosscheck
from pursue_index.pdf_limits import Budget
from tests.support.tranche_bytes_fakes import (
    append_update,
    build_base_pdf,
    metadata_only_resave,
    stream_body,
)

IMAGE_ENTRIES = b"/Type /XObject /Subtype /Image /Width 4 /Height 4 /ColorSpace /DeviceGray /BitsPerComponent 8"


def _image_swapped(base, pixels: bytes) -> bytes:
    return append_update(
        base.data, {base.image_num: stream_body(pixels, IMAGE_ENTRIES)},
        root=base.root_num, info=base.info_num, size=base.size,
    )


def test_a_swapped_image_xobject_with_identical_content_stream_is_refused() -> None:
    base = build_base_pdf()
    with pytest.raises(CrossCheckError):
        crosscheck(base.data, _image_swapped(base, bytes(range(16, 32))), Budget())


def test_resources_signal_is_reported_and_metadata_resaves_still_pass() -> None:
    base = build_base_pdf()
    assert "resources" in crosscheck(base.data, metadata_only_resave(base), Budget())
    assert "resources" in pdf_crosscheck.CROSSCHECKS


def test_an_identical_image_rewritten_in_place_is_not_a_change() -> None:
    base = build_base_pdf()
    same = _image_swapped(base, bytes(range(16)))
    assert crosscheck(base.data, same, Budget())


def test_a_resource_cycle_or_depth_overflow_is_refused(monkeypatch) -> None:
    base = build_base_pdf()
    monkeypatch.setattr(pdf_crosscheck, "MAX_RESOURCE_DEPTH", 1)
    with pytest.raises(CrossCheckError):
        crosscheck(base.data, metadata_only_resave(base), Budget())
