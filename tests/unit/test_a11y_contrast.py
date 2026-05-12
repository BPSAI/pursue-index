"""WCAG 2.2 AA color-contrast guard for the web/ design-system tokens.

Failing this test means a foreground/background combination that the design
system advertises as readable body text would actually fail WCAG AA. The
constants here mirror the @theme block in `web/src/styles/global.css`; if
those tokens drift, this test starts failing and the operator has to
either bump the token (preferred) or document an exception.

Why a Python test (rather than a JS/Vitest one): the rest of this repo's
unit test suite is pytest, the existing `arch check` runs over Python
files, and a contrast assertion has zero dependencies — re-using the
existing pytest infra avoids standing up a JS test runner just for one
spec. The token list is small enough that the duplication cost is low.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Token table — must mirror @theme in web/src/styles/global.css.
# Keep alphabetical inside each section for ease of scanning.
# ---------------------------------------------------------------------------

BACKGROUNDS = {
    "bg-deep": "#0a0d12",
    "bg": "#11151b",
    "bg-elevated": "#181d25",
    "bg-raised": "#1d242e",
}

# Foregrounds advertised as body-text-capable (i.e. not strictly large-text
# or graphical). signal-* are also used as 14-pt+ accents but ARE used at
# body-text size in places (see usages of text-[color:var(--color-signal-*)]
# inline in paragraph copy), so we hold them to 4.5:1 too.
TEXT_FOREGROUNDS = {
    "text": "#c5cdd6",
    "text-bright": "#ecf2f9",
    "text-dim": "#9ba6b3",
    "text-faint": "#8390a0",
    "signal-green": "#a4ff5a",
    "signal-amber": "#ffc857",
    "signal-red": "#ff5c5c",
    "signal-cyan": "#5fd4ff",
    "signal-violet": "#b78fff",
}

WCAG_AA_NORMAL = 4.5  # body text
WCAG_AA_LARGE = 3.0  # 18pt+, or 14pt+ bold


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: int) -> float:
        c_norm = c / 255.0
        return c_norm / 12.92 if c_norm <= 0.03928 else ((c_norm + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def _contrast(c1: str, c2: str) -> float:
    L1 = _relative_luminance(_hex_to_rgb(c1))
    L2 = _relative_luminance(_hex_to_rgb(c2))
    if L1 < L2:
        L1, L2 = L2, L1
    return (L1 + 0.05) / (L2 + 0.05)


@pytest.mark.parametrize("fg_name,fg_hex", sorted(TEXT_FOREGROUNDS.items()))
@pytest.mark.parametrize("bg_name,bg_hex", sorted(BACKGROUNDS.items()))
def test_text_foreground_meets_aa_on_every_background(
    fg_name: str, fg_hex: str, bg_name: str, bg_hex: str
) -> None:
    """Every body-text token must hit 4.5:1 against every surface token."""
    ratio = _contrast(fg_hex, bg_hex)
    assert ratio >= WCAG_AA_NORMAL, (
        f"WCAG AA fail: {fg_name} ({fg_hex}) on {bg_name} ({bg_hex}) "
        f"is {ratio:.2f}:1, needs {WCAG_AA_NORMAL}:1"
    )


def test_text_dim_remains_dimmer_than_text() -> None:
    """Visual hierarchy: text-dim must be perceptually dimmer than text.

    If a contrast bump inverts the order so text-dim is *brighter* than text,
    every UI that uses both for hierarchy starts reading wrong.
    """
    bg = BACKGROUNDS["bg-deep"]
    text = _contrast(TEXT_FOREGROUNDS["text"], bg)
    text_dim = _contrast(TEXT_FOREGROUNDS["text-dim"], bg)
    text_faint = _contrast(TEXT_FOREGROUNDS["text-faint"], bg)
    assert text > text_dim > text_faint, (
        f"Hierarchy inverted on {bg}: text={text:.2f} dim={text_dim:.2f} "
        f"faint={text_faint:.2f} (expect text > dim > faint)"
    )


# ---------------------------------------------------------------------------
# Drift guard: the table above must mirror @theme in global.css. If somebody
# edits the CSS without updating this test, the test still passes against
# stale values — defeating the point. This last check parses the CSS and
# asserts the values agree.
# ---------------------------------------------------------------------------

GLOBAL_CSS = (
    Path(__file__).resolve().parent.parent.parent
    / "web"
    / "src"
    / "styles"
    / "global.css"
)
TOKEN_RE = re.compile(r"--color-([a-z\-]+):\s*(#[0-9a-fA-F]{6})\s*;")


def test_token_table_matches_global_css() -> None:
    """Catches the case where global.css changes but this file does not."""
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for m in TOKEN_RE.finditer(css):
        found[m.group(1)] = m.group(2).lower()

    expected = {**BACKGROUNDS, **TEXT_FOREGROUNDS}
    drift = {
        name: (expected[name].lower(), found.get(name))
        for name in expected
        if found.get(name) != expected[name].lower()
    }
    assert not drift, (
        f"Token drift between this test's table and global.css: {drift}"
    )


# ---------------------------------------------------------------------------
# Drift guard, extended: catches token consumers OUTSIDE global.css that
# could go stale silently. The original guard only walked global.css; the
# vaivora cross-cutting review (2026-05-12) flagged that web/public/og.svg
# and web/src/components/atlas-helpers.ts hard-code the same hex literals
# and were missed during the WCAG bump. Extends the guard to those files.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXTERNAL_TOKEN_CONSUMERS = [
    _REPO_ROOT / "web" / "public" / "og.svg",
    _REPO_ROOT / "web" / "src" / "components" / "atlas-helpers.ts",
]
# The OLD literals that should no longer appear as fill/color usage in any
# consumer. Matched against lowercased file text for case-insensitivity.
RETIRED_LITERALS = {"#4a5563", "#6b7783"}


def test_external_token_consumers_have_no_retired_literals() -> None:
    """No file outside global.css should still carry the pre-WCAG-AA hex.

    Note: false-positives possible if a consumer mentions the old hex in
    a comment or docstring describing the migration. The atlas-helpers.ts
    `text-dim was #6b7783 prior` comment is one such case — matched on
    'old hex' textual context, allowed via _COMMENT_EXEMPT below.
    """
    _COMMENT_EXEMPT = {"#6b7783"}  # historical comment in atlas-helpers.ts
    offenders: dict[str, list[str]] = {}
    for path in EXTERNAL_TOKEN_CONSUMERS:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").lower()
        # Per-file: filter out exempt-via-comment hits by checking whether
        # the literal appears in a comment-only line. For the atlas-helpers
        # case the literal is on a `*` JSDoc line; for og.svg there is no
        # comment context for these hexes.
        hits: list[str] = []
        for lit in RETIRED_LITERALS:
            if lit not in text:
                continue
            # Walk per-line: if every occurrence is in a comment line for
            # an exempt literal, skip. Otherwise flag.
            non_comment_use = False
            for line in text.splitlines():
                if lit not in line:
                    continue
                stripped = line.strip()
                is_comment_line = (
                    stripped.startswith("*") or
                    stripped.startswith("//") or
                    stripped.startswith("#") or
                    stripped.startswith("<!--")
                )
                if not (is_comment_line and lit in _COMMENT_EXEMPT):
                    non_comment_use = True
                    break
            if non_comment_use:
                hits.append(lit)
        if hits:
            offenders[str(path.relative_to(_REPO_ROOT))] = hits
    assert not offenders, (
        f"Retired hex literals still present in non-CSS consumers: {offenders}. "
        f"The WCAG AA bump (2026-05-12) replaced #4a5563 → #8390a0 and "
        f"#6b7783 → #9ba6b3 in global.css; mirror the change here."
    )
