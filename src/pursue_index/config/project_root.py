"""Anchor relative configuration paths to the checkout they belong to.

``data_root`` and its siblings default to relative paths, and the answer
has to be the same wherever the CLI is invoked from. The anchor is found
by walking up from the imported ``pursue_index`` package looking for the
project sentinel (``pyproject.toml``) beside a ``src/pursue_index`` that
IS this package — an identity check, not a name match, so an unrelated
project file further up the tree is never mistaken for our checkout.

Two layouts, two defined answers:

* **Source checkout** — the package lives at ``<root>/src/pursue_index``,
  so the walk finds ``<root>`` and a relative path resolves inside the
  checkout, exactly as it always has.
* **Installed package** — the package lives under ``site-packages``, which
  is not a checkout of this project, so there is nothing to anchor to.
  A relative path then resolves against the working directory: a location
  the operator chose, rather than one beside the installed package files.

Production points ``PURSUE_DATA_ROOT`` at an absolute location, which
bypasses this walk entirely; the walk decides only what the relative
default means.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["PACKAGE_DIR_NAME", "PROJECT_SENTINEL", "SOURCE_LAYOUT_PARENT",
           "resolve_relative_data_root", "source_checkout_root"]

# The file that marks a directory as the root of this project's checkout.
PROJECT_SENTINEL = "pyproject.toml"
# Where a source checkout keeps the importable package.
SOURCE_LAYOUT_PARENT = "src"
PACKAGE_DIR_NAME = "pursue_index"


def source_checkout_root(package_dir: Path) -> Path | None:
    """The source checkout ``package_dir`` was imported from, if any.

    Returns the ancestor that carries the project sentinel AND whose
    ``src/pursue_index`` is ``package_dir`` itself. Returns ``None`` for an
    installed package, including one whose virtualenv happens to sit inside
    some other project directory.
    """
    target = package_dir.resolve()
    for candidate in package_dir.parents:
        if not (candidate / PROJECT_SENTINEL).is_file():
            continue
        expected = candidate / SOURCE_LAYOUT_PARENT / PACKAGE_DIR_NAME
        if expected.resolve() == target:
            return candidate
    return None


def resolve_relative_data_root(
    relative: Path, *, package_dir: Path, cwd: Path
) -> Path:
    """Resolve a relative data root against the checkout, else ``cwd``."""
    root = source_checkout_root(package_dir)
    if root is not None:
        return root / relative
    return cwd / relative
