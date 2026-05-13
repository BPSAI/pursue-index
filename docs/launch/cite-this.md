# How to cite pursueindex

> A short citation guide for researchers, journalists, and academic readers
> using pursueindex as a reference. The corpus is U.S. Government work and
> in the public domain; we add the indexing layer (manifest, OCR
> transcripts, search). This page tells you how to point at us correctly.

---

## What you are actually citing

Three layers, three different citation targets. Pick the one that matches
your claim:

| Claim type                                | Cite                                  |
|-------------------------------------------|---------------------------------------|
| The contents of a source document         | The original DOW PDF (we're a reader) |
| A transcribed passage as it appears here  | This site, with `card_id` and page    |
| The corpus itself, or methodology         | This site, manifest snapshot          |

When in doubt, cite both: the original DOW PDF for the source authority,
and pursueindex for the page-level lookup that made the citation tractable.

---

## Citation format — the corpus as a whole

> *PURSUE Index*. (2026). BPS AI Software.
> https://pursueindex.com (manifest CSV SHA-256 `<csv_sha256>`,
> snapshot `<fetched_at>`).

Replace `<csv_sha256>` and `<fetched_at>` with the values shown in the
methodology page footer at the time of access. Both fields are visible at
<https://pursueindex.com/methodology#provenance>. The hash pin is the
load-bearing reproducibility claim — anyone with the same `csv_sha256` is
looking at the same upstream CSV bytes you cited.

---

## Citation format — a specific document or page

> *PURSUE Index* card `<card_id>`, p. `<n>`. Sourced from U.S. Department
> of War, *Presidential Unsealing and Reporting System for UAP Encounters*
> (PURSUE), Release 01 (2026). https://pursueindex.com/card/`<card_id>`#page-`<n>`

Worked example, citing FBI HQ-83894 Section 3, page 67 (the McHenry
affidavit from the Muroc 1947 entry):

> *PURSUE Index* card `99c12a9c49a91750`, p. 67. Sourced from U.S.
> Department of War, PURSUE Release 01 (2026).
> https://pursueindex.com/card/99c12a9c49a91750#page-67

The `card_id` is stable across re-fetches — it is `sha256(asset_url || title)[:16]`,
so the same card resolves the same way for every reader regardless of when
they re-run the pipeline. Page numbers are 1-indexed and match the original
PDF's page numbering.

---

## Citation format — the OCR transcript itself

If you are quoting the OCR transcript (not the original PDF text), make
that explicit. OCR is imperfect and the transcript is a derivative work:

> *PURSUE Index* OCR transcript, card `<card_id>`, p. `<n>`, OCR engine
> `<engine>` (confidence `<conf>`). https://pursueindex.com/card/`<card_id>`#page-`<n>`

`<engine>` is one of `surya`, `llm-anthropic`, or `tesseract` (legacy);
`<conf>` is the page-level mean confidence. Both are surfaced inline on
each card page.

When the OCR is wrong and the original PDF text is correct, cite the
original PDF and not us. We'd rather you do that than carry our error
forward.

---

## Reproducibility note (for academic readers)

The manifest is **hash-pinned and version-controlled** at
<https://github.com/BPSAI/pursue-index>. Every `csv_sha256` value
corresponds to a specific commit on `main`; readers can clone the repo,
check out the commit matching the hash you cited, and reproduce the
scrape, download, OCR, and embed stages from a clean machine. The full
pipeline costs under $2 to run end to end at current API rates.

For the strongest citation footing in published work, include both the
`csv_sha256` and the commit SHA visible at the methodology page footer at
the time of access. The two together give you a closed reproducibility
loop independent of upstream DOW changes.

---

## BibTeX

```bibtex
@misc{pursueindex2026,
  author       = {{BPS AI Software}},
  title        = {{PURSUE} {I}ndex: A Citable, Full-Text-Searchable Interface
                  to the {U.S.} {D}epartment of {W}ar's {PURSUE} {UAP}
                  Document Releases},
  year         = {2026},
  url          = {https://pursueindex.com},
  note         = {Manifest CSV SHA-256: \texttt{<csv_sha256>}; snapshot
                  \texttt{<fetched_at>}; accessed \texttt{<access_date>}}
}
```

For a specific card, append:

```bibtex
@misc{pursueindex2026_card_99c12a9c49a91750,
  author       = {{U.S. Department of War}},
  title        = {{FBI HQ-83894 Section 3}},
  howpublished = {\textit{PURSUE Index} card \texttt{99c12a9c49a91750}},
  year         = {2026},
  url          = {https://pursueindex.com/card/99c12a9c49a91750},
  note         = {Originally released as part of PURSUE Release 01;
                  retrieved via \url{https://pursueindex.com}}
}
```

---

## Suggested social-share text

For Twitter / Bluesky / Mastodon. All under 280 characters.

**General share:**

```
pursueindex.com — every page of the DOW's PURSUE UAP release, OCR'd and
citable. 4,161 pages, hash-pinned manifest, published quality benchmark.
Methodology: pursueindex.com/methodology
```

**Methodology angle:**

```
We OCR'd the entire DOW PURSUE UAP corpus (4,161 pages) for under $2:
Surya GPU primary, Anthropic vision fallback on sub-threshold pages.
Surya median CER 6.1% vs Tesseract 40.4%. pursueindex.com/methodology
```

**Primary-source angle:**

```
On July 8, 1947, while Roswell was retracting its "flying disc" press
release, five Army Air Forces personnel at Muroc gave sworn statements about
two separate disc sightings. The FBI file is now searchable.
pursueindex.com/finds/muroc-1947
```

---

## Errata and corrections

If you cite us and we later correct the underlying transcript, the URL
remains stable but the OCR text may change. We log every correction with
a commit SHA and a dated entry. For citation-stable scholarship, pin the
commit SHA in your `note` field as shown above; readers can recover the
exact transcript you cited via `git checkout <sha>`.

To report a correction: open an issue at
<https://github.com/BPSAI/pursue-index/issues> with the `card_id`, page
number, and a description of the discrepancy.
