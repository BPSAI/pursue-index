"""Rebuild ``data/external/alex-zhang42-corpus.jsonl`` from the upstream HF parquet.

Requires ``huggingface_hub`` and ``pyarrow`` (not core deps; install with
``pip install huggingface_hub pyarrow`` before running).


The dataset (alex-zhang42/ufo-pursue-open-atlas) ships its records as
``text/train.parquet`` (the ``text`` config of the dataset). Their
``schema.md`` calls the JSONL form ``corpus.jsonl``, but only the parquet
is actually published. This script materializes the JSONL form via a
deterministic projection of the parquet rows so we have a stable,
hashable artifact in the repo.

Output is byte-stable across runs as long as:

- The pinned HF revision is the same.
- ``json.dumps`` ordering follows the parquet's column order.
- Datetime cells are normalized to their ``isoformat`` string.

Run from repo root:

    python scripts/build_alex_zhang_corpus.py

This refreshes ``alex-zhang42-corpus.jsonl``,
``alex-zhang42-corpus.sha256``, and ``alex-zhang42-corpus.revision``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download

REPO_ID = "alex-zhang42/ufo-pursue-open-atlas"
PARQUET_PATH = "text/train.parquet"
OUT_DIR = Path("data/external")
OUT_JSONL = OUT_DIR / "alex-zhang42-corpus.jsonl"
OUT_SHA = OUT_DIR / "alex-zhang42-corpus.sha256"
OUT_REVISION = OUT_DIR / "alex-zhang42-corpus.revision"

# The upstream HF revision this script was written against. A re-run
# against a different HEAD is an explicit operator decision, not an
# accident: bump this constant in the same commit that updates the
# sidecars + JSONL. SEC-003 fail-closed posture: the `.revision` sidecar
# alone isn't enough — it gets rewritten alongside the JSONL on every
# run, so the safety check has to live in code that the developer reads.
PINNED_REVISION = "b0f0c79924b88d339846aa9fc4283958fe15682b"


def _normalize_record(rec: dict) -> dict:
    """Replace any datetime-like cells with ISO strings (parquet quirks)."""
    for key, value in list(rec.items()):
        if hasattr(value, "isoformat") and not isinstance(value, str):
            rec[key] = value.isoformat()
    return rec


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    info = HfApi().dataset_info(REPO_ID)
    head_sha = info.sha
    if head_sha != PINNED_REVISION:
        raise RuntimeError(
            f"upstream HEAD {head_sha} != PINNED_REVISION {PINNED_REVISION}. "
            f"Refusing to overwrite the committed corpus with a different "
            f"snapshot. To bump: change PINNED_REVISION in this script in "
            f"the same commit that updates corpus.jsonl + .sha256 + "
            f".revision."
        )
    revision = PINNED_REVISION
    print(f"revision: {revision}")

    parquet_path = hf_hub_download(
        repo_id=REPO_ID,
        filename=PARQUET_PATH,
        repo_type="dataset",
        revision=revision,
    )
    table = pq.read_table(parquet_path)
    print(f"rows: {table.num_rows}")

    with OUT_JSONL.open("w", encoding="utf-8") as fh:
        for rec in table.to_pylist():
            fh.write(json.dumps(_normalize_record(rec), ensure_ascii=False) + "\n")

    sha_hex = _hash_file(OUT_JSONL)
    OUT_SHA.write_text(f"{sha_hex}  {OUT_JSONL.name}\n")
    OUT_REVISION.write_text(revision + "\n")
    size_mb = OUT_JSONL.stat().st_size / 1024 / 1024
    print(f"wrote {OUT_JSONL} ({size_mb:.2f} MB)")
    print(f"sha256: {sha_hex}")


if __name__ == "__main__":
    main()
