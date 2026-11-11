"""The autopilot's result document.

Written to ``--result`` on every exit, valid against
``schemas/tranche-autopilot-result.schema.json``. ``operator_next`` is plain
text for a human: the commands that publish the local commit. The autopilot
itself never runs them.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pursue_index.paths import installed_checkout_root

__all__ = ["SCHEMA_RELPATH", "SCHEMA_VERSION", "Step", "commit_message", "operator_next",
           "redact", "repo_slug", "schema_path", "write_result"]

SCHEMA_VERSION = "1.0.0"
SCHEMA_RELPATH = Path("schemas") / "tranche-autopilot-result.schema.json"
# Child output lands in ``steps[].detail``; mask anything shaped like a secret.
_SECRETS = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)[\"']?\s*[=:]\s*\S+"
    r"|\b(?:sk|pk|rk)-[A-Za-z0-9_-]{12,}"
    r"|(?i:\bbearer\s+\S+)"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|(?<=://)[^/\s:@]+:[^@\s]+(?=@)"
)


@dataclass
class Step:
    name: str
    command: str | None = None
    status: str = "not-run"  # ok | skipped | failed | not-run
    duration_s: float = 0.0
    exit_code: int | None = None
    detail: str = ""
    _started: float = field(default=0.0, repr=False)

    def start(self) -> None:
        self._started = time.monotonic()

    @property
    def running(self) -> bool:
        """Started but not yet finished (an exception escaped it)."""
        return self.status == "not-run" and self._started > 0

    def finish(self, status: str, detail: str = "", exit_code: int | None = None) -> None:
        self.status = status
        self.detail = detail
        self.exit_code = exit_code
        self.duration_s = round(time.monotonic() - self._started, 3) if self._started else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "command": self.command, "status": self.status,
                "duration_s": self.duration_s, "exit_code": self.exit_code,
                "detail": self.detail}


def redact(text: str) -> str:
    """Mask ``NAME_KEY=value``-style assignments and API-key-shaped tokens."""
    return _SECRETS.sub(lambda m: f"{m.group(1)}=<redacted>" if m.group(1) else "<redacted>",
                        text)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def commit_message(tranche_sha: str, summary: dict[str, int], fields: list[str]) -> str:
    """The promote commit's message. No trailers: the operator adds any."""
    counts = ", ".join(f"{k}={v}" for k, v in sorted(summary.items()))
    return (
        f"release: promote tranche {tranche_sha[:12]} (metadata-only)\n\n"
        f"Tranche: {tranche_sha}\n"
        f"Receipt summary: {counts}\n"
        f"Fields edited: {', '.join(fields) or '(none)'}\n\n"
        "Promoted locally by `pursue tranche autopilot`: data-root preflight,\n"
        "scope preview, approve, dry-run scope check (both work-lists empty),\n"
        "storage verify, promote, make ship-ready, web tests.\n"
    )


_SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_REMOTE = re.compile(
    r"(?:git@github\.com:|ssh://git@github\.com/|https://github\.com/)"
    r"(?P<slug>[^/\s]+/[^/\s]+?)(?:\.git)?/?"
)


def repo_slug(origin_url: str) -> str | None:
    """``owner/name`` from a GitHub origin URL, or ``None`` if it is not one."""
    match = _REMOTE.fullmatch(origin_url.strip())
    if match is None:
        return None
    slug = match.group("slug")
    return slug if _SLUG.fullmatch(slug) and ".." not in slug else None


def operator_next(repo_root: Path, branch: str, tranche_sha: str,
                  slug: str | None = None) -> list[str]:
    """What a human runs to publish the local commit (text only).

    The ``gh`` lines name the repository with ``--repo`` when the origin
    remote gave a valid ``owner/name``; otherwise they ``cd`` into the
    checkout first, so neither resolves the repository from a stray cwd.
    """
    title = shlex.quote(f"release: promote tranche {tranche_sha[:12]} (metadata-only)")
    repo, head = shlex.quote(str(repo_root)), shlex.quote(branch)
    body = shlex.quote("Metadata-only tranche promoted by the autopilot; see the result JSON.")
    target, prefix = (f" --repo {shlex.quote(slug)}", "") if slug else ("", f"cd {repo} && ")
    return [
        f"git -C {repo} log --stat -1   # review the promote commit",
        f"git -C {repo} push --set-upstream origin {head}",
        f"{prefix}gh pr create{target} --base main --head {head} --title {title} --body {body}",
        f"{prefix}gh pr merge{target} <PR-number>   # after review; merging deploys "
        "(runbook step 13)",
    ]


def schema_path() -> Path:
    root = installed_checkout_root()
    if root is None:
        raise FileNotFoundError(f"no source checkout to read {SCHEMA_RELPATH} from")
    return root / SCHEMA_RELPATH


def write_result(path: Path, document: dict[str, Any]) -> None:
    """Write ``document`` to ``path`` atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
