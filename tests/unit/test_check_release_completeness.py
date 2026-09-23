"""Tests for ``scripts/check_release_completeness.py``.

The gate refuses a release whose AUD cards lack an AssemblyAI transcript
sidecar, whose VID/AUD cards lack a registered A/V byte row, or whose
transcript has the channel-duplication shape. Every test runs against a
fixture manifest, registry and data root under ``tmp_path`` — never the real
NAS.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from pursue_index.transcribe.pages import write_transcript_sidecar  # noqa: E402
from tests.support.completeness_env import (  # noqa: E402
    AUD,
    VID,
    Env,
    registry_row,
    write_jsonl,
)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


# --- transcripts ------------------------------------------------------------


def test_aud_card_without_sidecar_is_named_and_refused(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    code, out = env.run(capsys)
    assert code == 1
    assert AUD in out
    assert "missing transcript" in out


def test_aud_card_with_sidecar_passes(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    env.sidecar(AUD)
    code, _ = env.run(capsys)
    assert code == 0


def test_sidecar_from_another_engine_is_not_a_transcript(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    env.sidecar(AUD, engine="tesseract")
    code, out = env.run(capsys)
    assert code == 1
    assert AUD in out


def test_waiver_passes_and_is_printed(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    write_jsonl(env.waivers, [{"card_id": AUD, "reason": "silent tape, no speech"}])
    code, out = env.run(capsys)
    assert code == 0
    assert "waived" in out
    assert AUD in out
    assert "silent tape, no speech" in out


def test_waiver_without_a_reason_fails_closed(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    write_jsonl(env.waivers, [{"card_id": AUD, "reason": "  "}])
    code, out = env.run(capsys)
    assert code == 1
    assert "reason" in out


def test_waiver_naming_another_card_does_not_cover_this_one(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    write_jsonl(env.waivers, [{"card_id": "f" * 16, "reason": "unrelated"}])
    code, _ = env.run(capsys)
    assert code == 1


def test_vid_card_needs_no_transcript(env, capsys):
    env.set_cards({VID: "VID"})
    env.set_registry([registry_row(VID)])
    code, _ = env.run(capsys)
    assert code == 0


# --- A/V bytes --------------------------------------------------------------


def test_vid_card_without_registry_row_is_named_and_refused(env, capsys):
    env.set_cards({VID: "VID"})
    code, out = env.run(capsys)
    assert code == 1
    assert VID in out
    assert "missing A/V bytes" in out


def test_vid_card_with_registry_row_passes(env, capsys):
    env.set_cards({VID: "VID"})
    env.set_registry([registry_row(VID)])
    code, _ = env.run(capsys)
    assert code == 0


def test_a_pdf_registry_row_is_not_the_av_bytes(env, capsys):
    """9 real VID/AUD cards also carry a ``<card_id>.pdf`` row for their pairing."""
    env.set_cards({VID: "VID"})
    env.set_registry([registry_row(VID, "pdf")])
    code, out = env.run(capsys)
    assert code == 1
    assert VID in out


def test_registry_rows_without_current_key_are_ignored(env, capsys):
    env.set_cards({VID: "VID"})
    env.set_registry([{"card_id": VID, "archive_key": "archive/x.mp4"}])
    code, _ = env.run(capsys)
    assert code == 1


def test_pdf_and_img_cards_need_no_av_bytes(env, capsys):
    env.set_cards({"c" * 16: "PDF", "d" * 16: "IMG"})
    code, _ = env.run(capsys)
    assert code == 0


# --- channel duplication ----------------------------------------------------


def _dual_mono_utterances(words: int = 40) -> list[dict]:
    return [{"speaker": ch, "text": f"word{i}"} for i in range(words) for ch in ("1", "2")]


def test_channel_duplicated_sidecar_is_refused(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    write_transcript_sidecar(
        AUD,
        env.ocr_dir,
        _dual_mono_utterances(),
        multichannel=True,
        audio_duration_s=60.0,
        speakers=["1", "2"],
        source="t",
    )
    code, out = env.run(capsys)
    assert code == 1
    assert "channel-duplicated transcript" in out
    assert AUD in out


def test_ordinary_diarized_sidecar_is_not_flagged(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    utterances = [
        {
            "speaker": "A" if i % 2 == 0 else "B",
            "text": f"This is a full sentence number {i} spoken by someone.",
        }
        for i in range(40)
    ]
    write_transcript_sidecar(
        AUD,
        env.ocr_dir,
        utterances,
        multichannel=False,
        audio_duration_s=60.0,
        speakers=["A", "B"],
        source="t",
    )
    code, _ = env.run(capsys)
    assert code == 0


def test_waiver_does_not_excuse_a_duplicated_sidecar(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    write_transcript_sidecar(
        AUD,
        env.ocr_dir,
        _dual_mono_utterances(),
        multichannel=True,
        audio_duration_s=60.0,
        speakers=["1", "2"],
        source="t",
    )
    write_jsonl(env.waivers, [{"card_id": AUD, "reason": "r"}])
    code, out = env.run(capsys)
    assert code == 1
    assert "channel-duplicated transcript" in out


# --- reporting --------------------------------------------------------------


def test_failures_in_two_categories_are_both_reported(env, capsys):
    env.set_cards({AUD: "AUD", VID: "VID"})
    code, out = env.run(capsys)
    assert code == 1
    assert "missing transcript" in out and AUD in out
    assert "missing A/V bytes" in out and VID in out


def test_one_line_per_offending_id_and_a_summary_count(env, capsys):
    env.set_cards({AUD: "AUD", VID: "VID"})
    _, out = env.run(capsys)
    lines = out.strip().splitlines()
    assert sum(1 for line in lines if VID in line) == 1
    # AUD is missing both a transcript and its bytes: two problems, two lines.
    assert sum(1 for line in lines if AUD in line) == 2
    assert "3 problem" in lines[-1]


def test_a_clean_run_says_so(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    env.sidecar(AUD)
    _, out = env.run(capsys)
    assert "OK" in out


# --- failure modes ----------------------------------------------------------


def test_missing_manifest_is_a_clear_error_not_a_traceback(env, capsys):
    env.manifest.unlink()
    code, out = env.run(capsys)
    assert code == 1
    assert "manifest" in out.lower()
    assert "Traceback" not in out


def test_malformed_manifest_is_a_clear_error(env, capsys):
    env.manifest.write_text("{not json", encoding="utf-8")
    code, out = env.run(capsys)
    assert code == 1
    assert "manifest" in out.lower()


def test_absent_waivers_file_is_no_waivers(env, capsys):
    assert not env.waivers.exists()
    env.set_cards({VID: "VID"})
    env.set_registry([registry_row(VID)])
    code, _ = env.run(capsys)
    assert code == 0


def test_malformed_waivers_file_fails_closed(env, capsys):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    env.waivers.write_text("{not json\n", encoding="utf-8")
    code, out = env.run(capsys)
    assert code == 1
    assert "waivers" in out.lower()


def test_unreadable_data_root_fails_closed(env, capsys):
    shutil.rmtree(env.data_root)
    env.set_cards({VID: "VID"})
    env.set_registry([registry_row(VID)])
    code, out = env.run(capsys)
    assert code == 1
    assert "data root" in out.lower()


def test_missing_registry_is_a_clear_error(env, capsys):
    env.registry.unlink()
    code, out = env.run(capsys)
    assert code == 1
    assert "registry" in out.lower()
