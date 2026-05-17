"""Integration tests for ``scripts/wayback_save.py``.

These tests monkey-patch ``urllib.request.urlopen`` and exercise the
top-level ``main()`` and ``_collect_urls()`` paths end-to-end. They
cover the bug findings raised in Codex / nayru / vaivora review of
PR #65:

* H1 — ``--sitemap`` accepts a https:// URL string without Path-collapse.
* H3 — per-URL failures (429/timeout/404) do NOT exit 1.
* H5 — origin HEAD check skips dead URLs before the Wayback submission.
* main() smoke: no-URLs branch, no-plan branch, mixed 200/429 outcome.

Pure unit tests for the helpers live in ``test_wayback_save.py``.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import wayback_save  # noqa: E402


# --- shared fakes ----------------------------------------------------


_SITEMAP_INDEX_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://pursueindex.com/sitemap-0.xml</loc></sitemap>
</sitemapindex>
""".strip()

_SITEMAP_LEAF_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://pursueindex.com/</loc></url>
  <url><loc>https://pursueindex.com/about</loc></url>
</urlset>
""".strip()


def _fake_resp(body: bytes, status: int = 200) -> MagicMock:
    """Build a context-managed urlopen() return value."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.status = status
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: None
    return resp


# --- H1: --sitemap accepts a https:// URL string ----------------------


def test_collect_urls_accepts_https_sitemap_arg_without_path_collapse() -> None:
    """H1 (vaivora P1): ``--sitemap https://...`` must not collapse to ``https:/...``.

    The prior version typed args.sitemap as Path, so argparse silently
    rewrote ``https://`` to ``https:/`` (Path normalization). The fix
    changes the arg type to str so the URL survives intact and
    ``_read_sitemap_text`` takes its https branch.
    """
    calls: list[str] = []

    def fake_urlopen(url_or_req: Any, timeout: float = 30):  # noqa: ANN401, ARG001
        url = url_or_req if isinstance(url_or_req, str) else url_or_req.full_url
        calls.append(url)
        if url.endswith("sitemap-index.xml"):
            return _fake_resp(_SITEMAP_INDEX_BODY.encode("utf-8"))
        return _fake_resp(_SITEMAP_LEAF_BODY.encode("utf-8"))

    args = wayback_save._build_parser().parse_args(
        ["--sitemap", "https://pursueindex.com/sitemap-index.xml"]
    )
    with patch.object(wayback_save.urllib.request, "urlopen", side_effect=fake_urlopen):
        urls = wayback_save._collect_urls(args)

    # The URL must reach urlopen with both slashes intact.
    assert calls, "urlopen was not called — args.sitemap likely still typed as Path"
    assert calls[0] == "https://pursueindex.com/sitemap-index.xml"
    # Sanity: the second call expanded the child sitemap.
    assert "https://pursueindex.com/sitemap-0.xml" in calls
    assert "https://pursueindex.com/" in urls
    assert "https://pursueindex.com/about" in urls


# --- H3: per-URL failures do not fail the workflow --------------------


def test_run_plan_per_url_failures_return_exit_zero(tmp_path: Path) -> None:
    """H3 (Codex P1): mixed 200/429 results in exit 0; 200 entry persisted.

    Per-URL failures (429, timeout, 404) are expected and recoverable on
    the next run. Reserving exit 1 for catastrophic failure means the
    workflow's ``Commit updated wayback-history.json`` step still runs
    and freshness state persists even when one URL throttles.
    """
    history_path = tmp_path / "wayback-history.json"
    history_path.write_text("{}", encoding="utf-8")

    submit_calls: list[str] = []

    def fake_submit(save_url: str, *, timeout: float = 60) -> int:  # noqa: ARG001
        submit_calls.append(save_url)
        if "/about" in save_url:
            return 429  # throttled
        return 200

    args = wayback_save._build_parser().parse_args(
        [
            "--url",
            "https://pursueindex.com/",
            "--url",
            "https://pursueindex.com/about",
            "--history",
            str(history_path),
            "--delay-seconds",
            "0",  # speed up the test — no need to sleep between submissions
            "--skip-origin-check",  # H5: bypass the origin HEAD probe
        ]
    )

    with patch.object(wayback_save, "_submit_save", side_effect=fake_submit):
        exit_code = wayback_save._main_with_args(args)

    assert exit_code == 0, "Per-URL 429 must NOT mark the run as failed"
    assert len(submit_calls) == 2
    # The 200 URL is persisted in history; the 429 URL is not, so it
    # gets retried on the next run when its freshness window is naturally
    # absent.
    saved = json.loads(history_path.read_text(encoding="utf-8"))
    assert "https://pursueindex.com/" in saved
    assert "https://pursueindex.com/about" not in saved


def test_run_plan_emits_warning_annotation_for_failures(
    tmp_path: Path, capsys
) -> None:
    """H3: per-URL failures surface as ``::warning::`` GH Actions annotations.

    Exit 0 + a warning annotation means the run appears green but the
    operator still sees the throttled URL in the run summary. Without
    the annotation, partial failures would be silent.
    """
    history_path = tmp_path / "wayback-history.json"
    history_path.write_text("{}", encoding="utf-8")

    def fake_submit(save_url: str, *, timeout: float = 60) -> int:  # noqa: ARG001
        return 429

    args = wayback_save._build_parser().parse_args(
        [
            "--url",
            "https://pursueindex.com/about",
            "--history",
            str(history_path),
            "--delay-seconds",
            "0",
            "--skip-origin-check",
        ]
    )
    with patch.object(wayback_save, "_submit_save", side_effect=fake_submit):
        exit_code = wayback_save._main_with_args(args)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "::warning::" in captured.out
    assert "429" in captured.out


# --- H5: origin HEAD check wires `should_skip_origin_status` ---------


def test_run_plan_skips_dead_origin_urls(tmp_path: Path) -> None:
    """H5 (laverna): a 404-at-origin URL is not submitted to Wayback.

    The script HEADs the origin URL first; if the origin returns 4xx/5xx,
    ``should_skip_origin_status`` is True and we skip the Wayback POST.
    This avoids filling Wayback's queue with dead pointers and surfaces
    the dead-URL set in the run log for operator triage.
    """
    history_path = tmp_path / "wayback-history.json"
    history_path.write_text("{}", encoding="utf-8")

    head_responses: dict[str, int] = {
        "https://pursueindex.com/": 200,
        "https://pursueindex.com/dead-link": 404,
    }
    submit_calls: list[str] = []

    def fake_head_status(url: str, *, timeout: float = 10) -> int:  # noqa: ARG001
        return head_responses[url]

    def fake_submit(save_url: str, *, timeout: float = 60) -> int:  # noqa: ARG001
        submit_calls.append(save_url)
        return 200

    args = wayback_save._build_parser().parse_args(
        [
            "--url",
            "https://pursueindex.com/",
            "--url",
            "https://pursueindex.com/dead-link",
            "--history",
            str(history_path),
            "--delay-seconds",
            "0",
        ]
    )

    with patch.object(wayback_save, "_head_origin_status", side_effect=fake_head_status):
        with patch.object(wayback_save, "_submit_save", side_effect=fake_submit):
            exit_code = wayback_save._main_with_args(args)

    assert exit_code == 0
    # Only the live URL was submitted to Wayback; the 404 was skipped.
    assert submit_calls == ["https://web.archive.org/save/https://pursueindex.com/"]


def test_skip_origin_check_flag_bypasses_head(tmp_path: Path) -> None:
    """H5: ``--skip-origin-check`` skips the HEAD probe entirely.

    Operator escape hatch for cases like "save a known-removed URL
    before it's removed from Wayback too". When the flag is set, every
    URL in the plan is submitted to Wayback regardless of origin status.
    """
    history_path = tmp_path / "wayback-history.json"
    history_path.write_text("{}", encoding="utf-8")

    head_called: list[str] = []
    submit_calls: list[str] = []

    def fake_head_status(url: str, *, timeout: float = 10) -> int:  # noqa: ARG001
        head_called.append(url)
        return 404

    def fake_submit(save_url: str, *, timeout: float = 60) -> int:  # noqa: ARG001
        submit_calls.append(save_url)
        return 200

    args = wayback_save._build_parser().parse_args(
        [
            "--url",
            "https://pursueindex.com/dead-link",
            "--history",
            str(history_path),
            "--delay-seconds",
            "0",
            "--skip-origin-check",
        ]
    )

    with patch.object(wayback_save, "_head_origin_status", side_effect=fake_head_status):
        with patch.object(wayback_save, "_submit_save", side_effect=fake_submit):
            exit_code = wayback_save._main_with_args(args)

    assert exit_code == 0
    assert head_called == [], "HEAD probe must be bypassed under --skip-origin-check"
    assert len(submit_calls) == 1


# --- main() smoke paths ----------------------------------------------


def test_main_with_args_no_urls_exits_zero(tmp_path: Path) -> None:
    """main() with an empty sitemap exits 0 (no-op branch)."""
    history_path = tmp_path / "wayback-history.json"
    history_path.write_text("{}", encoding="utf-8")
    empty_sitemap = tmp_path / "sitemap.xml"
    empty_sitemap.write_text(
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>',
        encoding="utf-8",
    )
    args = wayback_save._build_parser().parse_args(
        [
            "--sitemap",
            str(empty_sitemap),
            "--history",
            str(history_path),
            "--delay-seconds",
            "0",
            "--skip-origin-check",
        ]
    )
    assert wayback_save._main_with_args(args) == 0


def test_main_with_args_no_plan_exits_zero(tmp_path: Path) -> None:
    """All URLs fresh -> plan is empty -> exit 0 without submitting."""
    history_path = tmp_path / "wayback-history.json"
    now = datetime.now(UTC)
    history_path.write_text(
        json.dumps(
            {
                "https://pursueindex.com/": now.isoformat(),
                "https://pursueindex.com/about": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    args = wayback_save._build_parser().parse_args(
        [
            "--url",
            "https://pursueindex.com/",
            "--url",
            "https://pursueindex.com/about",
            "--history",
            str(history_path),
            "--delay-seconds",
            "0",
            "--skip-origin-check",
        ]
    )
    with patch.object(wayback_save, "_submit_save") as submit_mock:
        exit_code = wayback_save._main_with_args(args)
    assert exit_code == 0
    submit_mock.assert_not_called()


# --- M-new: --max-urls cap end-to-end --------------------------------


def test_main_with_args_truncates_oversized_plan(
    tmp_path: Path, capsys
) -> None:
    """M-new: ``--max-urls`` truncates the plan and emits a warning.

    Run with 1500 distinct sitemap URLs and ``--max-urls 5`` so the
    assertion stays cheap; only 5 submissions should fire and the
    truncation must surface as a ``::warning::`` annotation.
    """
    history_path = tmp_path / "wayback-history.json"
    history_path.write_text("{}", encoding="utf-8")
    sitemap = tmp_path / "sitemap.xml"
    urls = "".join(
        f"<url><loc>https://pursueindex.com/p{i}</loc></url>" for i in range(1500)
    )
    sitemap.write_text(
        f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        encoding="utf-8",
    )

    submit_calls: list[str] = []

    def fake_submit(save_url: str, *, timeout: float = 60) -> int:  # noqa: ARG001
        submit_calls.append(save_url)
        return 200

    args = wayback_save._build_parser().parse_args(
        [
            "--sitemap",
            str(sitemap),
            "--history",
            str(history_path),
            "--delay-seconds",
            "0",
            "--max-urls",
            "5",
            "--skip-origin-check",
        ]
    )
    with patch.object(wayback_save, "_submit_save", side_effect=fake_submit):
        exit_code = wayback_save._main_with_args(args)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(submit_calls) == 5
    assert "::warning::" in captured.out
    assert "1500" in captured.out and "5" in captured.out
