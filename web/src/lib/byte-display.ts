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

const ARCHIVE_KEY_PATTERN = /^archive\/[0-9a-f]{64}\.[a-z0-9]+$/;

/**
 * Convert a registry ``archive_key`` to its public URL path.
 *
 * Validates the key shape before interpolating into the URL — the
 * registry contract is ``archive/<sha256>.<ext>`` and that's also
 * what the worker route at ``/archive/<sha>.<ext>`` expects. Bad
 * shapes throw at build time (Astro static-generation surfaces the
 * error in the build log naming the offending card) rather than
 * producing broken or surprising links at runtime. Laverna PR #79
 * P2-1 / Vaivora PR #79 P2-3 — defense in depth even though the
 * data is operator-controlled.
 */
export function archiveHrefFromKey(key: string): string {
  if (!ARCHIVE_KEY_PATTERN.test(key)) {
    throw new Error(
      `archive_key has unexpected shape: ${JSON.stringify(key)} (expected archive/<64-hex>.<ext>)`,
    );
  }
  return `/${key}`;
}

/**
 * Whitelist of valid v2 category strings rendered into CSS class
 * names by the /altered/ pages. Operator-attested data is closed-
 * vocabulary at the schema layer (AlteredCategoryV2 Literal in
 * pursue-curate), but the consumer doesn't import that schema —
 * Laverna PR #79 P2-2: guard at the rendering boundary so a future
 * typo can't silently break the class binding.
 */
const VALID_V2_CATEGORIES = new Set([
  "re_processing",
  "procedural_correction",
  "content_change",
]);

export function categoryClass(category: string | null | undefined): string {
  if (category && VALID_V2_CATEGORIES.has(category)) {
    return `altered-cat-${category}`;
  }
  // Fallback aligns with categorySlug() — single vocabulary across
  // the CSS class binding and the data-category filter slot. Nayru
  // PR #79 round-3 P1: prior fallback was `altered-cat-unknown`
  // which mismatched the slug's `unverified`, so a v1-leakage row
  // had a coloured class that didn't match its filter token.
  return "altered-cat-unverified";
}

/**
 * Whitelist-normalized slug for ``data-category`` attributes the
 * client-side filter pill JS keys off of. Same vocabulary closure
 * as :func:`categoryClass` but with ``"unverified"`` as the
 * not-categorized sentinel (matches the pill button's
 * ``data-filter="unverified"`` value). Laverna PR #79 round-2 P2-1
 * / Nayru P2-1: the prior raw interpolation let operator typos
 * write through to the DOM where they'd silently become
 * unfilterable rows. Apply the same close-vocabulary guard at the
 * DOM-attribute boundary.
 */
export function categorySlug(category: string | null | undefined): string {
  if (category && VALID_V2_CATEGORIES.has(category)) return category;
  return "unverified";
}
