"""scripts/release_intermediates.py: the guard in front of attaching a packed
intermediates archive to a tag's Release.

It refuses unless the files match their SHA256SUMS, the stamp committed at
HEAD pins the tarball, and no packed QC row carries a dropped field; only then
does it upload, through an injected runner, never with ``--clobber``.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_stamp  # noqa: E402
import intermediates  # noqa: E402
import release_intermediates  # noqa: E402

TAG = "v1.2.3"
_IDENT = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


def _data_root(tmp_path: Path, qc_row: dict) -> Path:
    root = tmp_path / "data-root"
    d = root / "ocr" / "aaaa000000000001"
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{}")
    (d / "pages.jsonl").write_text('{"page": 1, "text": "t"}\n')
    (d / "pages_cleaned.jsonl").write_text('{"page": 1, "text": "t"}\n')
    (d / "pages_cleaned_qc.jsonl").write_text(json.dumps(qc_row) + "\n")
    emb = root / "embeddings" / intermediates.EMBED_MODEL
    emb.mkdir(parents=True)
    (emb / "index.json").write_text("[]")
    (emb / "vectors.bin").write_bytes(b"\0" * 16)
    return root


def _pack(tmp_path: Path) -> Path:
    out = tmp_path / "assets"
    intermediates.pack(_data_root(tmp_path, {"page": 1, "verdict": "ok"}), out, TAG)
    return out


def _repo(tmp_path: Path, tarball: Path | None) -> Path:
    """A git repo whose HEAD commits a stamp, pinning ``tarball`` when given."""
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    stamp: dict = {"schema": build_stamp.SCHEMA, "builder_commit": "a" * 40, "files": {}}
    if tarball is not None:
        stamp["intermediates"] = build_stamp.intermediates_entry(tarball)
    (repo / build_stamp.STAMP_PATH).write_text(json.dumps(stamp))
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), *_IDENT, "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), *_IDENT, "commit", "-qm", "stamp"], check=True)
    return repo


class Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        return 0


def _release(out: Path, repo: Path, runner: Runner, tag: str = TAG) -> int:
    return release_intermediates.release(tag, out, repo, run=runner)


def test_a_pinned_clean_archive_is_uploaded_with_its_sums(tmp_path: Path,
                                                          capsys: pytest.CaptureFixture[str]) -> None:
    out = _pack(tmp_path)
    tarball = out / f"intermediates-{TAG}.tar.gz"
    repo, runner = _repo(tmp_path, tarball), Runner()
    assert _release(out, repo, runner) == 0
    assert runner.calls == [["gh", "release", "upload", TAG, str(tarball),
                             str(out / "SHA256SUMS")]]
    # The line to paste into the release notes.
    sha = build_stamp.sha256_file(tarball)
    assert f"{sha}  {tarball.name}" in capsys.readouterr().out


def _refused(out: Path, repo: Path, needle: str, tag: str = TAG) -> None:
    runner = Runner()
    with pytest.raises(SystemExit) as exc:
        _release(out, repo, runner, tag)
    assert needle in str(exc.value)
    assert runner.calls == []


def test_a_missing_tarball_is_refused(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    tarball = out / f"intermediates-{TAG}.tar.gz"
    repo = _repo(tmp_path, tarball)
    tarball.unlink()
    _refused(out, repo, "not found")


def test_missing_sums_are_refused(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    repo = _repo(tmp_path, out / f"intermediates-{TAG}.tar.gz")
    (out / "SHA256SUMS").unlink()
    _refused(out, repo, "SHA256SUMS")


def test_a_sums_mismatch_is_refused(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    repo = _repo(tmp_path, out / f"intermediates-{TAG}.tar.gz")
    (out / "SHA256SUMS").write_text(f"{'0' * 64}  intermediates-{TAG}.tar.gz\n")
    _refused(out, repo, "does not match SHA256SUMS")


def test_a_stamp_without_the_key_is_refused(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    _refused(out, _repo(tmp_path, None), "no intermediates key")


def test_a_stamp_pinning_another_archive_is_refused(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    other = tmp_path / "other" / f"intermediates-{TAG}.tar.gz"
    other.parent.mkdir()
    other.write_bytes(b"another archive")
    _refused(out, _repo(tmp_path, other), "differs from the stamped")


def test_an_uncommitted_stamp_does_not_count(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    tarball = out / f"intermediates-{TAG}.tar.gz"
    repo = _repo(tmp_path, None)
    stamp = json.loads((repo / build_stamp.STAMP_PATH).read_text())
    stamp["intermediates"] = build_stamp.intermediates_entry(tarball)
    (repo / build_stamp.STAMP_PATH).write_text(json.dumps(stamp))  # not committed
    _refused(out, repo, "no intermediates key")


def test_no_stamp_at_head_is_refused(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), *_IDENT, "commit", "-q", "--allow-empty",
                    "-m", "empty"], check=True)
    _refused(out, repo, "no data/build-stamp.json at HEAD")


def _repack_with_raw_qc(out: Path, row: dict) -> Path:
    """Rewrite the packed tarball so its QC sidecar row is ``row`` verbatim
    (bypassing pack's scrub), and its SHA256SUMS to match."""
    tarball = out / f"intermediates-{TAG}.tar.gz"
    with tarfile.open(tarball, "r:gz") as tar:
        blobs = {m.name: tar.extractfile(m).read() for m in tar}  # type: ignore[union-attr]
    qc = next(n for n in blobs if n.endswith("/pages_cleaned_qc.jsonl"))
    blobs[qc] = (json.dumps(row) + "\n").encode()
    with tarfile.open(tarball, "w:gz") as tar:
        for name, data in blobs.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    sha = build_stamp.sha256_file(tarball)
    (out / "SHA256SUMS").write_text(f"{sha}  {tarball.name}\n")
    return tarball


def test_a_qc_row_with_the_dropped_field_is_refused(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    tarball = _repack_with_raw_qc(out, {"page": 1, "cost_estimate_usd": 0.01})
    _refused(out, _repo(tmp_path, tarball), "cost_estimate_usd")


def test_a_malformed_tag_is_refused(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    repo = _repo(tmp_path, out / f"intermediates-{TAG}.tar.gz")
    _refused(out, repo, "vX.Y.Z", tag="1.2.3")


def test_an_archive_packed_under_another_label_is_refused(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    repo = _repo(tmp_path, out / f"intermediates-{TAG}.tar.gz")
    _refused(out, repo, "intermediates-v9.9.9.tar.gz", tag="v9.9.9")


def test_a_failed_upload_fails(tmp_path: Path) -> None:
    out = _pack(tmp_path)
    repo = _repo(tmp_path, out / f"intermediates-{TAG}.tar.gz")
    assert release_intermediates.release(TAG, out, repo, run=lambda argv: 1) == 1


def test_main_wires_the_default_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _pack(tmp_path)
    repo = _repo(tmp_path, out / f"intermediates-{TAG}.tar.gz")
    runner = Runner()
    monkeypatch.setattr(release_intermediates, "run_upload", runner)
    rc = release_intermediates.main(["--tag", TAG, "--dir", str(out), "--root", str(repo)])
    assert rc == 0 and runner.calls[0][:4] == ["gh", "release", "upload", TAG]
