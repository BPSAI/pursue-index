"""Key and Content-Type derivation in ``scripts/r2_archive_assets.py``."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import r2_archive_assets  # noqa: E402

_SHA = "ab" * 32
_GOOD_ID = "0123456789abcdef"


def _card(card_id: str = _GOOD_ID, filename: str | None = "doc.pdf") -> SimpleNamespace:
    return SimpleNamespace(
        card_id=card_id,
        asset_filename=filename,
        asset_url="https://example.invalid/asset",
    )


@pytest.mark.parametrize(
    ("filename", "ext", "content_type"),
    [
        ("doc.pdf", "pdf", "application/pdf"),
        ("DOC.PDF", "pdf", "application/pdf"),
        ("photo.jpg", "jpg", "image/jpeg"),
        ("photo.jpeg", "jpeg", "image/jpeg"),
        ("image.png", "png", "image/png"),
        ("anim.gif", "gif", "image/gif"),
        ("pic.webp", "webp", "image/webp"),
        ("scan.tif", "tif", "image/tiff"),
        ("scan.tiff", "tiff", "image/tiff"),
    ],
)
def test_content_type_comes_from_the_extension_map(filename, ext, content_type):
    archive_key, current_key, ctype = r2_archive_assets._build_keys(_card(filename=filename), _SHA)
    assert archive_key == f"archive/{_SHA}.{ext}"
    assert current_key == f"{_GOOD_ID}.{ext}"
    assert ctype == content_type


def test_content_type_ignores_the_rest_of_the_filename():
    # A name whose guessed type differs from its final allowlisted extension
    # must still be stored with the type the allowlist assigns.
    _, _, ctype = r2_archive_assets._build_keys(_card(filename="page.html.pdf"), _SHA)
    assert ctype == "application/pdf"


@pytest.mark.parametrize(
    "filename",
    ["page.html", "script.svg", "noext", "", None, "archive.pdf.exe"],
)
def test_extensions_outside_the_map_are_refused(filename):
    with pytest.raises(ValueError):
        r2_archive_assets._build_keys(_card(filename=filename), _SHA)


@pytest.mark.parametrize(
    "card_id",
    [
        "",
        "0123456789ABCDEF",
        "0123456789abcde",
        "0123456789abcdef0",
        "../0123456789abc",
        "archive/01234567",
        "0123456789abcde/",
        "0123456789abcdeg",
        None,
    ],
)
def test_malformed_card_ids_are_refused(card_id):
    with pytest.raises(ValueError):
        r2_archive_assets._build_keys(_card(card_id=card_id), _SHA)


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def _no_network(*_args, **_kwargs):
    raise AssertionError("network must not be touched for a refused card")


@pytest.mark.parametrize(
    "card",
    [_card(card_id="../escape.pdf"), _card(filename="page.html")],
)
def test_process_card_refuses_before_any_fetch_or_put(card, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(r2_archive_assets, "head_asset", _no_network)
    monkeypatch.setattr(r2_archive_assets, "fetch_asset", _no_network)
    client = _FakeClient()
    registry_path = tmp_path / "registry.jsonl"

    result = r2_archive_assets._process_card(card, {}, client, "b", False, registry_path)

    assert result == "fail"
    assert client.calls == []
    assert not registry_path.exists()
    assert "[r2-archive]" in capsys.readouterr().out


def test_process_card_uploads_with_mapped_content_type(monkeypatch, tmp_path):
    monkeypatch.setattr(r2_archive_assets, "head_asset", lambda _url: (None, None))
    monkeypatch.setattr(r2_archive_assets, "fetch_asset", lambda _url: b"jpeg-bytes")
    client = _FakeClient()
    registry_path = tmp_path / "registry.jsonl"

    result = r2_archive_assets._process_card(
        _card(filename="photo.jpg"), {}, client, "b", False, registry_path
    )

    assert result == "new"
    assert [c["Key"] for c in client.calls][1] == f"{_GOOD_ID}.jpg"
    assert {c["ContentType"] for c in client.calls} == {"image/jpeg"}
    assert registry_path.exists()
