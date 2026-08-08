// Tests for pipeAnthropicSSE's usage-accounting fault signal.
//
// The daily $ cap is only as trustworthy as the usage numbers it accounts.
// A genuinely completed Anthropic call always reports positive input AND
// output token counts; if either is still zero after the stream drains, the
// upstream usage shape has moved (or was absent) and downstream cost
// accounting must NOT read that as a real, free ($0) call. These tests pin
// the `usageParsed` signal that pipeAnthropicSSE hands to its onDone callback.

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { pipeAnthropicSSE } from "../chat_sse.js";
import {
  anthropicSSEResponse,
  anthropicSSEMovedUsageResponse,
} from "./fixtures/anthropic_sse.js";

function collectingController() {
  return {
    frames: [],
    enqueue(x) {
      this.frames.push(x);
    },
    close() {},
  };
}

describe("pipeAnthropicSSE usage accounting", () => {
  test("canonical response → usageParsed true with positive token counts", async () => {
    const res = anthropicSSEResponse("Roswell appears in [card-a:1].", {
      inputTokens: 100,
      outputTokens: 50,
    });
    let done;
    await pipeAnthropicSSE(collectingController(), res.body, async (d) => {
      done = d;
    });
    assert.equal(done.usageParsed, true);
    assert.equal(done.usage.input_tokens, 100);
    assert.equal(done.usage.output_tokens, 50);
  });

  test("moved usage fields → usageParsed false (fault, not a silent zero)", async () => {
    const res = anthropicSSEMovedUsageResponse("Roswell appears in [card-a:1].");
    let done;
    await pipeAnthropicSSE(collectingController(), res.body, async (d) => {
      done = d;
    });
    // The parser can no longer find the token counts...
    assert.equal(done.usage.input_tokens, 0);
    assert.equal(done.usage.output_tokens, 0);
    // ...and MUST flag that as a fault so cost accounting doesn't charge $0.
    assert.equal(done.usageParsed, false);
  });
});
