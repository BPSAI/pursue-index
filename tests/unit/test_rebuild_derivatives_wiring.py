"""The `make rebuild-derivatives` target must invoke every derived-payload
builder, with the import-fragile atlas builder LAST.

This is the regression guard for the orphaned-builder class of bug: a
generator that works but that nothing invokes, so the deployed payload
silently tracks an old manifest. `build_novelty_data.py` in particular
was orphaned while embed/posters/atlas were already wired — novelty.json
went stale (0 of the Release-5 cards) and `/disclosure` couldn't see the
newest release. A grep-the-Makefile test is deliberately coarse: it can't
run the operator-only builders (they need the NAS embed root + r2-mirror),
but it CAN assert none of them silently drops out of the recipe again.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MAKEFILE = _REPO_ROOT / "Makefile"

# The four derived-payload builders the task requires wired into the build.
_DERIVED_BUILDERS = (
    "build_embed_data.py",
    "build_novelty_data.py",
    "build_video_posters.py",
    "build_atlas_layout.py",
)


def _rebuild_derivatives_recipe() -> list[str]:
    """The recipe lines (tab-indented) of the rebuild-derivatives target."""
    lines = _MAKEFILE.read_text().splitlines()
    recipe: list[str] = []
    in_target = False
    for line in lines:
        if line.startswith("rebuild-derivatives:"):
            in_target = True
            continue
        if in_target:
            # Recipe lines are tab-indented; the first non-tab line ends it.
            if line.startswith("\t"):
                recipe.append(line)
            elif line.strip() == "":
                # blank lines inside a recipe are allowed to separate groups
                continue
            else:
                break
    return recipe


def _builder_invocations(recipe: list[str]) -> list[str]:
    """Ordered list of ``build_*.py`` filenames the recipe actually runs.

    Only counts lines that execute the builder (a `$(PYTHON) scripts/…`
    command), not comment lines that merely mention it.
    """
    ordered: list[str] = []
    for line in recipe:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "$(PYTHON)" not in stripped and "python" not in stripped.lower():
            continue
        for builder in _DERIVED_BUILDERS:
            if builder in stripped:
                ordered.append(builder)
    return ordered


def test_all_four_derived_builders_are_invoked() -> None:
    """Every derived-payload builder must be wired — an orphaned builder
    is exactly how novelty.json went stale."""
    invoked = _builder_invocations(_rebuild_derivatives_recipe())
    for builder in _DERIVED_BUILDERS:
        assert builder in invoked, (
            f"{builder} is not invoked by `make rebuild-derivatives`; "
            f"invoked builders: {invoked}"
        )


def test_atlas_builder_runs_last() -> None:
    """The import-fragile atlas builder (optional projection stack) must run
    LAST so a missing optional dep can't block the builders behind it."""
    invoked = _builder_invocations(_rebuild_derivatives_recipe())
    assert invoked, "no builders invoked at all"
    assert invoked[-1] == "build_atlas_layout.py", (
        f"atlas must be the last builder invoked; order was {invoked}"
    )


def test_derived_builders_are_not_pipe_masked() -> None:
    """A builder whose exit code is masked by `| tail`/`| head` can fail
    silently and leave a stale payload. The four derived-payload builders
    must run un-piped so a non-zero exit fails the target loudly."""
    recipe = _rebuild_derivatives_recipe()
    for line in recipe:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if not any(b in stripped for b in _DERIVED_BUILDERS):
            continue
        assert "|" not in stripped, (
            f"derived-payload builder line pipe-masks its exit code: {stripped!r}"
        )
