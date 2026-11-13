"""``pursue_index.page_text`` stays stdlib-only, and the search payload's
page emitter loads it without the ``pursue_index`` package.

``scripts/_search_pages.py`` used to import the markup strip from
``pursue_index.clean.qc.page_provenance``, which runs the package
``__init__`` (third-party deps) and pulls in ``clean.qc`` and ``embed``. It
now loads the leaf by file path, so it imports with the package blocked.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEAF = REPO_ROOT / "src" / "pursue_index" / "page_text.py"
SEARCH_PAGES = REPO_ROOT / "scripts" / "_search_pages.py"


def _imported_roots(path: Path) -> set[str]:
    """Top-level packages imported at module level (what runs on import)."""
    roots: set[str] = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_leaf_imports_only_the_standard_library() -> None:
    extra = _imported_roots(LEAF) - set(sys.stdlib_module_names) - {"__future__"}
    assert not extra, f"page_text.py must stay stdlib-only, imports {sorted(extra)}"


def test_search_pages_has_no_module_level_package_import() -> None:
    # emit_observation_only_pages keeps its pre-existing lazy import of
    # embed.image_observations: it runs only inside build_search_data, which
    # needs the installed package anyway.
    assert "pursue_index" not in _imported_roots(SEARCH_PAGES)


def test_search_pages_imports_with_the_package_blocked() -> None:
    # sys.modules[name] = None makes any import of it raise ImportError.
    code = (
        "import sys\n"
        "sys.modules['pursue_index'] = None\n"
        f"sys.path.insert(0, {str(SEARCH_PAGES.parent)!r})\n"
        "import _search_pages\n"
        "assert _search_pages._clean_text('<b>a</b><i>b</i>') == 'ab'\n"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                         timeout=30)
    assert out.returncode == 0, out.stderr


def test_one_definition_is_shared() -> None:
    from pursue_index import page_text
    from pursue_index.clean.qc import page_provenance
    from pursue_index.embed import image_observations

    assert page_provenance.published_ocr_text is page_text.published_ocr_text
    assert image_observations.OBSERVATIONS_HEADER is page_text.OBSERVATIONS_HEADER
