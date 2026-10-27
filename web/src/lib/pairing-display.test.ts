import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  cardHasTag,
  cardsInTagCollection,
  pairingDisplay,
} from "./pairing-display.ts";

describe("pairingDisplay", () => {
  test("a TAG: value renders as a collection chip", () => {
    const d = pairingDisplay("PDF pairing", "TAG:AAWSAP", "");
    assert.equal(d.kind, "tag");
    assert.equal(d.raw, "TAG:AAWSAP");
    if (d.kind === "tag") {
      assert.equal(d.tag, "AAWSAP");
      assert.equal(d.chipText, "AAWSAP collection");
      assert.equal(d.href, "/#tag=AAWSAP");
    }
  });

  test("the chip link is prefixed with the site base path", () => {
    const d = pairingDisplay("PDF pairing", "TAG:AAWSAP", "/pursue");
    assert.equal(d.kind, "tag");
    if (d.kind === "tag") {
      assert.equal(d.href, "/pursue/#tag=AAWSAP");
    }
  });

  test("an explicit DOW-UAP-... value renders verbatim, as today", () => {
    const d = pairingDisplay("PDF pairing", "DOW-UAP-D176", "");
    assert.deepEqual(d, {
      kind: "verbatim",
      label: "PDF pairing",
      raw: "DOW-UAP-D176",
    });
  });

  test("an explicit pipe-delimited document list renders verbatim", () => {
    const d = pairingDisplay(
      "PDF pairing",
      "DOW-UAP-D110 | DOW-UAP-D111",
      "",
    );
    assert.equal(d.kind, "verbatim");
    assert.equal(d.raw, "DOW-UAP-D110 | DOW-UAP-D111");
  });

  test("tag names with URL-unsafe characters are escaped in the href", () => {
    const d = pairingDisplay("PDF pairing", "TAG:FOO BAR", "");
    assert.equal(d.kind, "tag");
    if (d.kind === "tag") {
      assert.equal(d.href, "/#tag=FOO%20BAR");
    }
  });
});

describe("cardHasTag", () => {
  const card = (pdf: string | null, video: string | null = null) => ({
    card_id: "x",
    pdf_pairing: pdf,
    video_pairing: video,
  });

  test("matches an exact TAG: value on pdf_pairing", () => {
    assert.equal(cardHasTag(card("TAG:AAWSAP"), "AAWSAP"), true);
  });

  test("matches an exact TAG: value on video_pairing", () => {
    assert.equal(cardHasTag(card(null, "TAG:AAWSAP"), "AAWSAP"), true);
  });

  test("does not match a different tag", () => {
    assert.equal(cardHasTag(card("TAG:AAWSAP"), "OTHER"), false);
  });

  test("does not match an explicit document reference", () => {
    assert.equal(cardHasTag(card("DOW-UAP-D176"), "AAWSAP"), false);
  });

  test("does not match a null pairing", () => {
    assert.equal(cardHasTag(card(null), "AAWSAP"), false);
  });
});

describe("cardsInTagCollection", () => {
  test("filters a mixed list down to exactly the tagged cards", () => {
    const cards = [
      { card_id: "a", pdf_pairing: "TAG:AAWSAP", video_pairing: null },
      { card_id: "b", pdf_pairing: "DOW-UAP-D176", video_pairing: null },
      { card_id: "c", pdf_pairing: null, video_pairing: "TAG:AAWSAP" },
      { card_id: "d", pdf_pairing: "TAG:OTHER", video_pairing: null },
    ];
    assert.deepEqual(
      cardsInTagCollection(cards, "AAWSAP").map((c) => c.card_id),
      ["a", "c"],
    );
  });

  // Pins the filter against the real, committed manifest: the
  // AAWSAP collection is exactly 53 cards (upstream tranche
  // 096ef2c0058a, #177/#178), and every one of them carries the tag
  // on pdf_pairing specifically (none on video_pairing, today).
  test("against the committed manifest: AAWSAP collection is exactly 53 cards", () => {
    const manifest = JSON.parse(
      readFileSync(
        new URL("../data/manifest.json", import.meta.url),
        "utf-8",
      ),
    );
    const tagged = cardsInTagCollection(manifest.cards, "AAWSAP");
    assert.equal(tagged.length, 53);
    for (const c of tagged) {
      assert.equal(c.pdf_pairing, "TAG:AAWSAP");
    }
    const idSet = new Set(tagged.map((c) => c.card_id));
    assert.equal(idSet.size, 53, "card_ids must be unique");

    // Cross-check: cardHasTag must agree with cardsInTagCollection for
    // every card in the manifest, not just the ones it returned.
    const bruteForce = manifest.cards.filter((c: unknown) =>
      cardHasTag(c as { pdf_pairing: string | null; video_pairing: string | null }, "AAWSAP"),
    );
    assert.equal(bruteForce.length, 53);
  });
});
