import { test } from "node:test";
import assert from "node:assert/strict";
import { buildSearchHref } from "./homepage-search.ts";

// ---------------------------------------------------------------------------
// Cycle 1: empty query → land on /search with no query string. The user
// arrived at the homepage with no specific intent; sending them to a search
// page seeded with "" would either show "0 matches" (confusing) or empty
// results (also confusing). Just open the search input ready for fresh input.
// ---------------------------------------------------------------------------

test("empty query returns base + /search with no query string", () => {
  assert.equal(buildSearchHref("", ""), "/search");
  assert.equal(buildSearchHref("/", ""), "/search");
});

test("whitespace-only query is treated as empty", () => {
  assert.equal(buildSearchHref("", "   "), "/search");
  assert.equal(buildSearchHref("", "\t\n "), "/search");
});

// ---------------------------------------------------------------------------
// Cycle 2: non-empty queries are URI-encoded into the q= parameter.
// ---------------------------------------------------------------------------

test("simple ASCII query is appended as q=", () => {
  assert.equal(buildSearchHref("", "roswell"), "/search?q=roswell");
});

test("spaces in query are encoded as %20 (not '+')", () => {
  // encodeURIComponent uses %20 for spaces — confirms we're not using
  // the looser application/x-www-form-urlencoded '+' convention,
  // which trips up some servers/proxies.
  assert.equal(
    buildSearchHref("", "green fireballs"),
    "/search?q=green%20fireballs",
  );
});

test("reserved URL characters are encoded", () => {
  // & ? # all become %-escapes so a query like "tic-tac & gimbal"
  // doesn't accidentally inject a second query parameter.
  assert.equal(
    buildSearchHref("", "tic-tac & gimbal"),
    "/search?q=tic-tac%20%26%20gimbal",
  );
});

test("unicode in query is percent-encoded", () => {
  // Real-world example: foreign-language sighting names.
  assert.equal(buildSearchHref("", "OVNI"), "/search?q=OVNI");
  assert.equal(
    buildSearchHref("", "señor"),
    "/search?q=se%C3%B1or",
  );
});

// ---------------------------------------------------------------------------
// Cycle 3: base normalization. The site is deployed at
// import.meta.env.BASE_URL which Astro reports as `/` in our config — but
// the consumer in index.astro does `base.replace(/\/$/, "")` to strip the
// trailing slash. Defensive: handle both shapes ourselves.
// ---------------------------------------------------------------------------

test("trailing slash on base is stripped", () => {
  assert.equal(buildSearchHref("/preview/", "x"), "/preview/search?q=x");
});

test("base without trailing slash works as-is", () => {
  assert.equal(buildSearchHref("/preview", "x"), "/preview/search?q=x");
});

test("nested base path is preserved", () => {
  // Hypothetical future CF Pages preview at /pr-42/. Keeps us safe if the
  // site ever moves off the root.
  assert.equal(buildSearchHref("/pr-42", "ufo"), "/pr-42/search?q=ufo");
});
