// Tests for cosine top-k over a flat Float32Array of corpus vectors.
//
// Layout: corpus is a single Float32Array of length n*dim, row-major.
// `pages` is a parallel array of {card_id, page} length n. The function
// returns the top-k indices by cosine similarity to the query, with their
// scores, sorted desc.

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { cosineTopK, normalizeVector } from "../retrieve.js";

function flatCorpus(rows) {
  // rows: number[][]
  const dim = rows[0].length;
  const out = new Float32Array(rows.length * dim);
  for (let i = 0; i < rows.length; i += 1) {
    for (let j = 0; j < dim; j += 1) out[i * dim + j] = rows[i][j];
  }
  return out;
}

describe("cosineTopK", () => {
  test("identical vector → score 1.0 ranked first", () => {
    const corpus = flatCorpus([
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ]);
    const query = new Float32Array([1, 0, 0]);
    const hits = cosineTopK(query, corpus, 3, 3);
    assert.equal(hits[0].index, 0);
    assert.ok(Math.abs(hits[0].score - 1.0) < 1e-6);
  });

  test("orders strictly by descending similarity", () => {
    const corpus = flatCorpus([
      [1, 0, 0], // perfect
      [0.9, 0.1, 0], // close
      [0, 1, 0], // orthogonal
      [-1, 0, 0], // opposite
    ]);
    const query = new Float32Array([1, 0, 0]);
    const hits = cosineTopK(query, corpus, 4, 4);
    assert.equal(hits.length, 4);
    assert.equal(hits[0].index, 0);
    assert.equal(hits[1].index, 1);
    assert.equal(hits[2].index, 2);
    assert.equal(hits[3].index, 3);
    assert.ok(hits[0].score > hits[1].score);
    assert.ok(hits[1].score > hits[2].score);
    assert.ok(hits[2].score > hits[3].score);
  });

  test("respects k limit (k < n)", () => {
    const corpus = flatCorpus([
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
      [0.5, 0.5, 0],
    ]);
    const query = new Float32Array([1, 0, 0]);
    const hits = cosineTopK(query, corpus, 2, 4);
    assert.equal(hits.length, 2);
    assert.equal(hits[0].index, 0);
  });

  test("handles fewer-than-k corpus entries (k > n)", () => {
    const corpus = flatCorpus([
      [1, 0, 0],
      [0, 1, 0],
    ]);
    const query = new Float32Array([1, 0, 0]);
    const hits = cosineTopK(query, corpus, 8, 2);
    assert.equal(hits.length, 2);
  });
});

describe("normalizeVector", () => {
  test("scales vector to unit length", () => {
    const v = new Float32Array([3, 4]);
    const u = normalizeVector(v);
    const mag = Math.hypot(u[0], u[1]);
    assert.ok(Math.abs(mag - 1.0) < 1e-6);
    assert.ok(Math.abs(u[0] - 0.6) < 1e-6);
    assert.ok(Math.abs(u[1] - 0.8) < 1e-6);
  });

  test("returns the original zero vector unchanged (no division by zero)", () => {
    const v = new Float32Array([0, 0, 0]);
    const u = normalizeVector(v);
    assert.equal(u[0], 0);
    assert.equal(u[1], 0);
    assert.equal(u[2], 0);
  });
});
