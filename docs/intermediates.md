# Pipeline intermediates

The published search, cleaned-text and embedding payloads under
`web/public/data/` are built from three intermediates that a clone of this
repository does not contain:

| Intermediate | Archive path | Read by |
|---|---|---|
| Per-page OCR and transcript text, and each card's engine record | `ocr/<card_id>/pages.jsonl`, `ocr/<card_id>/meta.json` | `build_search_data.py` |
| Cleaned page text and its QC verdicts | `ocr/<card_id>/pages_cleaned.jsonl`, `ocr/<card_id>/pages_cleaned_qc.jsonl` | `build_pages_cleaned.py` |
| Float32 page embeddings and their row index | `embeddings/voyage-3/vectors.bin`, `embeddings/voyage-3/index.json` | `build_embed_data.py` |

Regenerating them needs paid model calls, and the result is not repeatable:
LLM OCR and cleanup produce different text on a rerun. So instead of
regenerating them, a release can carry them as an asset,
`intermediates-<tag>.tar.gz`, with a `SHA256SUMS` file beside it.

## Verifying a release from its intermediates

On a release that carries the asset:

```bash
gh release download <tag> -R BPSAI/pursue-index -p 'intermediates-*' -p SHA256SUMS -D intermediates/
sha256sum -c intermediates/SHA256SUMS
git checkout <tag>
python scripts/intermediates.py rebuild-check --tarball intermediates/intermediates-<tag>.tar.gz
```

`rebuild-check` needs no data root, no network and no API keys. It:

1. checks the tarball against `SHA256SUMS` and every file inside it against
   the tarball's `MANIFEST.json`;
2. runs this checkout's three builders on the unpacked files alone;
3. compares their output with the committed `pages.json`,
   `pages-cleaned.json`, `embed_index.json` and `embeddings.bin`.

The build timestamp in `pages-cleaned.json`'s `meta` is the only difference
it ignores. It exits 1 and names the differing fields on any other
difference, for example when the checked-out builder records a field that the
committed payload predates.

## Making the asset

The release operator packs the intermediates from the data root the release
was built from:

```bash
python scripts/intermediates.py pack --data-root <data root> --out-dir <dir> --label <tag>
python scripts/intermediates.py rebuild-check --tarball <dir>/intermediates-<tag>.tar.gz
```

The archive is deterministic: members are sorted and their times and owners
are zeroed, so the same inputs always give the same sha256. Backup and partial
files beside the intermediates are never packed.
