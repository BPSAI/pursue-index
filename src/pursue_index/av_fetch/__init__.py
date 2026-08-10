"""A/V direct-fetch stage (pipeline stage 5): DOD id -> file URL -> staged bytes.

Automates the operator's manual DVIDS download step. ``client`` resolves a
card's ``dvids_video_id`` to its direct DOD asset file URL (via the same
curl_cffi Chrome-impersonation client used for war.gov) and fetches the
bytes; ``select`` scopes a manifest to a release's A/V rows; ``fetch``
orchestrates the two into a staging directory consumed unchanged by
``scripts/ingest_release_videos.py --desktop`` (the existing DOD-id matcher).

Probed 2026-08-09 (T48.5): a real ``/video/<id>`` page fetch and the direct
asset GET both succeeded (200, not CDN-blocked) for a VID and an AUD asset —
see the task summary for the full probe record.
"""

from __future__ import annotations
