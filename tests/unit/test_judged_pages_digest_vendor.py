"""The vendored ``judged_pages_digest`` contract module (R7C.15).

CI cannot read the NAS OCR sidecars, so pursue-curate's per-page sha and
per-card digest definitions travel into this repo as a byte-for-byte
vendored copy (``src/pursue_index/vendor/judged_pages_digest.py``) rather
than a reimplementation — the two repos must never compute diverging
digests for the same input. These tests pin that the vendored file and
its shared test-vector fixture are byte-identical to pursue-curate's own
copies, reproduce every vector, and remain the single place in this repo
that computes the digest.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from pursue_index.vendor.judged_pages_digest import judged_pages_digest, page_sha256

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MODULE_PATH = REPO_ROOT / "src" / "pursue_index" / "vendor" / "judged_pages_digest.py"
_VECTORS_PATH = REPO_ROOT / "tests" / "fixtures" / "judged_pages_digest_vectors.json"

# Pinned from pursue-curate's own copies (src/curate/judged_pages_digest.py
# and tests/fixtures/judged_pages_digest_vectors.json) at the commit this
# repo vendored them from. A mismatch means one side drifted from the other.
_UPSTREAM_MODULE_SHA256 = (
    "d6d8e55a1ad73e59a9bc6fcda8c16a0c50cdb89854ac8a6c609eaa6145584c28"
)
_UPSTREAM_VECTORS_SHA256 = (
    "a8a864d3aa02e768940810631a27da248e44984ee0b06224ba17fb749d0dbed9"
)


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_vectors() -> list[dict]:
    return json.loads(_VECTORS_PATH.read_text(encoding="utf-8"))["cases"]


def test_vendored_module_is_byte_identical_to_pursue_curates() -> None:
    assert _sha256_of(_MODULE_PATH) == _UPSTREAM_MODULE_SHA256


def test_vendored_vectors_fixture_is_byte_identical_to_pursue_curates() -> None:
    assert _sha256_of(_VECTORS_PATH) == _UPSTREAM_VECTORS_SHA256


def test_vendored_module_imports_only_the_standard_library() -> None:
    """Dependency-free on purpose — a vendored copy has no access to this
    repo's other modules (or pursue-curate's), so an import here would
    break at the vendoring seam."""
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    allowed_stdlib = {"__future__", "hashlib", "collections.abc"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module] if node.module else []
        else:
            continue
        for name in names:
            assert name in allowed_stdlib, (
                f"vendored judged_pages_digest.py imports {name!r}, which "
                "is not standard library -- the vendored copy must stay "
                "byte-identical to pursue-curate's dependency-free original."
            )


@pytest.mark.parametrize("case", _load_vectors(), ids=lambda c: c["name"])
def test_vector_cases_reproduce_the_committed_shas_and_digest(case: dict) -> None:
    if "pages_cleaned_jsonl" in case:
        pytest.skip("canonical JSONL fixture is covered by its own test below")
    pairs = [(p["page"], page_sha256(p["text_cleaned"])) for p in case["pages"]]
    for page, sha in pairs:
        assert sha == case["page_shas"][str(page)]
    assert judged_pages_digest(pairs) == case["digest"]


def test_canonical_vector_is_a_literal_pages_cleaned_jsonl_fixture() -> None:
    """The ``canonical`` vector is a real ``pages_cleaned.jsonl`` excerpt
    (pages 2 and 10, one CRLF, one non-ASCII ``text_cleaned``) -- the same
    fixture ``build_pages_cleaned.py`` and ``build_qc_coverage.py`` are
    tested against for cross-script agreement."""
    canonical = next(c for c in _load_vectors() if c["name"] == "canonical")
    rows = [
        json.loads(line)
        for line in canonical["pages_cleaned_jsonl"].splitlines()
        if line
    ]
    assert {row["page"] for row in rows} == {2, 10}
    pairs = [(row["page"], page_sha256(row["text_cleaned"])) for row in rows]
    for page, sha in pairs:
        assert sha == canonical["page_shas"][str(page)]
    assert judged_pages_digest(pairs) == canonical["digest"]


def _defines(path: Path, name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.FunctionDef) and node.name == name
        for node in ast.walk(tree)
    )


def test_no_other_module_under_src_or_scripts_computes_the_digest_itself() -> None:
    """Static check: the vendored copy is the ONLY digest/page-sha code in
    this repo. A second definition of ``page_sha256`` or
    ``judged_pages_digest`` elsewhere could silently diverge from the
    contract both repos must share."""
    offenders: list[str] = []
    for root in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
        for path in root.rglob("*.py"):
            if path == _MODULE_PATH:
                continue
            if _defines(path, "page_sha256") or _defines(path, "judged_pages_digest"):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
