"""ship-ready packs the release's intermediates and pins them in the stamp, when
asked to; release-intermediates attaches them to the tag's Release.

``INTERMEDIATES_LABEL=vX.Y.Z`` makes ship-ready pack from the data root into a
directory outside the repository, rebuild-check the result, and pass the
tarball to ``build_stamp.py write`` and the closing ``verify``. Without the
label, ship-ready is unchanged.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = "/srv/pursue-data"
TARBALL = f"{DATA_ROOT}/release-assets/v1.2.3/intermediates-v1.2.3.tar.gz"


def _make(*args: str, data_root: str | None = DATA_ROOT) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("PURSUE_DATA_ROOT", "INTERMEDIATES_LABEL", "TAG")}
    if data_root is not None:
        env["PURSUE_DATA_ROOT"] = data_root
    return subprocess.run(["make", "-C", str(ROOT), *args, "PYTHON=python3"],
                          capture_output=True, text=True, timeout=60, env=env)


def _dry(*args: str, data_root: str | None = DATA_ROOT) -> list[str]:
    out = _make("-n", *args, data_root=data_root)
    assert out.returncode == 0, out.stderr
    # One entry per command: join backslash-continued recipe lines.
    text = out.stdout.replace("\\\n", " ")
    return [ln for ln in text.splitlines() if ln.strip()]


def _at(lines: list[str], needle: str) -> int:
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    assert hits, needle
    return hits[0]


def test_with_a_label_ship_ready_packs_checks_then_stamps_the_tarball() -> None:
    lines = _dry("ship-ready", "INTERMEDIATES_LABEL=v1.2.3")
    pack = _at(lines, "intermediates.py pack")
    check = _at(lines, "intermediates.py rebuild-check")
    stamp = _at(lines, "build_stamp.py write")
    # The data root is final once the derivatives are rebuilt; packing hangs
    # off stamp, so it also follows the site build.
    assert _at(lines, "build_atlas_layout.py") < _at(lines, "npm run build") < pack
    assert pack < check < stamp
    assert f'--data-root "{DATA_ROOT}"' in lines[pack]
    assert f'--out-dir "{DATA_ROOT}/release-assets/v1.2.3"' in lines[pack]
    assert '--label "v1.2.3"' in lines[pack]
    assert f'--tarball "{TARBALL}"' in lines[check]
    # Pinned to the SHA256SUMS the pack just wrote, never --allow-unpinned.
    assert "--expect-sha256" in lines[check] and "SHA256SUMS" in lines[check]
    assert "--allow-unpinned" not in lines[check]
    assert f'--intermediates "{TARBALL}"' in lines[stamp]
    last = [ln for ln in lines if "build_stamp.py" in ln][-1]
    assert "verify" in last and f'--intermediates "{TARBALL}"' in last


def test_without_a_label_ship_ready_is_unchanged() -> None:
    lines = _dry("ship-ready")
    assert not [ln for ln in lines if "intermediates.py" in ln]
    assert not [ln for ln in lines if "--intermediates" in ln]
    stamp = lines[_at(lines, "build_stamp.py write")]
    assert stamp.endswith('--builder-commit "$(cat "$(git rev-parse --git-path '
                          'pursue-build-commit)")"')


def test_a_label_is_checked_before_any_build_time_is_spent() -> None:
    lines = _dry("ship-ready", "INTERMEDIATES_LABEL=v1.2.3")
    assert _at(lines, "intermediates-label:") < _at(lines, "check_release_completeness.py")


def test_a_malformed_label_is_refused() -> None:
    for label in ("1.2.3", "v1.2", "v1.2.3-rc1", "v1.2.3/../x", "latest"):
        out = _make("intermediates-label", f"INTERMEDIATES_LABEL={label}")
        assert out.returncode != 0, label
        assert "INTERMEDIATES_LABEL" in out.stderr and "vX.Y.Z" in out.stderr, label


def test_a_label_is_tested_never_run(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    for label in (f"v1.2.3'; touch {marker}; '", f"$(touch {marker})", f"`touch {marker}`"):
        out = _make("intermediates-label", f"INTERMEDIATES_LABEL={label}")
        assert out.returncode != 0, label
        assert not marker.exists(), label
    out = _make("release-intermediates", f"TAG=v1.2.3'; touch {marker}; '")
    assert out.returncode != 0 and not marker.exists()


def test_a_label_without_a_data_root_is_refused() -> None:
    out = _make("intermediates-label", "INTERMEDIATES_LABEL=v1.2.3", data_root=None)
    assert out.returncode != 0
    assert "PURSUE_DATA_ROOT" in out.stderr


def test_a_well_formed_label_passes() -> None:
    out = _make("intermediates-label", "INTERMEDIATES_LABEL=v1.2.3")
    assert out.returncode == 0, out.stderr


def test_an_out_dir_inside_the_repository_is_refused() -> None:
    out = _make("intermediates-label", "INTERMEDIATES_LABEL=v1.2.3", data_root=str(ROOT))
    assert out.returncode != 0
    assert "outside the repository" in out.stderr


def test_release_intermediates_checks_sums_then_guards_then_uploads() -> None:
    lines = _dry("release-intermediates", "TAG=v0.0.0")
    sums = _at(lines, "sha256sum -c SHA256SUMS")
    guard = _at(lines, "release_intermediates.py")
    assert sums < guard
    assert f'cd "{DATA_ROOT}/release-assets/v0.0.0"' in lines[sums]
    assert '--tag "v0.0.0"' in lines[guard]
    assert f'--dir "{DATA_ROOT}/release-assets/v0.0.0"' in lines[guard]
    text = "\n".join(lines)
    # The upload is the guard's last act; the target itself never calls gh.
    assert "gh release" not in text and "--clobber" not in text


def test_release_intermediates_needs_a_well_formed_tag() -> None:
    for args in ((), ("TAG=1.2.3",)):
        out = _make("release-intermediates", *args)
        assert out.returncode != 0, args
        assert "TAG" in out.stderr and "vX.Y.Z" in out.stderr, args
