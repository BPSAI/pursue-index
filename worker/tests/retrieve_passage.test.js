// Tests for buildPassage — the single place a retrieval hit becomes a
// citation. A citation with an empty title or snippet is unusable to the
// chat model and reads as a blank source to the user, so a lookup miss has
// to be an explicit skip, not a silent blank.

import { describe, test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { buildPassage } from "../retrieve_passage.js";
import { makeSnippet } from "../retrieve.js";

let warnings;
const realWarn = console.warn;

beforeEach(() => {
  warnings = [];
  console.warn = (...args) => warnings.push(args.join(" "));
});

afterEach(() => {
  console.warn = realWarn;
});

function build(pageRec, opts = {}) {
  return buildPassage({
    card_id: opts.card_id || "abc123",
    page: opts.page ?? 2,
    pageRec,
    query: opts.query ?? "disc",
    score: opts.score ?? 0.42,
    makeSnippetFn: makeSnippet,
  });
}

describe("buildPassage", () => {
  test("returns a citation when the page record has title and text", () => {
    const passage = build({
      card_id: "abc123",
      page: 2,
      title: "DOW-UAP-D017",
      text: "A metallic disc was observed over the range.",
    });
    assert.equal(passage.card_id, "abc123");
    assert.equal(passage.page, 2);
    assert.equal(passage.title, "DOW-UAP-D017");
    assert.ok(passage.snippet.includes("disc"));
    assert.equal(passage.score, 0.42);
    assert.equal(warnings.length, 0);
  });

  test("skips and logs when the page record is missing", () => {
    assert.equal(build(undefined), null);
    assert.equal(warnings.length, 1);
    assert.match(warnings[0], /abc123/);
    assert.match(warnings[0], /p2/);
  });

  test("skips and logs when the page text is empty", () => {
    assert.equal(
      build({ card_id: "abc123", page: 2, title: "DOW-UAP-D017", text: "  " }),
      null,
    );
    assert.equal(warnings.length, 1);
  });

  test("skips and logs when the title is empty", () => {
    assert.equal(
      build({ card_id: "abc123", page: 2, title: "", text: "readable text" }),
      null,
    );
    assert.equal(warnings.length, 1);
  });
});
