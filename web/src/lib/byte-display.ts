// Byte-size + percentage-delta formatters used by Sprint 4g surfaces
// (card-detail "bytes changed upstream" banner + /altered listing
// table). Extracted to a single source of truth so the two consumers
// don't drift — the `+∞` sentinel for zero-prior, the `< 1024` /
// `< 1024*1024` boundaries, and the sign convention are all pinned
// by the co-located tests.

/**
 * Human-readable byte count. Boundaries: < 1KB → bytes, < 1MB → KB
 * with one decimal, otherwise MB with two decimals. No locale-aware
 * thousands separators so the output is stable across runners /
 * browsers (any future hydration consumer would otherwise see SSR/CSR
 * mismatch from differing locale defaults).
 */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

/**
 * Signed percentage delta from ``prior`` to ``current``, formatted to
 * one decimal with an explicit ``+`` sign for non-negative values.
 *
 * The zero-prior case returns the ``+∞`` sentinel so the UI doesn't
 * surface a NaN/Inf division — the only case where this fires is a
 * card whose first-seen registry row had ``byte_size: 0`` (which
 * shouldn't happen in practice — would suggest a malformed registry).
 */
export function sizeDeltaPct(prior: number, current: number): string {
  if (prior === 0) return "+∞";
  const pct = ((current - prior) / prior) * 100;
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}
