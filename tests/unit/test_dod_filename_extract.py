"""Tests for ``extract_dod_filename`` in ``scripts/build_video_posters.py``.

The DVIDS page-scrape must resolve a card's DOD asset id to the operator's
canonical ``DOD_<id>.mp4`` filename regardless of which surface form the id
appears in on the page. Regression guard for the Release-04 audio bug: AUD
items (e.g. the NASA Apollo debriefings) never expose a bare ``DOD_<id>.mp4``
string — only a resolution-suffixed CDN URL and a dotted ``DOD_<id>.0000001``
reference — so the original ``DOD_(\\d{8,12})\\.mp4`` regex returned None and
every audio card fell through to a 404ing ``/audio/`` fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from build_video_posters import extract_dod_filename  # noqa: E402


def test_bare_mp4_download_link_video_page():
    # VID pages expose a clean download filename directly.
    body = '<a href="/download/DOD_111830004.mp4">Download</a>'
    assert extract_dod_filename(body) == "DOD_111830004.mp4"


def test_cloudfront_resolution_suffixed_url_audio_page():
    # AUD pages only carry the transcoded CDN URL with a resolution suffix.
    body = (
        "https://d34w7g4gy10iej.cloudfront.net/video/2607/"
        "DOD_111830063/DOD_111830063-1920x1080-9000k.mp4"
    )
    assert extract_dod_filename(body) == "DOD_111830063.mp4"


def test_dotted_sequence_reference_audio_page():
    # The other id surface on AUD pages: DOD_<id>.0000001 (not .mp4).
    body = 'data-asset="DOD_111830069.0000001" class="player"'
    assert extract_dod_filename(body) == "DOD_111830069.mp4"


def test_no_dod_reference_returns_none():
    assert extract_dod_filename("<html>no asset here</html>") is None


def test_returns_canonical_even_when_multiple_surfaces_present():
    # First match wins and is normalized to the canonical clean filename.
    body = (
        "DOD_111830092-1920x1080-9000k.mp4 ... later DOD_111830092.0000001"
    )
    assert extract_dod_filename(body) == "DOD_111830092.mp4"
