"""Guard: no operator-specific absolute data path may be baked into source.

Where archived assets live is configured by ``PURSUE_DATA_ROOT`` and exposed
through ``settings`` (``data_root``/``ocr_dir``/``pdf_dir``/``r2_mirror_dir``).
Hardcoding one operator's mount point does two kinds of damage:

1. It publishes internal infrastructure topology from a public repository.
2. It breaks the script for anyone whose data root is somewhere else — the
   path silently resolves to a directory that does not exist.

Both failure modes are invisible until someone else runs the code, so they are
enforced here rather than left to review.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCANNED_DIRS = ("src", "scripts", "tests")

# Absolute paths that belong to one machine/user rather than to the project.
_OPERATOR_PATH = re.compile(r"(?:/mnt/|/media/|/Users/|/home/(?!runner\b)[a-z_][a-z0-9_-]*/)")


def _python_files() -> list[Path]:
    """Every Python source file in scope, except this guard itself.

    Self-exclusion is required: the detection pattern below is a string literal
    containing the very prefixes it looks for, so the guard would flag itself.
    """
    this_file = Path(__file__).resolve()
    files: list[Path] = []
    for rel in _SCANNED_DIRS:
        root = _REPO_ROOT / rel
        if root.is_dir():
            files.extend(
                p
                for p in root.rglob("*.py")
                if "__pycache__" not in p.parts and p.resolve() != this_file
            )
    return sorted(files)


def _string_literals(path: Path) -> list[tuple[int, str]]:
    """Every string constant in the file, with its line number.

    Parsed rather than grepped so a match is a real literal — a path named in
    prose, in a comment, or in a ``--help`` epilog is not what this guards.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
    return out


def test_no_operator_specific_absolute_paths_in_source() -> None:
    offenders: list[str] = []
    for path in _python_files():
        for lineno, value in _string_literals(path):
            if _OPERATOR_PATH.search(value):
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {value!r}")

    assert not offenders, (
        "Operator-specific absolute paths are baked into source. Resolve them "
        "from `settings` (driven by PURSUE_DATA_ROOT) instead:\n  "
        + "\n  ".join(offenders)
    )


# Non-Python source that ships in the repo. Scanned as text — these have no
# single parser in common, and a path in a comment is just as published as one
# in code (the first version of this guard was Python-only and missed a NAS
# path sitting in an Astro frontmatter comment).
_WEB_SOURCE_DIRS = ("web/src", "web/src/content", "worker", "scripts", ".github")
_WEB_SOURCE_SUFFIXES = (
    ".astro",
    ".mdx",  # renderable content collections — published like .astro
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".sh",
    ".yml",
    ".yaml",
    ".jsonc",
)


def _web_source_files() -> list[Path]:
    files: list[Path] = []
    for rel in _WEB_SOURCE_DIRS:
        root = _REPO_ROOT / rel
        if not root.is_dir():
            continue
        files.extend(
            p
            for p in root.rglob("*")
            if p.suffix in _WEB_SOURCE_SUFFIXES and "node_modules" not in p.parts
        )
    return sorted(files)


def test_no_operator_specific_absolute_paths_in_web_source() -> None:
    offenders: list[str] = []
    for path in _web_source_files():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if _OPERATOR_PATH.search(line):
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

    assert not offenders, (
        "Operator-specific absolute paths appear in non-Python source. Refer to "
        "`<PURSUE_DATA_ROOT>` instead of one machine's mount point:\n  "
        + "\n  ".join(offenders)
    )


# Each script's default asset location, and the settings property it must track.
_SCRIPT_DEFAULTS = (
    ("merge_partial_sonnet_with_surya", "NAS_OCR_ROOT", "ocr_dir"),
    ("restore_local_pdfs_from_mirror", "NAS_ROOT", "data_root"),
    ("ingest_release_videos", "DEFAULT_NAS", "r2_mirror_dir"),
    ("build_review_priority", "DEFAULT_OCR_DIR", "ocr_dir"),
    ("build_pdf_thumbs", "DEFAULT_PDF_ROOT", "pdf_dir"),
    ("spotcheck_view", "ROOT", "ocr_dir"),
    ("build_photo_card_index", "DEFAULT_OCR_ROOT", "ocr_dir"),
)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_pursue_script_{name}", _REPO_ROOT / "scripts" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def relocated_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point PURSUE_DATA_ROOT somewhere new and rebuild the settings singleton.

    Asserting against the *current* data root would pass even for a hardcoded
    path, because the operator's configured root is the very path that used to
    be baked in. Moving the root is what actually proves the coupling.
    """
    # `pursue_index.config` re-exports the Settings *instance* under the name
    # `settings`, which shadows the submodule of the same name — so resolve the
    # module by dotted name rather than by attribute access.
    settings_mod = importlib.import_module("pursue_index.config.settings")
    config_pkg = importlib.import_module("pursue_index.config")

    monkeypatch.setenv("PURSUE_DATA_ROOT", str(tmp_path))
    importlib.reload(settings_mod)
    importlib.reload(config_pkg)
    yield tmp_path
    # Restore the process-wide singleton for any test that runs after this one.
    monkeypatch.undo()
    importlib.reload(settings_mod)
    importlib.reload(config_pkg)


@pytest.mark.parametrize(("script", "attr", "settings_attr"), _SCRIPT_DEFAULTS)
def test_script_default_tracks_data_root(
    script: str, attr: str, settings_attr: str, relocated_data_root: Path
) -> None:
    """The default must follow PURSUE_DATA_ROOT, not a fixed mount point."""
    module = _load_script(script)
    actual = Path(getattr(module, attr))

    assert actual == relocated_data_root or relocated_data_root in actual.parents, (
        f"scripts/{script}.py::{attr} is {actual}, which does not follow "
        f"PURSUE_DATA_ROOT ({relocated_data_root}) — it looks hardcoded"
    )
