"""Image mirror hardening: scope check, publish file mode, Markdown escaping."""

from __future__ import annotations

import errno
import os
import stat

import pytest
import typer

from pursue_index.cli import storage_cli
from pursue_index.release import exclusive_publish
from pursue_index.release.exclusive_publish import PUBLISHED, publish_exclusive, sha256_file
from pursue_index.release.image_mirror import ImageMirrorPreflight, ImageMirrorReport
from pursue_index.release.image_mirror_render import (
    render_image_mirror_report,
    render_image_verify,
)

# --- (a) scope check is an explicit exit, not an assert -------------------


def test_missing_worklist_is_a_clean_exit_two():
    with pytest.raises(typer.Exit) as exc:
        storage_cli._require_worklist(None)
    assert exc.value.exit_code == 2
    assert storage_cli._require_worklist(storage_cli.Path("w.json")) == storage_cli.Path("w.json")


# --- (b) one file mode on both publish paths ------------------------------


def _staged(tmp_path, data=b"bytes"):
    tmp = tmp_path / ".stage.tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY, 0o600)  # mkstemp's mode
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return tmp


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_hard_link_publish_is_mode_0644(tmp_path):
    tmp = _staged(tmp_path)
    target = tmp_path / "t.jpg"
    assert publish_exclusive(tmp, target, sha256_file(tmp))[0] == PUBLISHED
    assert _mode(target) == 0o644


def test_copy_publish_is_mode_0644_whatever_the_umask(tmp_path, monkeypatch):
    def no_links(src, dst):
        raise OSError(errno.EPERM, "no hard links here")

    monkeypatch.setattr(exclusive_publish.os, "link", no_links)
    tmp = _staged(tmp_path)
    target = tmp_path / "t.jpg"
    old = os.umask(0o077)
    try:
        assert publish_exclusive(tmp, target, sha256_file(tmp))[0] == PUBLISHED
    finally:
        os.umask(old)
    assert _mode(target) == 0o644


# --- (c) Markdown renderers escape card_id and detail ---------------------


def test_report_renders_hostile_detail_inside_one_code_span():
    rep = ImageMirrorReport(results={"a`b|c": ("unsafe_source", "x` | `y\nz")})
    line = [ln for ln in render_image_mirror_report(rep).splitlines() if "— unsafe_source:" in ln]
    assert len(line) == 1  # a newline in the detail cannot start another line
    assert line[0].count("`") == 4 and "|" in line[0]


def test_verify_renders_hostile_detail_inside_one_code_span():
    pf = ImageMirrorPreflight(ok=False, details={"a`b": "why` | `now\n* injected"})
    out = render_image_verify(pf)
    line = [ln for ln in out.splitlines() if ln.startswith("* `")]
    assert len(line) == 1 and line[0].count("`") == 4 and "|" in line[0]
    assert "* injected" not in out.splitlines()
