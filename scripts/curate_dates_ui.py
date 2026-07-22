"""Local-only review UI for curated display-date proposals.

Phase 3 of the display-date-curation plan. Operator runs:

    python scripts/curate_dates_ui.py

Then opens http://localhost:5555/ in a browser. The UI walks through
proposals one at a time, surfacing the proposed date + the evidence
span the writer agent cited. Operator decides accept / edit / reject /
abstain via keyboard shortcuts. Approved entries land in
``data/display_dates.json`` incrementally (each approval writes the
file so a crash mid-session doesn't lose work).

Design choices:

- Stdlib HTTP server (no FastAPI dependency dance for a single-page
  operator tool). Single file, single port (5555 by default).
- Persists across sessions: on launch, skips proposals whose card_id
  is already in ``data/display_dates.json``. Operator can resume.
- Keyboard shortcuts: ``a`` accept / ``e`` edit / ``r`` reject /
  ``s`` mark abstention / ``→`` or ``j`` next without action.
- Read-only against the proposals file (preserves the original
  agent draft for audit); the curated output is a separate file.

Outputs the same schema the ``DisplayDateEntry`` dataclass and the
``merge_display_dates`` function expect — so once the operator
approves entries, ``pursue scrape run`` picks them up automatically.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PROPOSALS = _REPO_ROOT / "data" / "display_dates_proposals.jsonl"
DEFAULT_CURATED = _REPO_ROOT / "data" / "display_dates.json"
DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_PORT = 5555


def _load_proposals(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _load_curated(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in data.get("entries", []):
        cid = entry.get("card_id")
        if cid:
            out[cid] = entry
    return out


def _save_curated(path: Path, by_card: dict[str, dict[str, Any]]) -> None:
    """Atomic write so a kill mid-flush doesn't corrupt the file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {"entries": list(by_card.values())}
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    tmp.replace(path)


def _build_queue(proposals: list[dict[str, Any]], curated: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Pending = proposals whose card_id is NOT yet in curated."""
    return [p for p in proposals if p["card_id"] not in curated]


_HTML = (Path(__file__).parent / "curate_dates_ui_assets" / "index.html").read_text()


class _Handler(BaseHTTPRequestHandler):
    proposals: list[dict[str, Any]] = []
    curated_path: Path = DEFAULT_CURATED
    manifest_by_card: dict[str, dict[str, Any]] = {}

    def _json(self, body: dict[str, Any], status: int = 200) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ANN401
        # Quieter logs — show one line per request
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            body = _HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/state":
            curated = _load_curated(self.curated_path)
            pending = _build_queue(self.proposals, curated)
            # Enrich pending entries with manifest context
            enriched = []
            for p in pending:
                row = dict(p)
                m = self.manifest_by_card.get(p["card_id"], {})
                row["manifest"] = {
                    "title": m.get("title"),
                    "agency": m.get("agency"),
                    "asset_type": m.get("asset_type"),
                    "incident_date": m.get("incident_date"),
                }
                enriched.append(row)
            self._json({
                "pending": enriched,
                "curated_count": len(curated),
                "total": len(self.proposals),
            })
            return
        self._json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/decide":
            self._json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        action = body.get("action")
        card_id = body.get("card_id")
        if not card_id or not action:
            self._json({"error": "card_id + action required"}, status=400)
            return

        curated = _load_curated(self.curated_path)
        if action == "skip":
            # No persistence — UI will refetch and move on
            self._json({"ok": True, "saved": False})
            return
        if action == "reject":
            # Persist a tombstone so we don't re-prompt? For now no — operator
            # can re-run the agent if they want a fresh draft. Just skip.
            self._json({"ok": True, "saved": False})
            return
        if action in ("accept", "abstain"):
            entry = body.get("entry") or {}
            if not entry.get("card_id"):
                entry["card_id"] = card_id
            entry.setdefault("display_date_approved_at", datetime.now(timezone.utc).isoformat())
            entry.setdefault("display_date_curator", "operator")
            curated[card_id] = entry
            _save_curated(self.curated_path, curated)
            self._json({"ok": True, "saved": True})
            return
        self._json({"error": f"unknown action {action}"}, status=400)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposals", type=Path, default=DEFAULT_PROPOSALS)
    parser.add_argument("--curated", type=Path, default=DEFAULT_CURATED)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    proposals = _load_proposals(args.proposals)
    if not proposals:
        print(f"No proposals at {args.proposals}. Run draft_display_dates.py first.", file=sys.stderr)
        return 1

    manifest = json.loads(args.manifest.read_text())
    manifest_by_card = {c["card_id"]: c for c in manifest.get("cards", [])}

    _Handler.proposals = proposals
    _Handler.curated_path = args.curated
    _Handler.manifest_by_card = manifest_by_card

    url = f"http://localhost:{args.port}/"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    print(f"display-date review UI: {url}")
    print(f"  proposals: {len(proposals)} ({args.proposals.relative_to(_REPO_ROOT)})")
    print(f"  curated output: {args.curated.relative_to(_REPO_ROOT)}")
    print(f"  press Ctrl+C to stop")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
