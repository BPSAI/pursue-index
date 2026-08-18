"""Release-path defaults must survive the scaffolding untracking (index #112).

Two regressions this locks down, both found after #112/#113:

1. Tranche-diff receipts are a permanent record — the artifact `ingest approve`
   checks bytes against. Producer and consumer both defaulted to a
   directory that #112 added to `.gitignore`. Writing receipts into
   an ignored directory loses them silently: `git add -A` skips them and a
   fresh checkout cannot approve the tranche from the defaults.

2. `ingest_release_videos.py` documents `--env <path>` as how the operator
   supplies configuration, but `read_env_file` returns a dict and never updates
   the process environment — so a module-level default derived from `settings`
   cannot see it, and A/V bytes would stage under `./data` instead of the
   configured NAS root, silently leaving the NAS durability tier unwritten.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _is_git_ignored(path: Path) -> bool:
    """True when git would refuse to track files at this path."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_pursue_script_{name}", _REPO_ROOT / "scripts" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tranche_diff_writes_receipts_to_a_tracked_directory() -> None:
    """The producer must not default into an ignored tree."""
    out_dir = Path(_load_script("tranche_diff").DEFAULT_OUT_DIR)

    assert not _is_git_ignored(out_dir), (
        f"tranche_diff.py writes receipts to {out_dir}, which git ignores — "
        "they would be silently dropped by `git add -A`"
    )


def test_ingest_cli_reads_receipts_from_a_tracked_directory() -> None:
    """The consumer must look where the producer writes, and both must be tracked."""
    from pursue_index.cli.ingest_cli import DEFAULT_DIFF_DIR

    assert not _is_git_ignored(DEFAULT_DIFF_DIR), (
        f"ingest approve/run reads receipts from {DEFAULT_DIFF_DIR}, which git "
        "ignores — a fresh checkout has no artifact to approve against"
    )


def test_producer_and_consumer_agree_on_the_receipt_directory() -> None:
    from pursue_index.cli.ingest_cli import DEFAULT_DIFF_DIR

    produced = Path(_load_script("tranche_diff").DEFAULT_OUT_DIR).resolve()

    assert produced == Path(DEFAULT_DIFF_DIR).resolve(), (
        f"tranche_diff.py writes to {produced} but ingest approve/run reads "
        f"{DEFAULT_DIFF_DIR} — approval would not find the receipt"
    )


def test_video_nas_default_follows_data_root_from_the_supplied_env_file(
    tmp_path: Path,
) -> None:
    """`--env` must actually select the NAS root, not just load credentials.

    `read_env_file` returns a dict; it never exports into the process
    environment. A default resolved at import time therefore cannot see it.
    """
    module = _load_script("ingest_release_videos")

    nas_root = tmp_path / "nas-root"
    env_file = tmp_path / "opsec.env"
    env_file.write_text(
        f"PURSUE_DATA_ROOT={nas_root}\nR2_ACCESS_KEY_ID=ak\nR2_SECRET_ACCESS_KEY=sk\n",
        encoding="utf-8",
    )

    resolved = module.resolve_nas_dir(nas_arg=None, env=module.read_env_file(env_file))

    assert nas_root in Path(resolved).parents or Path(resolved) == nas_root, (
        f"--env supplied PURSUE_DATA_ROOT={nas_root} but the NAS dir resolved to "
        f"{resolved}; A/V bytes would stage outside the configured data root"
    )


def test_explicit_nas_flag_still_wins_over_the_env_file(tmp_path: Path) -> None:
    module = _load_script("ingest_release_videos")

    explicit = tmp_path / "explicit-target"
    env = {"PURSUE_DATA_ROOT": str(tmp_path / "from-env")}

    assert Path(module.resolve_nas_dir(nas_arg=explicit, env=env)) == explicit


def test_nas_default_falls_back_to_settings_when_env_file_is_silent() -> None:
    """No PURSUE_DATA_ROOT in the env file → the configured settings root."""
    from pursue_index.config import settings

    module = _load_script("ingest_release_videos")
    resolved = Path(module.resolve_nas_dir(nas_arg=None, env={}))

    assert Path(settings.data_root) in resolved.parents or resolved == Path(
        settings.data_root
    ), f"expected a path under settings.data_root, got {resolved}"


@pytest.mark.parametrize("suffix", [".mdx"])
def test_path_guard_covers_renderable_content_sources(suffix: str) -> None:
    """Renderable MDX under web/src/content publishes the same way .astro does."""
    from tests.unit.test_no_hardcoded_data_paths import _WEB_SOURCE_SUFFIXES

    assert suffix in _WEB_SOURCE_SUFFIXES
