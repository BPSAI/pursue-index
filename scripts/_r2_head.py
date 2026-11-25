"""What the last registry row says about an asset, and whether HEAD agrees with it."""

from __future__ import annotations

from typing import Any

from pursue_index.asset_rows import rows_of_asset


def rows_for_asset(
    rows: list[dict[str, Any]] | None, asset_url: Any, asset_filename: Any = None
) -> list[dict[str, Any]]:
    """The earlier rows of one asset (oldest first): those at the fetched URL, else the
    card's rows of the same file type when the asset moved; empty means net-new."""
    return rows_of_asset(rows, asset_url, asset_filename)


def last_known_size(rows: list[dict[str, Any]]) -> int | None:
    return rows[-1].get("byte_size") if rows else None


def last_known_etag(rows: list[dict[str, Any]]) -> str | None:
    return rows[-1].get("upstream_etag") if rows else None


def head_identical(
    rows: list[dict[str, Any]],
    cl: int | None,
    etag: str | None,
    last_modified: str | None = None,
    *,
    encoded: bool = False,
) -> bool:
    """True only when HEAD agrees with the last row's recorded validators.

    With an ETag on both sides, size and ETag must be equal. Without one, the
    fallback is Content-Length plus Last-Modified: both present and equal to the
    values recorded on the last row (a row without Last-Modified cannot use it).

    ``encoded`` (a content-encoded response) is never identical: the encoding flag comes from the
    upstream, so it must not decide whether the bytes are read. Such an asset is fetched and hashed.
    """
    if not rows or encoded or cl is None or cl != last_known_size(rows):
        return False
    recorded_etag = last_known_etag(rows)
    if etag is not None and recorded_etag is not None:
        return etag == recorded_etag
    if etag is not None or recorded_etag is not None:
        return False  # one side has an ETag and the other does not: not comparable
    recorded_lm = rows[-1].get("upstream_last_modified")
    return last_modified is not None and last_modified == recorded_lm
