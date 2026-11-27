"""Operator-facing Markdown summaries for the image r2-mirror stage and preflight."""

from __future__ import annotations

from pursue_index.release.image_mirror import (
    _FAILURES,
    ImageMirrorPreflight,
    ImageMirrorReport,
)


def _code(text: object) -> str:
    """``text`` as one inline code span: backticks and line breaks cannot escape it."""
    flat = " ".join(str(text).replace("`", "'").split())
    return f"`{flat}`"


def render_image_mirror_report(report: ImageMirrorReport) -> str:
    """Operator-facing summary for ``pursue storage mirror-images``."""
    lines = ["### Image r2-mirror stage", ""]
    lines += [f"* {name}: {n}" for name, n in report.counts.items()]
    for cid, (outcome, detail) in report.results.items():
        if outcome in _FAILURES:
            lines.append(f"    * {_code(cid)} — {outcome}: {_code(detail)}")
    lines += ["", f"**All in-scope images mirrored:** {'yes' if report.ok else 'NO'}"]
    return "\n".join(lines)


def render_image_verify(pf: ImageMirrorPreflight) -> str:
    """Operator-facing summary for ``pursue storage verify-image-mirror``."""
    lines = ["### Image r2-mirror preflight", ""]
    if pf.ok:
        lines.append("**All in-scope image cards have their r2-mirror copy:** yes")
        return "\n".join(lines)
    lines.append(f"**MISSING or wrong mirror for {len(pf.details)} card(s):**")
    lines += [f"* {_code(cid)} — {_code(why)}" for cid, why in pf.details.items()]
    lines += [
        "",
        "> Run `pursue storage mirror-images --worklist <file>` to stage them, then re-verify.",
    ]
    return "\n".join(lines)
