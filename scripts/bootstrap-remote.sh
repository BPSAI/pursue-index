#!/usr/bin/env bash
# scripts/bootstrap-remote.sh — Ensure bpsai-pair is available in remote sessions
#
# Called by SessionStart hook in .claude/settings.json.
# Idempotent: skips if bpsai-pair is already on PATH and functional.
#
# What this does:
#   1. Checks if bpsai-pair is available and working
#   2. If not, installs it with known-good dependency set
#   3. Runs bpsai-pair status to prime context and verify functionality
#   4. On failure: sets BPSAI_ENFORCEMENT=none env var and logs to audit trail
#
# Why --no-deps + explicit deps:
#   Full `pip install bpsai-pair` fails in containerized environments because
#   transitive deps (toggl, slumber) can't build wheels due to setuptools
#   install_layout incompatibility. The CLI only needs a subset of deps
#   for enforcement, task lifecycle, and telemetry.

set -euo pipefail

# Pin to exact version — prevents supply chain attacks from auto-installing
# compromised future releases. Update this when upgrading bpsai-pair.
PINNED_VERSION="2.21.0"

# Core runtime deps — the minimum set for CLI enforcement commands.
CORE_DEPS=(typer click rich tiktoken pyyaml)

AUDIT_LOG=".paircoder/telemetry/bootstrap_audit.jsonl"

# -- Helpers ------------------------------------------------------------------

_log_failure() {
    local reason="$1"
    local timestamp
    timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "unknown")"
    echo "[bootstrap] WARNING: ${reason}"

    # Write audit log entry (append, create dir if needed)
    mkdir -p "$(dirname "${AUDIT_LOG}")" 2>/dev/null || true
    printf '{"event":"bootstrap_failure","reason":"%s","timestamp":"%s","enforcement":"none"}\n' \
        "${reason}" "${timestamp}" >> "${AUDIT_LOG}" 2>/dev/null || true

    # Signal to downstream hooks that enforcement is unavailable
    export BPSAI_ENFORCEMENT=none
    exit 1
}

# -- 1. Check if already available -------------------------------------------

if command -v bpsai-pair >/dev/null 2>&1; then
    if bpsai-pair --version >/dev/null 2>&1; then
        # Already installed and functional — nothing to do
        exit 0
    fi
fi

# -- 2. Install bpsai-pair + core deps ---------------------------------------

echo "[bootstrap] Installing bpsai-pair for remote session enforcement..."

# Install the wheel without transitive deps (avoids toggl/slumber build failures)
pip install "bpsai-pair==${PINNED_VERSION}" --no-deps --quiet 2>/dev/null || {
    _log_failure "pip install bpsai-pair failed"
}

# Install the core runtime deps needed for CLI commands
pip install "${CORE_DEPS[@]}" --quiet 2>/dev/null || {
    _log_failure "pip install core deps failed"
}

# -- 3. Verify it works ------------------------------------------------------

if bpsai-pair --version >/dev/null 2>&1; then
    echo "[bootstrap] bpsai-pair $(bpsai-pair --version 2>&1) ready."
else
    _log_failure "bpsai-pair installed but not functional"
fi

# -- 4. Prime context --------------------------------------------------------

# Run status to load .paircoder context
bpsai-pair status >/dev/null 2>&1 || true
