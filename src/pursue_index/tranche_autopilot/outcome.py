"""Exit codes for ``pursue tranche autopilot`` and the stop signal.

The codes are a contract with whatever schedules the command, so they are
deliberately distinct from typer's own 1/2 usage errors:

====  ======================  ==============================================
code  outcome                 meaning
====  ======================  ==============================================
10    done-needs-operator     promoted and committed locally; a human pushes,
                              opens the pull request and merges
20    refused-needs-lease     the tranche carries content work (new, renamed,
                              quarantined, restored cards, added rows, or a
                              non-empty worklist); run the attended release
21    refused-ineligible      not a metadata-only tranche the autopilot may
                              promote (removed cards, a non-allowlisted
                              field, ...)
21    refused-superseded      the poller moved origin/main while running
30    gate-failed             a release gate exited non-zero; the result
                              names the step
40    precondition-missing    an input the run needs is absent or malformed
                              (bad sha, no receipt, dirty tree, no data root)
====  ======================  ==============================================
"""

from __future__ import annotations

from enum import IntEnum

__all__ = ["AutopilotStopError", "ExitCode", "Outcome"]


class ExitCode(IntEnum):
    DONE = 10
    NEEDS_LEASE = 20
    INELIGIBLE = 21
    GATE_FAILED = 30
    PRECONDITION = 40


class Outcome:
    """The ``outcome`` strings recorded in the result JSON."""

    DONE = "done-needs-operator"
    NEEDS_LEASE = "refused-needs-lease"
    INELIGIBLE = "refused-ineligible"
    SUPERSEDED = "refused-superseded"
    GATE_FAILED = "gate-failed"
    PRECONDITION = "precondition-missing"


_DEFAULT_OUTCOME = {
    ExitCode.DONE: Outcome.DONE,
    ExitCode.NEEDS_LEASE: Outcome.NEEDS_LEASE,
    ExitCode.INELIGIBLE: Outcome.INELIGIBLE,
    ExitCode.GATE_FAILED: Outcome.GATE_FAILED,
    ExitCode.PRECONDITION: Outcome.PRECONDITION,
}


class AutopilotStopError(Exception):
    """Raised by a step to end the run with ``code``.

    ``outcome`` defaults from the code; 21 is shared by "ineligible" and
    "superseded", so the freshness re-check passes it explicitly.
    """

    def __init__(self, code: ExitCode, message: str, outcome: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.outcome = outcome or _DEFAULT_OUTCOME[code]
