"""Stub (red phase)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImageMirrorReport:
    counts: dict[str, int] = field(default_factory=dict)
    ok: bool = True


@dataclass
class ImageMirrorPreflight:
    ok: bool = True
    details: dict[str, str] = field(default_factory=dict)


def select_image_cards(card_ids, manifest_cards):
    return [], {}


def run_image_mirror(cards, *, images_root, mirror_root, registry_path):
    return ImageMirrorReport(counts={})


def verify_image_mirror(cards, *, mirror_root, registry_path):
    return ImageMirrorPreflight()


def render_image_mirror_report(report):
    return ""


def render_image_verify(pf):
    return ""
