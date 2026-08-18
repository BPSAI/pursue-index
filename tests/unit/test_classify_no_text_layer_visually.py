"""Tests for ``scripts/classify_no_text_layer_visually.py``.

Pins hash output shape, Hamming-distance arithmetic, and the
control-flow branches in `classify_card_visually` that don't require
a real rasterizer (those run as part of the script's main invocation).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import classify_no_text_layer_visually as cv  # noqa: E402


def _solid(value: int, size: tuple[int, int] = (200, 200)) -> Image.Image:
    """Solid-color RGB image."""
    return Image.new("RGB", size, color=(value, value, value))


# --------------------------- perceptual_hash -----------------------------


def test_perceptual_hash_returns_packed_bytes_at_expected_length() -> None:
    h = cv.perceptual_hash(_solid(128))
    # 64x64 bits = 4096 bits = 512 bytes
    assert len(h) == cv._HASH_SIZE * cv._HASH_SIZE // 8
    assert isinstance(h, bytes)


def test_perceptual_hash_identical_images_have_zero_hamming_distance() -> None:
    """Same image → same hash. Zero bit-difference is the strongest
    signal of visual identity."""
    a = cv.perceptual_hash(_solid(100))
    b = cv.perceptual_hash(_solid(100))
    assert cv.hamming_distance(a, b) == 0


def test_perceptual_hash_distinguishes_clearly_different_images() -> None:
    """Black vs white images should have very high bit-difference."""
    # Use a checkerboard vs solid white so the hash has bits set differently
    checker = Image.new("RGB", (200, 200), color=(255, 255, 255))
    # Paint left half black, right half white
    for x in range(100):
        for y in range(200):
            checker.putpixel((x, y), (0, 0, 0))
    a = cv.perceptual_hash(checker)
    b = cv.perceptual_hash(_solid(255))
    # Half the bits should differ (one half of the image was inverted).
    # Allow generous wiggle room because LANCZOS smooths the edge.
    distance = cv.hamming_distance(a, b)
    assert distance > 500, f"expected high distance for visually different images, got {distance}"


# --------------------------- hamming_distance ----------------------------


def test_hamming_distance_zero_for_identical_bytes() -> None:
    assert cv.hamming_distance(b"\x00\xff", b"\x00\xff") == 0


def test_hamming_distance_counts_bit_differences() -> None:
    # 0b00000000 ^ 0b00000001 → 1 bit differs
    assert cv.hamming_distance(b"\x00", b"\x01") == 1
    # 0b11111111 ^ 0b00000000 → 8 bits differ
    assert cv.hamming_distance(b"\xff", b"\x00") == 8


def test_hamming_distance_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="hash length mismatch"):
        cv.hamming_distance(b"\x00\x00", b"\x00")


# --------------------------- classify_card_visually ----------------------


def test_classify_card_visually_skips_non_no_text_layer_cards() -> None:
    """Cards already classified by 4k-A (text-layer route) should not
    be re-processed visually."""
    result = cv.classify_card_visually(
        card_id="abc",
        entry={"class": "content_changed"},
        byte_history={"abc": []},
        archive_dir=Path("/nonexistent"),
    )
    assert result is None


def test_classify_card_visually_skips_when_history_lacks_pair() -> None:
    result = cv.classify_card_visually(
        card_id="abc",
        entry={"class": "no_text_layer"},
        byte_history={"abc": [{"byte_sha256": "x", "archive_key": "archive/x.pdf"}]},
        archive_dir=Path("/nonexistent"),
    )
    assert result is None


def test_classify_card_visually_skips_mp4_history() -> None:
    """The 4k-A asset_type_change branch already handled mp4 oldests;
    this script is defensive about not double-classifying them."""
    result = cv.classify_card_visually(
        card_id="abc",
        entry={"class": "no_text_layer"},
        byte_history={"abc": [
            {"byte_sha256": "x", "archive_key": "archive/x.pdf"},
            {"byte_sha256": "y", "archive_key": "archive/y.mp4"},
        ]},
        archive_dir=Path("/nonexistent"),
    )
    assert result is None


def test_classify_card_visually_skips_missing_bytes(tmp_path: Path) -> None:
    """If the PDFs referenced in byte-history aren't on disk, return
    None rather than crash."""
    result = cv.classify_card_visually(
        card_id="abc",
        entry={"class": "no_text_layer"},
        byte_history={"abc": [
            {"byte_sha256": "x", "archive_key": "archive/x.pdf"},
            {"byte_sha256": "y", "archive_key": "archive/y.pdf"},
        ]},
        archive_dir=tmp_path,  # empty
    )
    assert result is None
