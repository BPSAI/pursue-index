"""Unattended local promotion of a metadata-only tranche.

``pursue tranche autopilot`` runs the release steps that need no human
judgement for a tranche whose receipt shows only allowlisted field edits:
approve, the dry-run scope check, the storage and data-root preflights, the
local promote, ``make ship-ready`` and the web tests, then one local commit.
It never publishes anything: pushing the branch, opening the pull request and
merging it stay with the operator, and the result JSON spells out those
commands as text.

Modules:

* ``outcome`` -- exit codes and the stop signal the steps raise.
* ``eligibility`` -- the fail-closed receipt check and the field allowlist.
* ``runner`` -- the injectable command runner (subprocess in production).
* ``worklists`` -- the post-dry-run "both worklists are empty" check.
* ``gitops`` -- clean-tree check, branch, changed paths, local commit.
* ``steps`` / ``engine`` -- the ordered steps and the driver.
* ``result`` -- the result document and its schema.
"""

from pursue_index.tranche_autopilot.engine import AutopilotConfig, run_autopilot
from pursue_index.tranche_autopilot.outcome import ExitCode

__all__ = ["AutopilotConfig", "ExitCode", "run_autopilot"]
