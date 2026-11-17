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
python scripts/intermediates.py rebuild-check --tarball intermediates/intermediates-<tag>.tar.gz \
    --expect-sha256 <sha256 from the release notes>
```

`SHA256SUMS` travels with the tarball, so it only catches a corrupted
download. `--expect-sha256` pins the tarball to a value published separately
(the release notes), which also catches a substituted file. The check refuses
to run without it unless you pass `--allow-unpinned`.

A second pin, carried by git itself rather than the release notes: when
`data/build-stamp.json` at `<tag>` has an `intermediates` key, it records the
archive's name and sha256, and the checked-out stamp can vouch for the
download:

```bash
python scripts/build_stamp.py verify --root . --require \
    --intermediates intermediates/intermediates-<tag>.tar.gz
```

It exits 1, naming both sha256s, when the tarball differs from the stamped
one, and also when the stamp has no `intermediates` key (stamps from before
the key was added do not). On a pass, the stamped sha256 is the value to give
`--expect-sha256`.

`rebuild-check` needs no data root, no network and no API keys. It:

1. checks the tarball against `SHA256SUMS` (required) and the pinned sha256,
   refuses anything over its unpack limits, and checks every file inside it
   against the tarball's `MANIFEST.json`;
2. runs this checkout's three builders on the unpacked files alone;
3. compares their output with the committed `pages.json`,
   `pages-cleaned.json`, `embed_index.json` and `embeddings.bin`.

The build timestamp in `pages-cleaned.json`'s `meta` is the only difference
it ignores. It exits 1 and names the differing fields on any other
difference, for example when the checked-out builder records a field that the
committed payload predates.

## Making the asset

The release build packs the intermediates itself when given the release's
label:

```bash
make ship-ready INTERMEDIATES_LABEL=vX.Y.Z    # PURSUE_DATA_ROOT set to the data root
```

After the derived payloads are rebuilt and the site is built (the data root
is final by then), just before stamping, ship-ready packs the intermediates into
`$PURSUE_DATA_ROOT/release-assets/vX.Y.Z/`, outside the repository, runs
`rebuild-check` on the result pinned to the `SHA256SUMS` it just wrote, and
then stamps `data/build-stamp.json` with the tarball's name and sha256. Its
closing `build_stamp.py verify` checks the tarball against the stamp too. It
refuses a label that is not `vX.Y.Z`, a label without `PURSUE_DATA_ROOT`, and a
`PURSUE_DATA_ROOT` inside the repository, before any build time is spent.
Without `INTERMEDIATES_LABEL`, ship-ready neither packs nor pins anything.

The same steps by hand:

```bash
python scripts/intermediates.py pack --data-root <data root> --out-dir <dir> --label <tag>
python scripts/intermediates.py rebuild-check --tarball <dir>/intermediates-<tag>.tar.gz \
    --expect-sha256 "$(cut -d' ' -f1 <dir>/SHA256SUMS)"
```

## Attaching the asset to the Release

After the release commit carrying that stamp is merged, tagged, and its
Release created (`gh release create vX.Y.Z`):

```bash
make release-intermediates TAG=vX.Y.Z
```

It runs `sha256sum -c` on the packed files, then refuses unless the stamp
committed at `HEAD` pins the tarball, and unless no packed QC row carries a
field the pack drops. Only then does it run
`gh release upload vX.Y.Z intermediates-vX.Y.Z.tar.gz SHA256SUMS`. It never
creates the Release, edits its notes, or replaces an asset already attached
(no `--clobber`); replacing one is a deliberate manual step. It prints the
`SHA256SUMS` line; paste it into the release notes, so readers can pin it.

The archive is deterministic: members are sorted and their times and owners
are zeroed, so the same inputs always give the same sha256. Backup and partial
files beside the intermediates are never packed, and neither is anything
reached through a symlink.
