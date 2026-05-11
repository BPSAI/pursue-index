#!/usr/bin/env bash
# Bootstrap a dev environment on a local workstation with NAS-mounted data.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

uv venv
# shellcheck disable=SC1091
source .venv/bin/activate

uv pip install -e ".[dev]"

if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Created .env from .env.example — edit before running pipeline."
fi

mkdir -p data/{manifests,pdfs,ocr,inspect,logs}

echo
echo "Bootstrap complete. Next steps:"
echo "  1. Edit .env (especially PURSUE_DATA_ROOT to point at the NAS)."
echo "  2. make db-up                     # start local Postgres"
echo "  3. pursue scrape inspect          # capture rendered DOM for selector tuning"
echo "  4. pursue scrape run              # build the release_01 manifest"
