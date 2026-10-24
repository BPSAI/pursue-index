"""The single resolver every ``_REPO_ROOT``-style constant must route through.

An editable install's ``sys.path`` entry stays pinned to whichever checkout
ran ``pip install -e .``. ``repo_root()`` answers where *data* lives: it
prefers the checkout the process is standing in, so a CLI run from a second
worktree reads and writes that worktree's ``data/``.

The resolved root is data-only. Anything the process executes (worker
scripts, builder scripts) is located with ``installed_scripts_dir()``,
which is anchored to the installed package and never follows the working
directory or ``PURSUE_REPO_ROOT``.

Precedence for ``repo_root()``:

1. ``PURSUE_REPO_ROOT`` if set -- an explicit operator override.
2. The git top level of the current directory, if it is a pursue-index
   checkout AND is the installed checkout or one of its registered
   worktrees (same ``git rev-parse --git-common-dir``). Any other
   pursue-index-looking directory is refused with ``UntrustedRootError``.
3. The checkout the imported ``pursue_index`` package belongs to, else the
   installed package's own directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from pursue_index.config.project_root import source_checkout_root
from pursue_index.safe_git import GitUnavailableError, run_git

__all__ = [
    "UntrustedRootError",
    "installed_checkout_root",
    "installed_scripts_dir",
    "repo_root",
]


class UntrustedRootError(RuntimeError):
    """The working directory is a checkout this install does not own.

    The CLI entry point reports it as one line (see ``cli.commands``).
    """


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


def _package_dir() -> Path:
    import pursue_index

    return Path(pursue_index.__file__).resolve().parent


def installed_checkout_root() -> Path | None:
    """The source checkout the imported package lives in, or ``None``."""
    return source_checkout_root(_package_dir())


def installed_scripts_dir() -> Path | None:
    """``scripts/`` of the installed checkout: the only place executables load from."""
    root = installed_checkout_root()
    if root is None:
        return None
    scripts = root / "scripts"
    return scripts if scripts.is_dir() else None


def _git_common_dir(root: Path) -> Path | None:
    try:
        result = run_git(root, "rev-parse", "--git-common-dir")
    except GitUnavailableError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    common = Path(result.stdout.strip())
    return (common if common.is_absolute() else root / common).resolve()


def _is_registered_worktree_of(candidate: Path, common: Path) -> bool:
    """True iff ``candidate`` is a worktree git registered under ``common``.

    A ``.git`` file only claims a gitdir; the registered worktree's own
    ``gitdir`` file must point back at this exact ``.git``, and git must
    agree the candidate is its own top level.
    """
    link = candidate / ".git"
    if not link.is_file():
        return False
    text = link.read_text(encoding="utf-8", errors="replace").strip()
    if not text.startswith("gitdir:"):
        return False
    gitdir = Path(text.removeprefix("gitdir:").strip())
    gitdir = (gitdir if gitdir.is_absolute() else candidate / gitdir).resolve()
    if gitdir.parent != (common / "worktrees").resolve():
        return False
    back = gitdir / "gitdir"
    if not back.is_file():
        return False
    if Path(back.read_text(encoding="utf-8", errors="replace").strip()).resolve() != link.resolve():
        return False
    top = run_git(candidate, "rev-parse", "--show-toplevel")
    return top.returncode == 0 and Path(top.stdout.strip()).resolve() == candidate.resolve()


def _owned_by_install(cwd_root: Path) -> bool:
    installed = installed_checkout_root()
    if installed is None:
        return False
    if cwd_root.resolve() == installed.resolve():
        return True
    theirs, ours = _git_common_dir(cwd_root), _git_common_dir(installed)
    if theirs is None or theirs != ours:
        return False
    try:
        return _is_registered_worktree_of(cwd_root, ours)
    except (GitUnavailableError, OSError):
        return False


def repo_root() -> Path:
    """The checkout this process should read and write ``data/`` against."""
    env_override = os.environ.get("PURSUE_REPO_ROOT")
    if env_override:
        return Path(env_override).resolve()

    cwd_root = _git_top_level(Path.cwd())
    if cwd_root is not None and _looks_like_pursue_index_checkout(cwd_root):
        if not _owned_by_install(cwd_root):
            raise UntrustedRootError(
                f"refusing to use {cwd_root} as the repo root: it is not the "
                "installed checkout or one of its git worktrees. Run from the "
                "installed checkout (or a worktree of it), or set "
                "PURSUE_REPO_ROOT explicitly."
            )
        return cwd_root

    package_dir = _package_dir()
    checkout_root = source_checkout_root(package_dir)
    return checkout_root if checkout_root is not None else package_dir
