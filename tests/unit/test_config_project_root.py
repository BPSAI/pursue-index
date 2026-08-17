"""Anchoring a relative ``data_root`` to the checkout it belongs to.

``data_root`` defaults to a relative path, and the answer must be the same
no matter which directory the CLI is invoked from. The anchor is the
source checkout the ``pursue_index`` package was imported from, identified
by the project sentinel next to it rather than by counting parent
directories — so the same code gives the right answer for a source
checkout and a defined one for an installed package.
"""

from __future__ import annotations

from pathlib import Path

from pursue_index.config.project_root import (
    resolve_relative_data_root,
    source_checkout_root,
)


def _make_source_checkout(root: Path) -> Path:
    """Build a source-checkout layout; return its ``pursue_index`` dir."""
    (root / "pyproject.toml").write_text("[project]\nname = 'pursue-index'\n")
    package_dir = root / "src" / "pursue_index"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")
    return package_dir


def _make_installed_layout(venv_root: Path) -> Path:
    """Build a site-packages layout; return its ``pursue_index`` dir."""
    package_dir = venv_root / "lib" / "python3.12" / "site-packages" / "pursue_index"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")
    return package_dir


# --- source checkout: the established answer, unchanged ------------------


def test_source_checkout_root_is_the_directory_holding_the_project_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    package_dir = _make_source_checkout(root)

    assert source_checkout_root(package_dir) == root


def test_relative_data_root_anchors_to_the_source_checkout(tmp_path: Path) -> None:
    """From a source checkout, ``./data`` means the checkout's data
    directory whatever the working directory happens to be."""
    root = tmp_path / "checkout"
    root.mkdir()
    package_dir = _make_source_checkout(root)
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()

    resolved = resolve_relative_data_root(
        Path("data"), package_dir=package_dir, cwd=elsewhere
    )

    assert resolved == root / "data"


# --- installed package: a defined answer outside any checkout ------------


def test_installed_package_has_no_source_checkout_root(tmp_path: Path) -> None:
    """An installed package sits under site-packages, which is not a
    checkout of this project, so there is no checkout to anchor to."""
    package_dir = _make_installed_layout(tmp_path / "venv")

    assert source_checkout_root(package_dir) is None


def test_installed_package_inside_a_checkout_still_has_no_checkout_root(
    tmp_path: Path,
) -> None:
    """A virtualenv living inside some project directory does not make that
    directory this package's checkout: the anchor is the checkout whose
    ``src/pursue_index`` IS the imported package, not merely an ancestor
    that happens to carry a project file."""
    outer = tmp_path / "some-project"
    outer.mkdir()
    (outer / "pyproject.toml").write_text("[project]\nname = 'unrelated'\n")
    package_dir = _make_installed_layout(outer / ".venv")

    assert source_checkout_root(package_dir) is None


def test_installed_relative_data_root_anchors_to_the_working_directory(
    tmp_path: Path,
) -> None:
    """With no checkout to anchor to, a relative ``data_root`` is taken
    against the working directory — a location the operator chose — and
    never lands beside the installed package files."""
    package_dir = _make_installed_layout(tmp_path / "venv")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    resolved = resolve_relative_data_root(
        Path("data"), package_dir=package_dir, cwd=workdir
    )

    assert resolved == workdir / "data"
    assert package_dir not in resolved.parents


# --- the real package, as imported ---------------------------------------


def test_the_imported_package_resolves_without_walking_a_fixed_depth() -> None:
    """The anchor for the package under test is found by the sentinel walk,
    so the resolution holds regardless of how deep the package sits."""
    import pursue_index

    package_dir = Path(pursue_index.__file__).parent
    root = source_checkout_root(package_dir)

    assert root is not None
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "pursue_index").resolve() == package_dir.resolve()
