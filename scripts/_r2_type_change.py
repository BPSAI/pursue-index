"""The file-type change warning: one detection, run on every lane."""

from __future__ import annotations


def type_change_with_asset_gone(rows, asset_url, asset_filename, current_urls):
    raise NotImplementedError


def warn_type_changes(registry, cards) -> int:
    raise NotImplementedError
