"""The single resolver every ``_REPO_ROOT``-style constant must route through.

An editable install's ``sys.path`` entry stays pinned to whichever checkout
ran ``pip install -e .``. A module that derives its repo root by counting
``.parent`` hops off its own ``__file__`` therefore answers with the
INSTALLING checkout's location, not the one the process actually runs in —
so a CLI invoked from a second worktree silently reads and writes the
original checkout's ``data/``. ``repo_root()`` instead prefers the checkout
the process is standing in (found via the current directory's git top
level), and only falls back to the imported package's own location when
the current directory is not a pursue-index checkout at all.

Precedence:

1. ``PURSUE_REPO_ROOT`` if set — an explicit operator override, wins outright.
2. The git top level of the current directory, if that top level is itself
   a pursue-index checkout (carries ``pyproject.toml`` and
   ``src/pursue_index/__init__.py``).
3. The checkout the imported ``pursue_index`` package belongs to (for an
   editable install), else the installed package's own directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from pursue_index.config.project_root import source_checkout_root

__all__ = ["repo_root"]


def _looks_like_pursue_index_checkout(candidate: Path) -> bool:
    return (candidate / "pyproject.toml").is_file() and (
        candidate / "src" / "pursue_index" / "__init__.py"
    ).is_file()


def _git_top_level(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def repo_root() -> Path:
    """The checkout this process should read and write ``data/`` against."""
    env_override = os.environ.get("PURSUE_REPO_ROOT")
    if env_override:
        return Path(env_override).resolve()

    cwd_root = _git_top_level(Path.cwd())
    if cwd_root is not None and _looks_like_pursue_index_checkout(cwd_root):
        return cwd_root

    import pursue_index

    package_dir = Path(pursue_index.__file__).resolve().parent
    checkout_root = source_checkout_root(package_dir)
    return checkout_root if checkout_root is not None else package_dir
