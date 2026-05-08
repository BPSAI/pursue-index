---
id: ui-redesign-alien
type: feature
status: backlog
created: 2026-05-08
priority: medium
---

# UI redesign — declassified-terminal aesthetic

## Why

The current UI is functional but generic dark mode. For pursueindex.com
we want a visual identity that hits the moment a journalist or HN reader
lands on the page: this is *the* place to query the UAP archive. The
interface should look like you're operating a declassified document
terminal, not a SaaS dashboard.

The aesthetic to hit:

- *Arrival* / *X-Files* / *Annihilation* / *Roswell file room*.
- Government terminal monochrome with selective color signal.
- Subtle CRT artifacts; not so heavy it becomes a Halloween costume.
- Mono + sans pairing; dense info but legible.

Not the aesthetic:

- Sci-fi neon "AI brain" Three.js explosions.
- Discord/Slack-style chat bubbles for the chat surface.
- Generic Linear/Vercel dark mode (which is what we ship today).

## Direction

### Palette

```
--bg-deep       #0a0d12   # near-black blue-shifted
--bg            #11151b
--bg-elevated   #181d25
--border        #1f2a35
--border-bright #2f3d4e
--text          #c5cdd6
--text-bright   #ecf2f9
--text-dim      #6b7783

--signal-green  #a4ff5a   # terminal, OK, "verified"
--signal-amber  #ffc857   # caution, "review"
--signal-red    #ff5c5c   # redaction, error
--signal-cyan   #5fd4ff   # link, citation, "asset"
--signal-violet #b78fff   # video, classified
```

### Typography

- **Display + monospace:** "JetBrains Mono" or "Berkeley Mono" for headers,
  card_id, terminal accents.
- **Body:** "Inter Tight" or "IBM Plex Sans" for descriptions.
- **Numerals:** tabular figures everywhere.
- Generous tracking on uppercase labels (already used).

### Motifs

- Header bar: thin scan-line above; small "PURSUE://INDEX" monospace badge
  with a blinking caret.
- Page footer: timestamp + csv_sha256 prefix in monospace.
- Card thumbnails: subtle CRT scan-line overlay (1–2% opacity, animated).
- Redaction: black bars with a subtle shimmer; hover reveals "REDACTED"
  in red signal.
- Loading states: scrolling text "DECLASSIFYING..." or character-by-character
  reveal at terminal speed.

### Surfaces

- Keep the current `/`, `/card/[id]`, `/search`, `/diff` route structure.
- Re-style each. The data layer doesn't change.
- New `/about` and `/methodology` pages added for launch.
- New `/chat` surface (separate plan); aesthetic continuity matters.

## Specific component upgrades

- **Card grid:** dense list view option (terminal-style table) toggleable
  with card view. Default to card view, but the table is the power-user mode.
- **Card detail:** PDF preview embedded inline (pdf.js), with the OCR text
  side-by-side. Clicking a search match scrolls the PDF to that page.
- **Search:** keyboard-first. `/` focuses, `j/k` navigates results,
  `enter` opens, `esc` clears.
- **Filter chips:** click an agency/type chip on a card to filter to it.
- **404 + empty states:** styled like terminal output with `> exit code 1`.

## Sound (optional, off by default)

Subtle CRT power-on hum + click feedback on key actions. Toggle in
header. We're not making the user's office sound like a movie set, but
the *option* fits the brand.

## Acceptance

- Lighthouse perf > 90 on the redesigned home and detail pages.
- AAA contrast on body text; AA on dim text.
- No layout shift on the search index loading.
- The "feel" passes a vibe check: would a journalist screenshot this for
  an article? Would a UAP forum user share this without irony?

## Open questions

- Do we hire a designer for the wordmark / favicon, or generate +
  iterate? Lean toward iterate-and-stop-when-it-feels-right. The
  "PURSUE://INDEX" lockup as monospace text is already strong.
- Any motion at all on first load, or fully static + interactive on hover?
  Lean static; motion is for chat-surface streaming and loading states only.
