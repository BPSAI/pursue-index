"""Page selection and image resolution for the bake-off harness.

A page is identified by ``(card_id, page)``. Card ids and page numbers come from
data files, so they are checked before they are used to build a file path, and
every resolved path must stay inside the directory it is meant to come from.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BLANK_MAX = 2
_CATEGORIES = ("photograph", "illustration", "document", "other")
_CARD_ID = re.compile(r"[0-9a-f]{16}")


@dataclass(frozen=True)
class Baseline:
    card_id: str
    row_key: str
    page: int
    image_type: str
    description: str
    visible_text: str
    claims: tuple[str, ...]


def page_key(b: Baseline) -> tuple[str, int]:
    return (b.card_id, b.page)


def load_baselines(obs_dir: Path, model: str) -> list[Baseline]:
    """Described pages from sidecars whose ``our_pass.model`` is ``model``."""
    out: list[Baseline] = []
    for path in sorted(obs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or (data.get("our_pass") or {}).get("model") != model:
            continue
        for page in data.get("pages") or []:
            desc = page.get("description") if isinstance(page, dict) else None
            if not isinstance(desc, str) or not desc.strip():
                continue
            claims = tuple(o["claim"] for o in page.get("observations") or []
                           if isinstance(o, dict) and isinstance(o.get("claim"), str))
            out.append(Baseline(
                str(data.get("card_id") or path.stem), str(page.get("row_key") or ""),
                int(page.get("page") or 1), str(page.get("image_type") or ""), desc,
                str(page.get("visible_text") or ""), claims))
    return sorted(out, key=lambda b: (b.card_id, b.row_key, b.page))


def categorize(image_type: str) -> str:
    t = image_type.lower()
    if "blank" in t or "empty" in t:
        return "blank"
    if re.search(r"illustrat|render|drawing|diagram", t):
        return "illustration"
    if re.search(r"photo", t):
        return "photograph"
    if re.search(r"scan|document|page|text|letter|memo|form", t):
        return "document"
    return "other"


def select_sample(pool: list[Baseline], n: int, seed: int,
                  resolvable: Callable[[Baseline], bool] | None = None) -> list[Baseline]:
    """Seeded, order-independent, round-robin across image kinds; blanks capped.

    Pages that fail ``resolvable`` are dropped before drawing, so a page with no
    image is replaced by another eligible one and the sample stays full size.
    """
    rng = random.Random(seed)
    ordered = sorted((b for b in pool if resolvable is None or resolvable(b)),
                     key=lambda b: (b.card_id, b.row_key, b.page))
    buckets: dict[str, list[Baseline]] = {c: [] for c in (*_CATEGORIES, "blank")}
    for b in ordered:
        buckets[categorize(b.image_type)].append(b)
    for name in buckets:
        rng.shuffle(buckets[name])
    blanks = buckets.pop("blank")[: min(BLANK_MAX, n)]
    picked: list[Baseline] = []
    want = n - len(blanks)
    while len(picked) < want and any(buckets.values()):
        for name in _CATEGORIES:
            if buckets[name] and len(picked) < want:
                picked.append(buckets[name].pop())
    return sorted(picked + blanks, key=lambda b: (b.card_id, b.row_key, b.page))


def valid_page_ref(card_id: str, page: int) -> bool:
    """A card id is 16 lowercase hex characters; a page is a positive int."""
    return (bool(_CARD_ID.fullmatch(card_id)) and isinstance(page, int)
            and not isinstance(page, bool) and page > 0)


def inside(path: Path, root: Path) -> bool:
    """True when ``path``, once resolved, lies under the resolved ``root``."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return False


def _load_shas(registry: Path) -> dict[str, str]:
    """Last registry row wins: card id -> byte sha."""
    shas: dict[str, str] = {}
    if not registry.exists():
        return shas
    for line in registry.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("card_id") and row.get("byte_sha256"):
            shas[str(row["card_id"])] = str(row["byte_sha256"])
    return shas


def _asset_path(card: Any, sha: str | None, *, pdf_dir: Path, image_dir: Path,
                mirror_dir: Path) -> Path | None:
    """The file for a card, or None when it is absent or outside its directory."""
    if card.asset_type == "IMG":
        root, path = image_dir / card.card_id, image_dir / card.card_id / card.asset_filename
    else:
        root, path = pdf_dir / card.card_id, pdf_dir / card.card_id / card.asset_filename
        if inside(path, root) and not path.exists() and sha:
            root, path = mirror_dir / "archive", mirror_dir / "archive" / f"{sha}.pdf"
    return path if inside(path, root) and path.exists() else None


def build_resolver(manifest: Any, *, pdf_dir: Path, image_dir: Path, mirror_dir: Path,
                   registry: Path) -> Callable[[Baseline], Any]:
    """Map a described page to an item the pipeline's renderer can load.

    Any page of a PDF card resolves, not only the image-only ones: the renderer
    rasterizes whatever page it is given. The PDF is the downloaded asset, else
    the mirrored bytes named by the registry's last row for the card. A card id
    or page that is malformed, or a path that leaves its directory, resolves to
    nothing.
    """
    from pursue_index.vision.eligibility import EligibleItem, _row_keys

    shas = _load_shas(registry)
    groups: dict[str, list[Any]] = {}
    for card in manifest.cards:
        if card.asset_type in ("IMG", "PDF"):
            groups.setdefault(card.card_id, []).append(card)
    keyed = {cid: dict(zip(_row_keys(rows), rows, strict=True)) for cid, rows in groups.items()}

    def resolve(b: Baseline) -> Any:
        card = (keyed.get(b.card_id) or {}).get(b.row_key)
        if not valid_page_ref(b.card_id, b.page) or card is None or not card.asset_filename:
            return None
        path = _asset_path(card, shas.get(b.card_id), pdf_dir=pdf_dir, image_dir=image_dir,
                           mirror_dir=mirror_dir)
        if path is None:
            return None
        img_card = card.asset_type == "IMG"
        return EligibleItem(card_id=card.card_id, page=1 if img_card else b.page,
                            kind="img_card" if img_card else "image_only_page",
                            image_path=path, title=card.title, row_key=b.row_key)

    return resolve
