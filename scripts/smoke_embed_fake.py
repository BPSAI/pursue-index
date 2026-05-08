#!/usr/bin/env python3
"""End-to-end smoke for the embed pipeline with a deterministic fake.

Drops a real VOYAGE_API_KEY requirement so we can prove the pipeline +
web build script compose correctly against the actual NAS OCR output.
The vectors are bogus (hash-derived 8-dim floats) — this is for shape
validation only, not retrieval quality.

Usage:
    .venv/bin/python scripts/smoke_embed_fake.py [--limit 20]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.config import settings  # noqa: E402
from pursue_index.embed.pipeline import embed_run  # noqa: E402
from pursue_index.embed.voyage import EmbedResult  # noqa: E402


class FakeEmbedder:
    """Deterministic 8-dim embedder — same text in, same vector out."""

    model = "fake-8d"

    def __init__(self) -> None:
        self.dim = 8

    def embed_texts(self, texts: list[str], input_type: str = "document") -> EmbedResult:
        vectors: list[list[float]] = []
        for t in texts:
            seed = sum(ord(c) for c in t[:200]) or 1
            vectors.append([float((seed * (i + 11)) % 997) / 1000.0 for i in range(self.dim)])
        return EmbedResult(vectors=vectors, total_tokens=sum(len(t) for t in texts))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    print(f"OCR root: {settings.ocr_dir}")
    print(f"Embed root: {settings.embeddings_dir}")
    settings.ensure_dirs()

    t0 = time.time()
    summary = embed_run(
        ocr_dir=settings.ocr_dir,
        out_root=settings.embeddings_dir,
        embedder=FakeEmbedder(),
        batch_size=64,
        limit=args.limit,
        cost_cap_usd=0.01,  # fake: no cost
        usd_per_million_tokens=0.0,
    )
    elapsed = time.time() - t0
    out = settings.embeddings_dir / "fake-8d"
    print(
        f"embedded {summary.embedded} pages, skipped {summary.skipped}, "
        f"{summary.cards_seen} cards seen, {elapsed:.1f}s, "
        f"vectors.bin={(out / 'vectors.bin').stat().st_size}B"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
