"""Fakes shared by the NTRS fetch and source tests: one real sample, no socket."""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

from pursue_index.ntrs_fetch import NtrsFetcher

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "tests" / "fixtures" / "ntrs-search-apollo12-debrief.json"
TODAY = date(2026, 11, 25)
HOSTS = frozenset({"ntrs.nasa.gov"})


def sample() -> dict[str, Any]:
    return json.loads(SAMPLE.read_text())


def card(**over: Any) -> dict[str, Any]:
    row = {
        "card_id": "a0a0a0a0a0a0a012",
        "title": "NASA-UAP-D099, Apollo 12 Medical Debriefing",
        "agency": "NASA",
        "release_date": "5/8/2026",
        "incident_date": "1969",
        "description": "",
        "asset_filename": "NASA-UAP-D099.pdf",
    }
    row.update(over)
    return row


def variant(**fields: Any) -> dict[str, Any]:
    """The real sample with top-level result fields replaced (None removes one)."""
    data = copy.deepcopy(sample())
    for key, value in fields.items():
        if value is None:
            data["results"][0].pop(key, None)
        else:
            data["results"][0][key] = value
    return data


class Resp:
    def __init__(self, status: int, payload: Any = None) -> None:
        self.status_code = status
        self.text = json.dumps(payload if payload is not None else {})
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return json.loads(self.text)


class Net:
    """Records events in order; replies from a queue, repeating the last."""

    def __init__(self, *responses: Resp) -> None:
        self.responses = list(responses) or [Resp(200, {"results": []})]
        self.events: list[str] = []
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    def get(self, url: str, headers: Any) -> Resp:
        self.events.append("get")
        self.urls.append(url)
        self.headers.append(dict(headers))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    def sleep(self, seconds: float) -> None:
        self.events.append(f"sleep:{seconds}")

    def fetcher(self) -> NtrsFetcher:
        return NtrsFetcher(get=self.get, hosts=HOSTS, sleep=self.sleep)
