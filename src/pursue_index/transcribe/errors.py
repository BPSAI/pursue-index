"""Error taxonomy of the direct AssemblyAI client (``transcribe.client``).

Kept apart from the HTTP calls so the run layer and tests can name a failure
without importing the client, and so the client module stays focused on
upload/submit/poll.
"""

from __future__ import annotations


class TranscribeError(Exception):
    """Base of the AAI client's error taxonomy."""


class ApiKeyMissingError(TranscribeError):
    """``ASSEMBLYAI_API_KEY`` isn't set in the environment."""


class UploadError(TranscribeError):
    """The upload request failed or returned an unusable response."""


class SubmitError(TranscribeError):
    """Job submission/status-poll HTTP call failed or was malformed."""


class PollTimeoutError(TranscribeError):
    """Polling exceeded the hard timeout before reaching a terminal state."""


class TranscriptFailedError(TranscribeError):
    """AssemblyAI itself reported the transcript job as failed."""
