"""R2 upload step for ``r2_archive_assets.py``: immutable archive PUT + current pointer."""

from __future__ import annotations

from typing import Any


def put_archive_and_current(
    client: Any,
    bucket: str,
    archive_key: str,
    current_key: str,
    body: bytes,
    content_type: str,
) -> bool:
    """PUT the bytes to the archive key and the current key.

    Returns True when the archive key already existed (archive hit).
    """
    archive_hit = False
    # Some other card may already have archived these exact bytes
    # (cross-card duplicates are rare but possible — content-addressed
    # storage handles them automatically). Use If-None-Match: "*" on
    # the archive PUT so even a compromised key cannot overwrite
    # historical bytes: a write to an existing archive key fails with
    # HTTP 412 PreconditionFailed at the R2 API layer rather than
    # silently replacing. This is the load-bearing immutability
    # guarantee for the byte-history claim.
    try:
        client.put_object(
            Bucket=bucket,
            Key=archive_key,
            Body=body,
            ContentType=content_type,
            IfNoneMatch="*",
        )
    except Exception as exc:
        # PreconditionFailed (412) when an object already exists.
        # boto3 surfaces this as ClientError with Code 'PreconditionFailed'.
        err = getattr(exc, "response", {}).get("Error", {})
        if err.get("Code") in (
            "PreconditionFailed",
            "PreconditionFailedException",
            "412",
        ):
            archive_hit = True
        else:
            # Any other failure is a real error — re-raise so the
            # workflow sees it and the registry row is NOT written.
            raise
    # Always update the "current" pointer to the latest bytes.
    # No IfNoneMatch here — current is deliberately overwritten on
    # every fetch (it's the "latest known" pointer the worker
    # serves). Byte-history is preserved by the archive PUT above
    # + the registry row that records what was current at each
    # timestamp.
    client.put_object(
        Bucket=bucket,
        Key=current_key,
        Body=body,
        ContentType=content_type,
    )
    return archive_hit
