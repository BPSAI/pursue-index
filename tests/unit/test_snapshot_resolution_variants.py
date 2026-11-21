"""A manual date-resolution overlay is part of a snapshot's identity.

Snapshots are content-addressed and never rewritten. When overlay entries
apply to a CSV (they target a row whose upstream date has a 2-digit year),
the snapshot, the diff record, the receipt and the tranche-ready record
are written under a variant name ``<name>.r<digest12>`` and the snapshot
records ``resolutions_digest``; with no applicable entry every name and
byte is what it always was. Every reader picks the variant matching the
CURRENT overlay, and refuses when none does.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import poll_snapshot  # noqa: E402
import tranche_diff  # noqa: E402

from pursue_index.ingest_run import locate_snapshot, promote_snapshot  # noqa: E402
from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv  # noqa: E402
from pursue_index.scrape.date_resolutions import load_date_resolutions  # noqa: E402
from pursue_index.scrape.manifest import save_manifest  # noqa: E402
from pursue_index.scrape.types import Manifest  # noqa: E402
from pursue_index.scrape.variants import VariantMismatchError, current_digest  # noqa: E402

_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = "Release Date,Title,Type,Agency,Incident Date,PDF | Image Link"
_U1 = "https://www.war.gov/medialink/case_0001.pdf"
_U2 = "https://www.war.gov/medialink/case_0002.pdf"
_REPO = Path(__file__).resolve().parents[2]


def _csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    body = "\r\n".join(f'{rel},"{title}",PDF,FBI,{inc},{url}' for rel, title, inc, url in rows)
    return ("﻿" + _HEADER + "\r\n" + body + "\r\n").encode("utf-8")


_PRIOR = _csv([("10/23/2026", "Case 1", "1/18/1957", _U1)])
_TRANCHE = _csv([("10/23/26", "Case 1", "1/18/57", _U1), ("10/23/26", "Case 2", "1/18/57", _U2)])
_SHA = build_manifest(_TRANCHE, parse_csv(_TRANCHE), _URL).csv_sha256


class _Repo:
    """The checkout layout: data/manifests/{latest.json,snapshots,diffs}."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifests = root / "data" / "manifests"
        self.latest = self.manifests / "latest.json"
        self.snapshots = self.manifests / "snapshots"
        self.public = root / "web" / "public" / "data" / "snapshots"
        self.overlay = root / "data" / "date_resolutions.json"
        self.csv = root / "new.csv"
        save_manifest(build_manifest(_PRIOR, parse_csv(_PRIOR), _URL), self.latest)
        self.prior = json.loads(self.latest.read_text(encoding="utf-8"))
        self.csv.write_bytes(_TRANCHE)

    def argv(self, *extra: str) -> list[str]:
        return ["--csv", str(self.csv), "--latest", str(self.latest),
                "--date-resolutions", str(self.overlay),
                "--canonical-dir", str(self.snapshots), "--public-dir", str(self.public),
                "--diff-out", str(self.manifests / "diffs" / f"{_SHA}.json"), *extra]

    def resolve(self, card_id: str, value: str = "1/18/1957", who: str = "operator") -> None:
        self.overlay.write_text(json.dumps({"entries": [
            {"card_id": card_id, "field": "incident_date", "value": value, "curator": who,
             "approved_at": "2026-11-20T12:00:00Z"}]}), encoding="utf-8")

    def files(self) -> dict[str, bytes]:
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in sorted(self.root.rglob("*.json")) if p.is_file()}


def _case2_id() -> str:
    return next(c.card_id for c in parse_csv(_TRANCHE) if c.title == "Case 2")


@pytest.fixture()
def repo(tmp_path: Path) -> _Repo:
    return _Repo(tmp_path)


def test_overlay_added_after_the_snapshot_regenerates_and_promotes_resolved(repo) -> None:
    assert poll_snapshot.main(repo.argv()) == 0
    assert (repo.snapshots / f"{_SHA}.json").is_file()
    repo.resolve(_case2_id())
    assert poll_snapshot.main(repo.argv("--check-up-to-date")) == poll_snapshot.EXIT_NEEDS_REGEN
    assert poll_snapshot.main(repo.argv()) == 0
    digest = current_digest(_SHA, repo.snapshots, load_date_resolutions(repo.overlay))
    variant = repo.snapshots / f"{_SHA}.r{digest[:12]}.json"
    assert variant.is_file() and (repo.public / variant.name).is_file()
    assert (repo.manifests / "diffs" / f"{_SHA}.r{digest[:12]}.json").is_file()
    assert json.loads(variant.read_text())["resolutions_digest"] == digest
    assert poll_snapshot.main(repo.argv("--check-up-to-date")) == 0

    located = locate_snapshot(_SHA, repo.snapshots, None)  # None: the checkout's overlay
    assert located == variant
    promote_snapshot(located, repo.latest)
    promoted = json.loads(repo.latest.read_text())
    assert [c["incident_date"] for c in promoted["cards"]] == ["1/18/1957", "1/18/1957"]
    assert (repo.public / variant.name).read_bytes() == variant.read_bytes()
    assert (repo.public / f"{_SHA}.json").read_bytes() == (
        repo.snapshots / f"{_SHA}.json").read_bytes()  # the base public copy is untouched

    receipt = tranche_diff.diff_tranches(repo.prior, json.loads(variant.read_text()), {},
                                         fetch_byte_sha=lambda _u: None,
                                         date_overlay=load_date_resolutions(repo.overlay))
    assert "date_unresolved" not in receipt and "date_open" not in receipt
    assert [(m["card_id"], m["value"]) for m in receipt["date_manual_rows"]] == [
        (_case2_id(), "1/18/1957")]


def test_no_overlay_keeps_names_and_bytes(repo) -> None:
    assert poll_snapshot.main(repo.argv("--check-up-to-date")) == poll_snapshot.EXIT_NEEDS_REGEN
    assert poll_snapshot.main(repo.argv()) == 0
    names = sorted(p.name for p in repo.snapshots.glob("*.json"))
    assert names == sorted([f"{_SHA}.json", f"{repo.prior['csv_sha256']}.json", "index.json"])
    snap = (repo.snapshots / f"{_SHA}.json").read_text(encoding="utf-8")
    assert "resolutions_digest" not in snap
    assert "resolutions_digest" not in (repo.snapshots / "index.json").read_text()
    assert locate_snapshot(_SHA, repo.snapshots, None) == repo.snapshots / f"{_SHA}.json"
    assert poll_snapshot.main(repo.argv("--check-up-to-date")) == 0


@pytest.mark.parametrize("sha", ["096ef2c0058abd412a568d630df31cb836241c1c08c4f67bdc8cdb7e5c8418b9",
                                 "92b3ec7dd872"])
def test_committed_snapshots_serialize_byte_identically(sha: str) -> None:
    path = next((_REPO / "data" / "manifests" / "snapshots").glob(f"{sha}*.json"))
    text = path.read_text(encoding="utf-8")
    assert Manifest.model_validate_json(text).model_dump_json(indent=2, by_alias=True) == text


def test_same_overlay_rerun_is_a_noop_and_a_changed_one_a_new_variant(repo) -> None:
    repo.resolve(_case2_id())
    assert poll_snapshot.main(repo.argv()) == 0
    before = repo.files()
    assert poll_snapshot.main(repo.argv()) == 0
    assert repo.files() == before
    first = current_digest(_SHA, repo.snapshots, load_date_resolutions(repo.overlay))
    repo.resolve(_case2_id(), who="another curator")
    second = current_digest(_SHA, repo.snapshots, load_date_resolutions(repo.overlay))
    assert second != first
    assert poll_snapshot.main(repo.argv("--check-up-to-date")) == poll_snapshot.EXIT_NEEDS_REGEN
    assert poll_snapshot.main(repo.argv()) == 0
    assert {p.name for p in repo.snapshots.glob(f"{_SHA}*.json")} == {
        f"{_SHA}.r{first[:12]}.json", f"{_SHA}.r{second[:12]}.json"}
    assert locate_snapshot(_SHA, repo.snapshots, None) == repo.snapshots / f"{_SHA}.r{second[:12]}.json"


def test_variants_with_none_matching_is_a_hard_error(repo) -> None:
    repo.resolve(_case2_id())
    assert poll_snapshot.main(repo.argv()) == 0
    repo.resolve(_case2_id(), who="someone else")  # current overlay matches no variant
    with pytest.raises(VariantMismatchError, match="regenerate"):
        locate_snapshot(_SHA, repo.snapshots, None)


def test_base_only_with_an_applicable_overlay_is_a_hard_error(repo) -> None:
    assert poll_snapshot.main(repo.argv()) == 0
    repo.resolve(_case2_id())
    with pytest.raises(VariantMismatchError):
        locate_snapshot(_SHA, repo.snapshots, None)


def test_overlay_for_another_card_keeps_the_base_identity(repo) -> None:
    repo.resolve("0" * 16)
    assert poll_snapshot.main(repo.argv()) == 0
    assert (repo.snapshots / f"{_SHA}.json").is_file()
    assert locate_snapshot(_SHA, repo.snapshots, None) == repo.snapshots / f"{_SHA}.json"
