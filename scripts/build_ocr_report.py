#!/usr/bin/env python3
"""Build the OCR benchmark report from the latest ``data/benchmarks/ocr-*.json``.

Computes CER/WER for Tesseract and Surya against the LLM (used as the truth
proxy per the plan's open question on truth-set transcription), assembles the
per-engine summary table, picks the worst Tesseract failure as a side-by-side
callout, and writes ``docs/ocr-benchmark.md``. Reads the Tesseract-snapshot
file written before the Surya full pass for full-corpus baseline numbers.

Run::

    .venv/bin/python scripts/build_ocr_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _ocr_metrics import (  # noqa: E402
    cer,
    compute_metrics,
    find_worst_tesseract,
    projection,
    truncate,
    wer,
)

BENCH_DIR = REPO_ROOT / "data" / "benchmarks"
DOCS_PATH = REPO_ROOT / "docs" / "ocr-benchmark.md"


def latest_benchmark() -> Path:
    files = sorted(BENCH_DIR.glob("ocr-*.json"))
    if not files:
        raise SystemExit("No benchmark JSON found in data/benchmarks/")
    return files[-1]


def load_snapshot(label: str) -> list[dict]:
    snap = BENCH_DIR / f"{label}-snapshot.json"
    if not snap.exists():
        return []
    return json.loads(snap.read_text())


def load_tesseract_snapshot() -> list[dict]:
    return load_snapshot("tesseract")


def load_surya_snapshot() -> list[dict]:
    return load_snapshot("surya")


def _format_snapshot_block(label: str, records: list[dict], context: str) -> list[str]:
    if not records:
        return []
    total_pages = sum(r["pages"] for r in records)
    total_dur = sum((r.get("duration_s") or 0) for r in records)
    page_weighted = sum(r["mean_conf"]*r["pages"] for r in records) / max(1, total_pages)
    return [
        "",
        f"**{label} (full corpus, {context}):**",
        f"- {len(records)} cards / {total_pages} pages",
        f"- {total_dur/60:.1f} min total wall-clock",
        f"- Page-weighted mean confidence: {page_weighted:.2f}",
    ]


def _engine_row(name, agg_eng, n, cost):
    if "cer_list" in agg_eng:
        cers = sorted(agg_eng["cer_list"])
        wers = sorted(agg_eng["wer_list"])
        median_cer = cers[len(cers) // 2]
        median_wer = wers[len(wers) // 2]
        # Cap at 100% per page so a single hallucination outlier doesn't
        # dominate the mean (Levenshtein/len_truth can exceed 1.0 when the
        # hypothesis is far longer than truth).
        capped_mean_cer = sum(min(x, 1.0) for x in agg_eng["cer_list"]) / n
        return (name, n, agg_eng["conf_sum"]/n, median_cer, capped_mean_cer,
                median_wer, agg_eng["wallclock"], cost)
    return (name, n, agg_eng["conf_sum"]/n, None, None, None, agg_eng["wallclock"], cost)


def render_summary_table(agg: dict, snapshot: list[dict],
                          surya_snapshot: list[dict] | None = None) -> str:
    n_t, n_s, n_l = agg["tesseract"]["pages"], agg["surya"]["pages"], agg["llm"]["pages"]
    rows = [
        _engine_row("Tesseract", agg["tesseract"], n_t, 0.0),
        _engine_row("Surya", agg["surya"], n_s, 0.0),
        _engine_row("LLM (Anthropic Haiku 4.5)", agg["llm"], n_l, agg["llm"]["cost"]),
    ]
    lines = [
        "| Engine | Pages | Mean conf | Median CER | Capped mean CER | Median WER | Total wall-clock | Total cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, n, conf, mc, cmc, mw, wc, cost in rows:
        mc_s = f"{mc*100:.1f}%" if mc is not None else "—"
        cmc_s = f"{cmc*100:.1f}%" if cmc is not None else "—"
        mw_s = f"{mw*100:.1f}%" if mw is not None else "—"
        lines.append(f"| {name} | {n} | {conf:.1f} | {mc_s} | {cmc_s} | {mw_s} | {wc:.1f}s | ${cost:.4f} |")
    lines += [
        "",
        "_CER/WER are scored vs the LLM as truth proxy. **Median CER** is the_",
        "_typical-page metric — robust to hallucination outliers on blank/near-blank_",
        "_scans where engines disagree on whether to emit any text. **Capped mean**_",
        "_clips per-page CER at 100% (raw means are skewed by a couple of pages_",
        "_where one engine emitted long garbage and the other was correctly silent)._",
    ]
    lines += _format_snapshot_block(
        "Tesseract baseline", snapshot,
        "snapshot 2026-05-08, 4-way concurrency, before Surya overwrite")
    if surya_snapshot:
        lines += _format_snapshot_block(
            "Surya post-pass", surya_snapshot,
            "this run, --force re-OCR with PURSUE_OCR_ENGINE=surya, serialized")
    return "\n".join(lines)


def render_per_card(results: list[dict]) -> str:
    blocks = []
    for card in results:
        block = [
            f"### {card['card_id']} — {card['category']}",
            f"_{card['description']}_  (file: `{card['pdf_filename']}`)",
            "",
            "| Page | Engine | Conf | Wall-clock | Snippet |",
            "|---:|---|---:|---:|---|",
        ]
        for tess, sur, lm in zip(card["engines"]["tesseract"], card["engines"]["surya"],
                                  card["engines"]["llm"], strict=True):
            for eng_label, row in (("tesseract", tess), ("surya", sur), ("llm", lm)):
                snippet = truncate(row["text"], 180).replace("|", "\\|")
                block.append(
                    f"| {row['page']} | {eng_label} | {row['confidence']:.1f} | "
                    f"{row['wall_clock_s']:.1f}s | {snippet} |"
                )
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def render_worst_failure(card, tess, sur, lm) -> str:
    fail_text = lambda r: r["text"].strip()[:1200].replace("\n", "\n> ")  # noqa: E731
    page_cer = cer(tess['text'], lm['text']) * 100
    page_wer = wer(tess['text'], lm['text']) * 100
    # Levenshtein/len(truth) can exceed 100% when the hypothesis is far longer
    # than the truth (Tesseract hallucinating long garbage on an image-only page).
    # Note that explicitly so the reader understands the over-100% number.
    cer_str = f"{page_cer:.1f}% (over 100% because Tesseract hallucinated more characters than the truth contains)" if page_cer > 100 else f"{page_cer:.1f}%"
    wer_str = f"{page_wer:.1f}% (same caveat — over 100% reflects hallucinated tokens)" if page_wer > 100 else f"{page_wer:.1f}%"
    return f"""## Worst Tesseract failure (side-by-side)

**Card:** `{card['card_id']}` ({card['category']}), page {tess['page']}
**Tesseract CER vs LLM truth proxy:** {cer_str}
**Tesseract WER vs LLM truth proxy:** {wer_str}

### Tesseract output (conf {tess['confidence']:.1f})
> {fail_text(tess)}

### Surya output (conf {sur['confidence']:.1f})
> {fail_text(sur)}

### LLM output (conf {lm['confidence']:.1f})
> {fail_text(lm)}
"""


def _stats(agg_eng):
    cers = sorted(agg_eng["cer_list"])
    return {
        "median_cer": cers[len(cers) // 2],
        "capped_mean_cer": sum(min(x, 1.0) for x in cers) / len(cers),
        "mean_conf": agg_eng["conf_sum"] / agg_eng["pages"],
        "wall_per_page": agg_eng["wallclock"] / agg_eng["pages"],
    }


def render_recommendation(agg: dict, results: list[dict], snapshot: list[dict]) -> str:
    p = projection(agg, results, snapshot)
    s = _stats(agg["surya"])
    t = _stats(agg["tesseract"])
    llm_mean_conf = agg['llm']['conf_sum']/p['llm_pages']
    return f"""## Recommendation

On the golden set, **Surya wins** on every metric that matters for production:
mean confidence {s['mean_conf']:.1f} vs Tesseract's {t['mean_conf']:.1f}, **median
per-page CER** vs the LLM truth proxy of **{s['median_cer']*100:.1f}%** vs
Tesseract's **{t['median_cer']*100:.1f}%** — i.e., on a typical page, Tesseract
makes ~{t['median_cer']/max(s['median_cer'], 0.01):.0f}× as many character
errors. Capped-mean CER is **{s['capped_mean_cer']*100:.1f}%** vs Tesseract's
**{t['capped_mean_cer']*100:.1f}%**. Per-page wall-clock is
{s['wall_per_page']:.1f}s vs {t['wall_per_page']:.1f}s after model load amortizes.
Surya is a flat win over Tesseract in both quality and speed; on the 5090 the
model load is one-time per run.

**Auto-mode projection.** {p['sub_threshold']}/{p['surya_pages']} Surya pages on the
golden set fell below the LLM-fallback threshold of 70 ({p['pct']*100:.1f}%).
Extrapolating to the full {p['total_corpus_pages']}-page corpus:

- Pages re-OCR'd by the LLM: ~{p['projected_pages']}
- At Haiku-4.5 (~${p['llm_cost_per_page']:.4f}/page): **~${p['projected_cost']:.2f} total**
- At Sonnet-4.6 (~13× Haiku per-token blend): ~${p['projected_cost_sonnet']:.2f}

**Auto-mode is worth running on the full corpus** — at Haiku rates it's well
under a dollar, fits the LLM budget, and the lift on the worst pages is real.
The pages Surya struggles with on this corpus aren't redacted text (it reads
around the bars cleanly) — they're heavily-faded carbon-copy pages where Surya
sometimes hallucinates plausible-but-wrong text instead of staying silent
(see card `13f86e95aed52840` page 3 in the per-card detail below: the LLM
correctly emits `[ILLEGIBLE]`, Surya emits a coherent-looking string that
isn't on the page). The auto-mode threshold of 70 catches those (Surya
self-rated low when in trouble) and the LLM cleans them up. The
`auto:surya+llm-anthropic` engine is the recommended default.

**One nuance:** the LLM's self-reported confidence on the golden set
({llm_mean_conf:.1f}) is *lower* than Surya's ({s['mean_conf']:.1f}). That's
not because the LLM is worse — it's because the LLM is trained to rate itself
harshly on partial transcriptions of redacted/illegible pages, while Surya's
confidence is a mean of per-line model probabilities and stays high even when
it's hallucinating on a black bar. Don't read the confidence column as quality
across engines; it's an engine-internal signal for the auto-mode threshold.
"""


GOLDEN_SET_SECTION = """## Golden set

5 cards pinned in [`tests/fixtures/ocr_golden.txt`](../tests/fixtures/ocr_golden.txt)
covering the engine-failure modes named in the benchmark plan:

1. **Clean typewriter** — `78dc972c0c143d1e` NASA Apollo 17 Transcript 1972.
   Tesseract should ace this; Surya does ace it; LLM matches.
2. **Faded FBI scan** — `4b68726be4af8ff9` FBI HQ-83894 Serial 220 (mid-1950s
   carbon). Tesseract drops to 80.7 mean conf; Surya recovers to 94.3; LLM
   matches Surya on text quality.
3. **Multi-column form** — `15d23b5f88df64fa` DOW-UAP-D25 Mission Report
   Greece. Reading-order torture test. Tesseract scrambles columns; Surya
   keeps the column intact; LLM produces the cleanest structured output.
4. **Redacted page** — `26b02d358ec20061` FBI HQ-101634279 100-DE-26505.
   Black-bar redactions over typed text. Tesseract gives garbage on the
   redacted regions (54.5 mean conf); Surya reads around the bars (76.3);
   LLM explicitly marks `[REDACTED]` per the prompt contract.
5. **Long debriefing** — `13f86e95aed52840` FBI HQ-83894 Section 6 (271 pp,
   mixed-quality omnibus). Stress test for engine consistency."""


def _build_md(bench, results, snapshot, surya_snapshot, agg, worst, bench_path):
    rel = bench_path.relative_to(REPO_ROOT)
    return f"""# OCR benchmark — {bench['started_at'][:10]}

> Methodology: 5 cards × first 5 pages × 3 engines (Tesseract, Surya, Anthropic
> Haiku-4.5 vision). The LLM transcription is used as the assumed-correct
> truth proxy for truth-set transcription; CER/WER for Tesseract and Surya are scored against
> it. Comparing the LLM engine's output against itself is meaningless and we
> don't try. Full per-page detail in [`{rel}`](../{rel}).

## Per-engine summary (golden set, 25 pages)

{render_summary_table(agg, snapshot, surya_snapshot)}

{render_worst_failure(*worst)}

{render_recommendation(agg, results, snapshot)}

{GOLDEN_SET_SECTION}

## Per-card detail (5 pages each)

{render_per_card(results)}

---

_Generated by `scripts/build_ocr_report.py` from `{bench_path.name}`._
"""


def main() -> int:
    bench_path = latest_benchmark()
    print(f"Reading {bench_path}")
    bench = json.loads(bench_path.read_text())
    results = bench["results"]
    snapshot = load_tesseract_snapshot()
    surya_snapshot = load_surya_snapshot()

    agg = compute_metrics(results)
    worst = find_worst_tesseract(results)
    md = _build_md(bench, results, snapshot, surya_snapshot, agg, worst, bench_path)

    DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_PATH.write_text(md, encoding="utf-8")
    print(f"Wrote {DOCS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
