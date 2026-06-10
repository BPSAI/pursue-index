/**
 * Tests for the chat-scroll stickiness helper.
 *
 * The helper is extracted from ChatIsland so the auto-scroll-vs-user-intent
 * logic (the "fights the user during streaming" antipattern) is testable
 * without a DOM. ChatIsland calls it on every scroll event to decide whether
 * subsequent streamed deltas should keep pinning to bottom or leave the
 * user where they are.
 *
 * Run with ``node --test src/components/chat-scroll.test.ts``.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { shouldStickToBottom } from "./chat-scroll.ts";

test("at-bottom exact returns true", () => {
  // scrollHeight - scrollTop - clientHeight === 0  → exactly at bottom
  assert.equal(shouldStickToBottom(1000, 800, 200, 50), true);
});

test("within tolerance counts as at-bottom", () => {
  // 49px from bottom, tolerance 50 → still sticky
  assert.equal(shouldStickToBottom(1049, 800, 200, 50), true);
});

test("just past tolerance breaks stickiness", () => {
  // 60px from bottom, tolerance 50 → user scrolled away
  assert.equal(shouldStickToBottom(1060, 800, 200, 50), false);
});

test("far from bottom returns false", () => {
  // 500px from bottom — clearly reading earlier content
  assert.equal(shouldStickToBottom(1500, 800, 200, 50), false);
});

test("tolerance boundary is exclusive", () => {
  // dist === tolerance → NOT sticky (use strict < for predictability)
  assert.equal(shouldStickToBottom(1050, 800, 200, 50), false);
});

test("scrolled past bottom (overscroll) still sticky", () => {
  // Negative distance (rubber-band on iOS, content shorter than viewport)
  // → should clamp to sticky, never break stickiness on negative dist
  assert.equal(shouldStickToBottom(900, 800, 200, 50), true);
});

test("default tolerance applied when not provided", () => {
  // Helper exposes a sensible default; calling without explicit tolerance
  // matches the production default. Default is 50 — same value used in
  // ChatIsland — so 49px from bottom is still sticky, 60px is not.
  assert.equal(shouldStickToBottom(1049, 800, 200), true);
  assert.equal(shouldStickToBottom(1060, 800, 200), false);
});
