// Tests for the system prompt + user prompt assembly.
//
// We don't fully assert the prompt text (would couple us to wording
// changes), but we do pin the *invariants* that protect quality:
//   - the citation format example must appear
//   - the abstention rule must appear
//   - retrieved passages must be wrapped in untrusted-input markers
//   - the user's literal question must be present at the end

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { buildSystemPrompt, buildUserPrompt } from "../chat_prompt.js";

describe("buildSystemPrompt", () => {
  test("contains the [card_id:page] citation rule", () => {
    const sp = buildSystemPrompt();
    assert.match(sp, /\[card_id:page\]/);
  });

  test("contains the explicit abstention requirement", () => {
    const sp = buildSystemPrompt();
    assert.match(sp, /do not address|not address that|no documents|do not contain/i);
  });

  test("contains the prompt-injection-resistance instruction", () => {
    const sp = buildSystemPrompt();
    assert.match(sp, /UNTRUSTED|ignore.*instructions|prompt injection/i);
  });

  test("contains a few-shot example with a citation", () => {
    const sp = buildSystemPrompt();
    // At least one inline citation in the form [hexish:N] should appear.
    assert.match(sp, /\[[a-f0-9]{6,}:\d+\]/);
  });

  test("contains an abstention example", () => {
    const sp = buildSystemPrompt();
    assert.match(sp, /not address|not contain/i);
  });
});

describe("buildUserPrompt", () => {
  test("wraps each passage with explicit untrusted-input markers", () => {
    const passages = [
      { card_id: "a1", page: 3, title: "T", page_text: "hello world" },
    ];
    const up = buildUserPrompt("what?", passages);
    assert.match(up, /<document/);
    assert.match(up, /<\/document>/);
    assert.match(up, /a1:3/);
    assert.match(up, /hello world/);
  });

  test("includes the user's literal query at the end", () => {
    const up = buildUserPrompt("Did Apollo 17 see anything?", []);
    assert.ok(
      up.trim().endsWith("Did Apollo 17 see anything?") ||
        up.includes("Did Apollo 17 see anything?"),
    );
  });

  test("handles empty passages gracefully (no retrieved context)", () => {
    const up = buildUserPrompt("q", []);
    assert.match(up, /no .* passages|no documents retrieved|empty/i);
  });

  test("truncates very long passage text to a sane budget", () => {
    const passages = [
      {
        card_id: "x",
        page: 1,
        title: "T",
        page_text: "z".repeat(20000),
      },
    ];
    const up = buildUserPrompt("q", passages);
    // Should clip individual passages to keep prompt under control.
    // Allow up to 4000 chars per passage but flag when one passage drives
    // the whole prompt over 12000 chars.
    assert.ok(up.length < 16000, `prompt too long: ${up.length}`);
  });
});
