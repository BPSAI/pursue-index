// Float32 cosine math for /api/retrieve, kept as pure functions so they
// can be tested without mocking ASSETS or fetch. The Worker scores float16
// rows (retrieve_vectors.js); `cosineTopK` over a decoded Float32Array is
// the reference that path is tested against.

/**
 * Normalize a vector to unit length, in-place safe.
 * Returns a new Float32Array; leaves the input untouched. Zero vectors
 * are returned as-is (no division by zero).
 */
export function normalizeVector(v) {
  let sum = 0;
  for (let i = 0; i < v.length; i += 1) sum += v[i] * v[i];
  if (sum === 0) return new Float32Array(v);
  const inv = 1 / Math.sqrt(sum);
  const out = new Float32Array(v.length);
  for (let i = 0; i < v.length; i += 1) out[i] = v[i] * inv;
  return out;
}

/**
 * Top-k cosine similarity over a flat Float32Array corpus of shape
 * (n*dim) row-major. Returns sorted [{index, score}] descending.
 *
 * Both `query` and `corpus` may or may not be pre-normalized; we don't
 * assume. The corpus is normalized lazily by the caller (we ship
 * unit-norm voyage-3 vectors so this is essentially a dot product).
 */
export function cosineTopK(query, corpus, k, n) {
  const dim = query.length;
  // Normalize the query once.
  const q = normalizeVector(query);
  // Use a partial sort: collect all (index, score) then sort. n=4119 is
  // small enough that a heap is over-engineered.
  const scores = new Array(n);
  for (let i = 0; i < n; i += 1) {
    let dot = 0;
    let mag = 0;
    const base = i * dim;
    for (let j = 0; j < dim; j += 1) {
      const v = corpus[base + j];
      dot += q[j] * v;
      mag += v * v;
    }
    const denom = mag === 0 ? 1 : Math.sqrt(mag);
    scores[i] = { index: i, score: dot / denom };
  }
  scores.sort((a, b) => b.score - a.score);
  return scores.slice(0, Math.min(k, n));
}
