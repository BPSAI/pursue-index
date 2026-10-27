"""A metadata-typed stream referenced anywhere else is not metadata, and the
cross-check covers a page's annotations and their appearance streams."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from pursue_index.pdf_crosscheck import CrossCheckError, crosscheck
from pursue_index.pdf_limits import Budget
from pursue_index.tranche_bytes import _is_metadata_only, classify_bytes
from tests.support.tranche_bytes_fakes import (
    append_update,
    build_base_pdf,
    metadata_only_resave,
    xmp_body,
)


def _rewrite_metadata_in_place(base) -> bytes:
    return append_update(base.data, {base.metadata_num: xmp_body()}, root=base.root_num,
                         info=base.info_num, size=base.size)


def test_parser_refuses_a_metadata_stream_that_is_also_an_annotation_appearance() -> None:
    base = build_base_pdf(annot_appearance_is_metadata=True)
    assert _is_metadata_only(base.data, _rewrite_metadata_in_place(base), Budget()) is False


def test_parser_still_accepts_an_in_place_rewrite_of_a_plain_metadata_stream() -> None:
    base = build_base_pdf()
    assert _is_metadata_only(base.data, _rewrite_metadata_in_place(base), Budget()) is True


def test_end_to_end_the_shared_appearance_rewrite_is_content_changed() -> None:
    base = build_base_pdf(annot_appearance_is_metadata=True)
    assert crosscheck_free_verdict(base.data, _rewrite_metadata_in_place(base)) == "content-changed"


def crosscheck_free_verdict(old: bytes, new: bytes) -> str:
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        o, n = Path(d, "o.pdf"), Path(d, "n.pdf")
        o.write_bytes(old)
        n.write_bytes(new)
        return classify_bytes(o, n, isolated=False)


def test_plain_metadata_resave_without_other_references_still_passes() -> None:
    base = build_base_pdf()
    assert crosscheck_free_verdict(base.data, metadata_only_resave(base)) == "metadata-only"


def test_a_changed_annotation_is_refused_by_the_cross_check() -> None:
    base = build_base_pdf(annot_appearance_is_metadata=True)
    body = (b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 99 99] /AP << /N %d 0 R >> >>"
            % base.metadata_num)
    new = append_update(base.data, {base.annot_num: body}, root=base.root_num,
                        info=base.info_num, size=base.size)
    with pytest.raises(CrossCheckError):
        crosscheck(base.data, new, Budget())


def test_an_unchanged_annotation_passes_the_cross_check() -> None:
    base = build_base_pdf(annot_appearance_is_metadata=True)
    assert crosscheck(base.data, base.data + b"\n", Budget())


# --- /Info and action-reachable objects ---------------------------------------

JS_INFO = b"<< /S /JavaScript /JS (app.alert\\(1\\)) >>"


def _rewrite(base, num: int, body: bytes) -> bytes:
    return append_update(base.data, {num: body}, root=base.root_num,
                         info=base.info_num, size=base.size)


def test_info_that_is_also_the_open_action_is_content_changed() -> None:
    base = build_base_pdf(info_is_open_action=True)
    new = _rewrite(base, base.info_num, JS_INFO)
    assert _is_metadata_only(base.data, new, Budget()) is False
    assert crosscheck_free_verdict(base.data, new) == "content-changed"


def test_a_plain_info_rewrite_is_still_metadata_only() -> None:
    base = build_base_pdf()
    new = _rewrite(base, base.info_num, b"<< /Title (DOW-UAP-D042) /Producer (resave) >>")
    assert _is_metadata_only(base.data, new, Budget()) is True


def test_an_update_touching_an_aa_target_is_refused() -> None:
    base = build_base_pdf(aa_action=True)
    new = _rewrite(base, base.action_num, JS_INFO)
    assert _is_metadata_only(base.data, new, Budget()) is False


def test_the_action_reachable_set_covers_aa_targets_and_nothing_else() -> None:
    from pursue_index.pdf_refs import action_reachable
    base = build_base_pdf(aa_action=True)
    reader = PdfReader(io.BytesIO(base.data))
    assert base.action_num in action_reachable(reader, Budget())
    assert base.metadata_num not in action_reachable(reader, Budget())
