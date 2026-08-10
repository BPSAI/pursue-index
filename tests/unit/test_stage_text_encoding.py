"""Stage artifacts are UTF-8 regardless of the locale the CLI runs under.

Transcripts carry speaker labels and observations carry descriptions, both of
which can hold characters outside ASCII. Text files are therefore read and
written with an explicit encoding rather than the interpreter's locale
default, so the artifact a run writes is the artifact any other run reads.

The check runs in a subprocess under a non-UTF-8 locale, because that is the
only place the difference shows: a run under a UTF-8 locale behaves the same
either way, so a same-process assertion would pass without the property.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_SCRIPT = '''
import importlib.util, json, sys
from pathlib import Path

# A source file is UTF-8 whatever the locale is, so the label reaches the
# stage code intact and the only encoding in play is the artifacts' own.
# Every artifact below is written as UTF-8 bytes rather than as escapes, which
# is the shape a locale-default read cannot take.
label = "Sprecher Ä — «réunion»"
out_dir = Path(sys.argv[1])
repo_root = Path(sys.argv[2])

from pursue_index.embed.image_observations import load_observation_text
from pursue_index.embed.pipeline import iter_card_pages
from pursue_index.transcribe.pages import write_transcript_sidecar
from pursue_index.transcribe.run import produced_rows
from pursue_index.vision.eligibility import image_only_pages
from pursue_index.vision.index import register_cards
from pursue_index.vision.run import produced_pages


def write_utf8(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# --- a card directory whose page text is non-ASCII on disk ----------------
ocr_dir = out_dir / "ocr"
card_dir = ocr_dir / "pdf1"
write_utf8(card_dir / "meta.json", {"status": "ok"})
(card_dir / "pages.jsonl").write_text(
    json.dumps({"page": 1, "text": label}, ensure_ascii=False) + "\\n"
    + json.dumps({"page": 2, "text": ""}, ensure_ascii=False) + "\\n",
    encoding="utf-8",
)
rows = iter_card_pages(ocr_dir)
assert rows[0].text == label, rows[0].text
assert image_only_pages(card_dir / "pages.jsonl") == [2]

# --- a transcript the stage writes, then reads back -----------------------
write_transcript_sidecar(
    "aud1", ocr_dir, [{"speaker": label, "text": label, "start": 0, "end": 1}],
    multichannel=False, audio_duration_s=1.0, speakers=[label], source="aud1.mp4",
)
assert produced_rows(ocr_dir, {"aud1"}) == {("aud1", "")}

# --- an observation sidecar whose description is non-ASCII on disk --------
obs_dir = out_dir / "obs"
write_utf8(
    obs_dir / "imgA.json",
    {
        "card_id": "imgA", "schema_version": 1,
        "our_pass": {"model": "m"},
        "pages": [{"page": 1, "description": label, "observations": []}],
    },
)
assert produced_pages(obs_dir) == {("imgA", "", 1)}
register_cards(obs_dir / "index.json", ["imgA"])
lookup = load_observation_text(obs_dir / "index.json")
assert label in lookup[("imgA", 1)]

# --- the static search payload, through its real entry point --------------
spec = importlib.util.spec_from_file_location(
    "build_search_data", repo_root / "scripts" / "build_search_data.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
write_utf8(
    out_dir / "manifest.json",
    {
        "source_url": "https://www.war.gov/x.csv",
        "fetched_at": "2026-08-01T00:00:00Z",
        "csv_sha256": "0" * 64,
        "cards": [
            {"card_id": "pdf1", "title": label, "asset_type": "PDF",
             "agency": "FBI", "asset_url": "https://www.war.gov/a.pdf"},
            {"card_id": "imgA", "title": label, "asset_type": "IMG",
             "agency": "FBI", "asset_url": "https://www.war.gov/a.jpg"},
        ],
    },
)
payload_path = out_dir / "pages.json"
assert mod.build(
    ocr_dir, out_dir / "manifest.json", payload_path, obs_dir / "index.json"
) == 0
docs = json.loads(payload_path.read_text(encoding="utf-8"))
assert any(d["card_id"] == "imgA" and label in d["text"] for d in docs)
assert any(d["card_id"] == "pdf1" and d["text"] == label for d in docs)
print("ok")
'''


def test_stage_artifacts_round_trip_non_ascii_under_a_non_utf8_locale(
    tmp_path: Path,
) -> None:
    env = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        # Both interpreter-level widenings of the locale are off, or the
        # subprocess would quietly get UTF-8 anyway and the check would pass
        # whatever the code does.
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }
    probe = tmp_path / "probe.py"
    probe.write_text(_SCRIPT, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(probe), str(tmp_path), str(REPO_ROOT)],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
