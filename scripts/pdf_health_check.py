"""6h cron sentinel: ping a single PDF and exit 0/1.

Mirror of ``scripts/poll_pursue.py`` for the PDF-fetch path. Lives
alongside it because they're invoked from the same workflow
(``.github/workflows/poll-pursue.yml``) and share the curl_cffi +
Chrome-TLS contract via ``pursue_index.scrape.csv_fetcher.http_get``.

The script is intentionally a thin shell — all the testable logic
(including the kv-format ``format_ok``/``format_fail`` helpers) lives
in ``pursue_index.scrape.pdf_health``. This file exists so the GH
Actions runner can invoke it directly without needing the full
``pursue`` CLI (typer + click + rich) installed; see
``requirements-poll.in`` for the minimal install list.

Output (stable kv format the workflow log can grep):

* ``pdf-health.ok url=<url> bytes=<n>``  -> exit 0
* ``pdf-health.fail url=<url> status=<n> error=<msg>``  -> exit 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make ``src/`` importable when running as ``python scripts/pdf_health_check.py``
# from the repo root (no install needed in the GH Actions runner).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.scrape import pdf_health  # noqa: E402

DEFAULT_MANIFEST_PATH = _REPO_ROOT / "data" / "manifests" / "latest.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Manifest path. Defaults to data/manifests/latest.json.",
    )
    args = parser.parse_args(argv)
    manifest_path: Path = args.manifest

    try:
        sentinel = pdf_health.pick_sentinel(manifest_path)
    except (FileNotFoundError, ValueError) as exc:
        # Silent green here would mask real problems (manifest never
        # built, all-VID manifest). Treat as failure. ``format_fail``
        # sanitizes the error string so multi-word messages don't
        # break log parsers.
        sentinel_fail = pdf_health.HealthFail(
            url="-",
            status=-1,
            error=f"sentinel:{type(exc).__name__}: {exc}",
        )
        print(pdf_health.format_fail(sentinel_fail), file=sys.stderr, flush=True)
        return 1

    result = pdf_health.check_pdf_health(str(sentinel.asset_url))
    if isinstance(result, pdf_health.HealthOk):
        print(pdf_health.format_ok(result), flush=True)
        return 0

    # HealthFail — emit on stderr so failures stay visible even if
    # stdout is consumed by a downstream pipe.
    print(pdf_health.format_fail(result), file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
