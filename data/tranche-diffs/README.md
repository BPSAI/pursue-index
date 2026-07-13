# Tranche diffs

One-off run outputs from the tranche-diff tooling (`pursue` ingest path), one
pair per upstream-manifest comparison: a human-readable `.md` summary
(renames / net-new / quarantined / restorations / field-only changes) and its
machine-readable `.json` twin. `*-review.md` files are annotated review passes.

These are run artifacts, not plans — moved here from `.paircoder/plans/` on
2026-07-13. Each corresponds to an ingest task for a given upstream CSV sha.
