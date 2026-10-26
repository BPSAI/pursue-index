"""``pursue_index.tranche_bytes.classify_bytes`` -- the byte-level evidence
that demotes a Class C quarantine to a metadata-only re-save (R7C.12).

The real case is card D042: the old file's bytes were an exact prefix of
the new file and the appended bytes were one PDF incremental update that
touched only the Info dict, the XMP stream, the xref stream and the catalog
(re-pointed at the new XMP stream). These fixtures reproduce that shape
synthetically (``tests/support/tranche_bytes_fakes.py``); the hardening
cases live in ``test_tranche_bytes_hardening.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.tranche_bytes import classify_bytes
from tests.support.tranche_bytes_fakes import (
    append_update,
    build_base_pdf,
    content_changed_resave,
    info_body,
    metadata_only_resave,
    write_pair,
    xmp_body,
)


def test_missing_old_file_raises_file_not_found(tmp_path: Path) -> None:
    new = tmp_path / "new.pdf"
    new.write_bytes(build_base_pdf().data)
    with pytest.raises(FileNotFoundError):
        classify_bytes(tmp_path / "absent.pdf", new)


def test_missing_new_file_raises_file_not_found(tmp_path: Path) -> None:
    old = tmp_path / "old.pdf"
    old.write_bytes(build_base_pdf().data)
    with pytest.raises(FileNotFoundError):
        classify_bytes(old, tmp_path / "absent.pdf")


def test_non_prefix_is_content_changed(tmp_path: Path) -> None:
    old = build_base_pdf().data
    new = build_base_pdf(text=b"(different) Tj").data
    assert classify_bytes(*write_pair(tmp_path, old, new)) == "content-changed"


def test_d042_shape_xref_stream_is_metadata_only(tmp_path: Path) -> None:
    base = build_base_pdf()
    new = metadata_only_resave(base, xref_stream=True, flate=True)
    assert classify_bytes(*write_pair(tmp_path, base.data, new)) == "metadata-only"


def test_metadata_only_with_uncompressed_xref_stream(tmp_path: Path) -> None:
    base = build_base_pdf()
    new = metadata_only_resave(base, xref_stream=True, flate=False)
    assert classify_bytes(*write_pair(tmp_path, base.data, new)) == "metadata-only"


def test_metadata_only_with_classic_xref_table(tmp_path: Path) -> None:
    base = build_base_pdf()
    new = metadata_only_resave(base, xref_stream=False)
    assert classify_bytes(*write_pair(tmp_path, base.data, new)) == "metadata-only"


def test_replaced_page_contents_is_content_changed(tmp_path: Path) -> None:
    base = build_base_pdf()
    new = content_changed_resave(base)
    assert classify_bytes(*write_pair(tmp_path, base.data, new)) == "content-changed"


def test_identical_bytes_are_not_an_update(tmp_path: Path) -> None:
    """No appended update at all is not something this rule vouches for."""
    base = build_base_pdf()
    assert classify_bytes(*write_pair(tmp_path, base.data, base.data)) == "content-changed"


def test_xmp_overwritten_in_place_is_metadata_only(tmp_path: Path) -> None:
    """Rewriting the existing XMP object number (no catalog change)."""
    base = build_base_pdf()
    new = append_update(base.data, {base.metadata_num: xmp_body()},
                        root=base.root_num, info=base.info_num, size=base.size)
    assert classify_bytes(*write_pair(tmp_path, base.data, new)) == "metadata-only"


def test_metadata_stream_with_indirect_length_is_metadata_only(tmp_path: Path) -> None:
    """A brand-new leaf object referenced only from the XMP stream (its
    ``/Length``) is part of the metadata update, not content."""
    base = build_base_pdf()
    n = base.size
    xmp = xmp_body(length=b"%d 0 R" % (n + 1))
    length = str(len(xmp_body().split(b"stream\n", 1)[1].rsplit(b"\nendstream", 1)[0]))
    new = append_update(base.data, {base.metadata_num: xmp, n + 1: length.encode()},
                        root=base.root_num, info=base.info_num, size=n + 2)
    assert classify_bytes(*write_pair(tmp_path, base.data, new)) == "metadata-only"


def test_new_info_dict_alone_is_metadata_only(tmp_path: Path) -> None:
    """Positive control for the hardening cases, which each perturb this."""
    base = build_base_pdf()
    new = append_update(base.data, {base.size: info_body()}, root=base.root_num,
                        info=base.size, size=base.size + 1)
    assert classify_bytes(*write_pair(tmp_path, base.data, new)) == "metadata-only"
