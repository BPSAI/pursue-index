/**
 * Tests for the corpus-qualifier helpers used by the per-card novelty
 * disclosure chips.
 *
 * The chip carries a parenthetical that names the reference corpus the
 * status was computed against — at v1.0.0 launch the corpus is a
 * synthetic placeholder, and the qualifier is the user-visible signal
 * that "NOVEL" / "PARTIAL" / "PREVIOUSLY DISCLOSED" is calibrated
 * against a tiny placeholder, not a real prior-disclosure archive.
 *
 * These tests pin the rendered text + the corpus tag (data-corpus
 * attribute) so when Black Vault integration lands, the qualifier can
 * swap to "(against Black Vault reference)" via a single update in
 * NoveltyFilter.ts rather than a per-chip rewrite.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CORPUS_QUALIFIER,
  corpusTag,
  disclosurePillLabel,
} from "./NoveltyFilter.ts";

test("CORPUS_QUALIFIER: default qualifier names the preview corpus", () => {
  // The literal text is asserted here because it's user-facing copy
  // that operator review on the PR is gated on.
  assert.equal(CORPUS_QUALIFIER, "(against preview corpus)");
});

test("corpusTag: preview/synthetic-placeholder/empty all map to 'preview'", () => {
  assert.equal(corpusTag("synthetic-placeholder"), "preview");
  assert.equal(corpusTag(""), "preview");
  assert.equal(corpusTag(undefined), "preview");
});

test("corpusTag: a named real corpus is passed through as its id", () => {
  // Future: when Black Vault ships, callers will switch the
  // data-corpus attribute via a single component constant rather
  // than per-chip rewrites.
  assert.equal(corpusTag("blackvault"), "blackvault");
});

test("disclosurePillLabel: emits status + qualifier for each disclosure status", () => {
  assert.deepEqual(disclosurePillLabel("novel"), {
    status: "NOVEL",
    qualifier: "(against preview corpus)",
  });
  assert.deepEqual(disclosurePillLabel("partial"), {
    status: "PARTIAL",
    qualifier: "(against preview corpus)",
  });
  assert.deepEqual(disclosurePillLabel("previously-disclosed"), {
    status: "PREVIOUSLY DISCLOSED",
    qualifier: "(against preview corpus)",
  });
});

test("disclosurePillLabel: archive override swaps the qualifier wording", () => {
  // When the operator flips the reference corpus to Black Vault,
  // every chip on the site picks up the new qualifier from one place.
  assert.deepEqual(disclosurePillLabel("novel", "blackvault"), {
    status: "NOVEL",
    qualifier: "(against Black Vault reference)",
  });
});
