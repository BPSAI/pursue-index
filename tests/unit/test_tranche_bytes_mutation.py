"""Single-byte content-stream mutations never turn an adversarial case into
``metadata-only``.

Reuses every adversarial fixture in ``test_tranche_bytes_hardening``: its
``_verdict`` helper is swapped for one that, for each stream in the pair,
flips ONE byte of the stream data and records the verdict. A flip inside the
shared prefix is applied to both files (the pair still shares its prefix); a
flip inside the appended update changes only the new file.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from pursue_index.tranche_bytes import classify_bytes
from tests.support.tranche_bytes_fakes import write_pair
from tests.unit import test_tranche_bytes_hardening as hardening

_STREAM = re.compile(rb"stream\r?\n")


def _mutants(old: bytes, new: bytes) -> Iterator[tuple[bytes, bytes]]:
    """One (old, new) pair per stream: its first data byte XOR-flipped."""
    for m in _STREAM.finditer(new):
        at = m.end()
        if at >= len(new) or new[at:at + 1] == b"\n":
            continue
        flipped = new[:at] + bytes([new[at] ^ 0x01]) + new[at + 1:]
        if at < len(old):
            yield old[:at] + bytes([old[at] ^ 0x01]) + old[at + 1:], flipped
        else:
            yield old, flipped


def _case_names() -> list[str]:
    return [n for n, f in inspect.getmembers(hardening, inspect.isfunction)
            if n.startswith("test_") and "tmp_path" in inspect.signature(f).parameters]


@pytest.mark.parametrize("name", _case_names())
def test_one_byte_mutation_of_an_adversarial_case_is_never_metadata_only(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def mutating_verdict(directory: Path, old: bytes, new: bytes) -> str:
        verdicts = [classify_bytes(*write_pair(directory, o, n), isolated=False) for o, n in _mutants(old, new)]
        verdicts.append(classify_bytes(*write_pair(directory, old, new), isolated=False))
        seen.extend(verdicts)
        return hardening.CC

    monkeypatch.setattr(hardening, "_verdict", mutating_verdict)
    getattr(hardening, name)(tmp_path)
    assert seen and "metadata-only" not in seen
