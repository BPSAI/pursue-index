---
id: accessibility-audit-and-remediation
type: feature
status: backlog
created: 2026-05-10
priority: high
depends_on: []
---

# Accessibility audit and remediation (WCAG AA)

## Summary

Run a structured accessibility audit across all live pursueindex.com
surfaces and remediate to WCAG 2.2 Level AA. The site positions as a
citable research interface for U.S. government UAP documents; screen-
reader users, motor-impaired users, keyboard-only users, and low-
vision users are exactly the audience we want — failing them is the
wrong posture for the project. This plan is operator-attended (manual
testing required) and pairs an automated scan with hands-on
verification across a small matrix of assistive technologies.

## Why

The v1.0.0 launch was infrastructure-first: pipeline, corpus integrity,
editorial bar. Accessibility wasn't formally audited. The terminal /
scanlines aesthetic uses signal colors that may not hit 4.5:1 contrast
for body text, the `/atlas` WebGL canvas has no accessible alternative,
and several custom-styled buttons may have lost their default focus
rings. None of these block the site from working for sighted mouse
users, but they do exclude meaningful audiences from a public-domain
archive.

This is also a credibility surface for journalists and researchers,
many of whom run accessibility-checker browser extensions as a matter
of habit. Failing those checks on a "citable research" project lands
poorly. WCAG AA is the realistic baseline; AAA where it lands cheap.

## Scope

### Surfaces in scope

- `/` (homepage)
- `/search`, `/finds`, `/finds/<slug>`
- `/card/<id>` (reader-mode toggle: Raw / Reader / Cleaned)
- `/atlas` — special case, needs accessible alternative
- `/chat`
- `/api`, `/methodology`, `/cite`, `/about`, `/diff`
- The shared `Base.astro` layout (topbar, footer, nav, badge)

### Concerns to audit

| Area | Specific check |
|---|---|
| Color contrast | Body text ≥4.5:1; large text ≥3:1; non-text UI ≥3:1. Test every signal color (`signal-green`, `signal-cyan`, `signal-violet`, `signal-amber`, `signal-red`) against every background (`bg-deep`, `bg-elevated`, `bg/60`). |
| Heading hierarchy | One `<h1>` per page; no skipped levels; logical document outline. |
| Landmark regions | `<main>`, `<nav>`, `<aside>`, `<footer>` present; supplementary landmarks labeled. |
| Skip-to-content | Visible-on-focus link in the layout for keyboard users. |
| Focus management | Every interactive element has a visible `:focus-visible` ring; custom-styled buttons aren't suppressing the default. |
| Keyboard traversal | Tab order is logical; no keyboard traps; modal-style components return focus on close. |
| ARIA labels | Icon-only buttons (reader-mode toggle, atlas controls, search clear, chat send, mobile nav) carry `aria-label`. |
| ARIA live regions | Chat response streaming uses `aria-live="polite"`; search-result count updates announced. |
| Alt text | All `<img>` carry meaningful `alt` (or `alt=""` for decorative); `modal_image_url` on cards, OG images, badge icons. |
| `prefers-reduced-motion` | Scanlines animation, atlas dot animations, page transitions all respect the media query. |
| Form labels | Every input has an associated `<label>` or `aria-labelledby`. |
| Error messaging | 404 page, error states surface clearly; not color-only. |
| Document language | `<html lang="en">` set; `og:locale="en_US"` in meta. |
| Time-based content | Chat streaming + atlas auto-zoom don't move out from under a reader. |

### `/atlas` accessible alternative (special case)

The 2D UMAP projection is inherently visual and non-keyboard-traversable.
The remediation is a parallel accessible surface, not a retrofit of
the canvas:

- Provide a `Browse by agency` tab adjacent to the canvas that renders
  a sortable HTML table of all cards (card_id, title, agency, date,
  redacted-flag), keyboard-traversable with `aria-sort` on column
  headers.
- Provide a `Browse by date` chronological list (same data, different
  ordering).
- Use `aria-describedby` on the canvas itself to summarize what's
  shown ("4,119 dots projected by semantic similarity, colored by
  agency: 1,260 Department of War, 2,679 FBI, 145 NASA, 35 Department
  of State"). The summary alone gives a screen-reader user the shape
  of the data without needing to interpret the canvas.
- The mobile cluster fallback (removed in PR #30) is conceptually the
  right shape for this. The plan should NOT re-introduce mobile-only
  fallback semantics; rather it should add a tab that's available on
  all viewports.

## Cost

- Audit pass: ~half-day (automated + manual)
- Remediation: ~1 day (most fixes are small; atlas alternative is the
  longest tail)
- Verification: ~half-day (re-run automated scans, manual screen-
  reader smoke)
- Total: ~2 days operator-attended (or driver-orchestrated with
  operator manual-testing checkpoints)
- No external API cost.

## Bring-Up Phases

1. **Automated baseline audit**: run `axe-core` (via `@axe-core/cli`
   or browser devtools) and Lighthouse accessibility scan over every
   live route. Capture before-state findings as a checklist in the
   PR description.
2. **Color-contrast pass**: programmatic check every signal-color +
   background combination via a small script reading the CSS variable
   palette. Flag any combination under WCAG AA. Adjust either the
   color tokens or the usage rules (e.g. signal-amber only on
   bg-deep, not on bg-elevated).
3. **Keyboard + screen-reader manual pass**: tab through every page;
   verify focus visibility, focus order, ARIA labels, live region
   announcements. Test with one screen reader (NVDA on Windows or
   VoiceOver on macOS).
4. **Reduced-motion pass**: add `@media (prefers-reduced-motion:
   reduce)` rules for scanlines, atlas dot easing, page transitions.
5. **Atlas accessible alternative**: implement the agency/date tab
   surface alongside the canvas. Wire keyboard navigation; verify
   the canvas's `aria-describedby` summary lands correctly.
6. **Verification**: re-run automated scans; document the before/after
   in the PR description. Target axe-core finding count = 0 on every
   live route (excluding any documented exceptions in `SECURITY.md`-
   style "documented exceptions" pattern, though we shouldn't need
   that escape hatch for AA).

## Acceptance

- axe-core scan returns zero violations on every live route
- Lighthouse accessibility score ≥ 95 on every live route
- Manual screen-reader smoke: every primary user flow (search, find
  + read, chat, atlas browse, finds reading) is fully navigable by
  keyboard + screen reader
- `prefers-reduced-motion` honored across all animations
- Atlas accessible alternative ships as a parallel surface with
  feature parity for "what's in the archive" browsing
- `/methodology` gains a short "Accessibility" section noting WCAG AA
  conformance and the atlas alternative pattern

## Editorial discipline

- **No "accessibility theatre".** Don't add ARIA labels that misdescribe
  the underlying element. Don't add `role="button"` to a `<div>` —
  use a `<button>`. Standards first; ARIA only when standards aren't
  enough.
- **Test with real assistive tech, not just automated scans.** Axe
  catches most violations but misses semantic errors that a screen
  reader user would feel immediately ("this image's alt text is
  technically present but says 'image-3.jpg'").
- **Respect existing aesthetic.** The terminal/scanlines visual
  identity is part of the project's character. Accessibility fixes
  should preserve it; if a particular signal-color truly can't hit
  contrast, choose a different signal-color from the existing palette
  rather than introducing a new visual register.

## Out of Scope

- Full WCAG AAA conformance (acceptable to leave a few AA-only items;
  AAA is the aspirational ceiling, not the target)
- Multilingual support (separate concern — corpus is English; UI
  translation has limited ROI without corpus translation)
- Cognitive-disability accommodations beyond the WCAG AA baseline
  (reading-level analysis, etc.) — separate plan if pursued
- Accessibility of the upstream war.gov source PDFs (out of our
  control; we mitigate via OCR'd Reader mode)

## Multilingual (note, not scope)

Briefly considered and deferred. The corpus is 100% English; UI
translation without corpus translation is "menu in Spanish, content
in English" — limited value, real maintenance burden.

If pursued later, the right architecture mirrors the Cleaned reader-
mode pattern:

- Per-card AI-translated OCR overlay (opt-in, provenance-labeled,
  reversible)
- Multilingual search query (voyage-multilingual embeddings; user
  types in Spanish, retrieves English results)
- Translated `/finds` editorial entries with explicit "translated by
  AI, reviewed by [native speaker]" provenance, or skip until a
  native-speaker editorial pipeline exists

Tracked as a future consideration; not part of this plan's scope.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Color-contrast fixes degrade the visual identity | Medium | Choose from existing palette before introducing new tokens; document any palette change in the methodology aesthetic notes |
| Atlas accessible alternative becomes a maintenance burden parallel to the canvas | Low | The alternative reads from the same `atlas-layout.json` + manifest — no new data path; only a different presentation |
| Manual screen-reader testing relies on operator availability | Low | Document the test matrix and primary user flows; can be redone by anyone with NVDA/VoiceOver |
| Reduced-motion handling breaks visual identity for users who DO want motion | Low | The default keeps motion; only users with the media query set get the reduced experience |

## Open Questions for Operator

1. Audit tool preference: `@axe-core/cli` (free, command-line) or
   commercial offering (Deque axe DevTools Pro, Tenon, etc.)? CLI is
   sufficient for v1.
2. Screen reader for manual testing: NVDA (Windows, free) or
   VoiceOver (macOS, built-in)? Whichever the operator has on hand.
3. Atlas alternative: tab adjacent to the canvas (operator sees both,
   switches via tabbed interface) vs `<details>` collapsible below
   the canvas (less prominent, less likely to clutter the UX)?
   Recommend tabs for parity.
4. Phasing: full audit + remediation as one focused thread, or split
   into "audit + critical fixes" then "atlas alternative" as a
   follow-on? Recommend single thread; the atlas alternative is the
   long tail but isn't blocking.
