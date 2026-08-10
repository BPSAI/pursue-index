"""A/V direct-fetch stage (pipeline stage 3): DOD id -> file URL -> staged bytes.

Automates the operator's manual DVIDS download step. ``client`` resolves a
card's ``dvids_video_id`` to its direct DOD asset file URL (through the same
HTTP client every other public fetch in this project uses) and retrieves the
bytes; ``select`` scopes a manifest to a release's A/V rows; ``fetch``
orchestrates the two into a staging directory consumed unchanged by
``scripts/ingest_release_videos.py --desktop`` (the existing DOD-id matcher).

Staging into that existing directory shape is what lets this stage replace the
manual step without touching the ingest script that follows it.
"""

from __future__ import annotations
