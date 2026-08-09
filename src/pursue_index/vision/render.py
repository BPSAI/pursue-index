"""Image loading/rendering for the vision stage.

IMG cards load the downloaded asset directly. Image-only PDF pages rasterize a
single page at 150 DPI — matching the frozen July artifact's ``pdftoppm -r 150``
provenance note (and comfortably under the vision API's size cap, which the
client downscales to anyway).
"""

from __future__ import annotations

from pdf2image import convert_from_path
from PIL import Image

from pursue_index.vision.eligibility import EligibleItem

_RENDER_DPI = 150


def load_image_for(item: EligibleItem, dpi: int = _RENDER_DPI) -> Image.Image:
    """Load the image for one eligible item.

    ``img_card`` opens the downloaded asset; ``image_only_page`` rasterizes just
    that one page of the source PDF at ``dpi``. Raises if ``image_path`` is
    missing — callers select only items whose asset exists.
    """
    if item.image_path is None:
        raise ValueError(f"eligible item has no image_path: {item.card_id}")
    if item.kind == "img_card":
        return Image.open(item.image_path).convert("RGB")
    pages = convert_from_path(
        str(item.image_path), dpi=dpi, first_page=item.page, last_page=item.page
    )
    if not pages:
        raise ValueError(
            f"no page {item.page} rendered from {item.image_path}"
        )
    return pages[0].convert("RGB")
