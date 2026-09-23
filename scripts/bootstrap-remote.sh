#!/usr/bin/env bash
# scripts/bootstrap-remote.sh -- Install bpsai-pair into a fresh CC cloud session
#
# Called by the SessionStart hook in .claude/settings.json. CC fires
# SessionStart on EVERY session (local interactive, local headless via
# `claude -p`, cloud / Ultra Plan online sessions), so this script gates
# on CLAUDE_CODE_REMOTE (set automatically by CC in cloud sessions, per
# https://code.claude.com/docs/en/env-vars) to ensure it only runs where
# bpsai-pair is genuinely missing.
#
# Local sessions already have bpsai-pair installed on the operator's
# machine -- running an install over a fresh dev venv was the v2.25.6
# incident pattern. Cloud sessions start from a fresh remote env that
# does not have bpsai-pair, so installing it there preserves enforcement
# semantics when the operator hands off from local CC to Ultra Plan.
#
# Why --no-deps + explicit deps:
#   Full `pip install bpsai-pair` fails in containerized environments
#   because transitive deps (toggl, slumber) can't build wheels due to
#   setuptools install_layout incompatibility. The CLI only needs a
#   subset of deps for enforcement, task lifecycle, and telemetry.
#
# Behavior on failure:
#   - Loud banner on stderr (CC SessionStart shows stderr to the user)
#   - Append a structured audit entry to .paircoder/telemetry/bootstrap_audit.jsonl
#   - exit 1 (non-blocking per CC's SessionStart contract; the session
#     continues, but subsequent bpsai-pair-aware operations will fail
#     naturally and the banner tells the operator why)

set -euo pipefail

# Gate: only run in CC cloud sessions.
# CC sets CLAUDE_CODE_REMOTE=true automatically in cloud / Ultra Plan
# sessions but not in local sessions (interactive or headless `claude -p`
# for background agents). Canonical signal per the CC env-vars docs.
# Operators can force the bootstrap manually by setting
# PAIRCODER_BOOTSTRAP_FORCE=1 (e.g. for diagnostics, or to prime a CI
# runner that wasn't otherwise set up).
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ] \
        && [ -z "${PAIRCODER_BOOTSTRAP_FORCE:-}" ]; then
    # Local session -- bpsai-pair is the operator's responsibility.
    exit 0
fi

# Pin to exact version — prevents supply chain attacks from auto-installing
# compromised future releases. Maintained by the paircoder release/upgrade
# payload -- do not hand-edit; `bpsai-pair upgrade` overwrites this value
# from the current payload template.
PINNED_VERSION="2.49.8"

# Core runtime deps — the minimum set CLI startup needs to import without
# crashing. `bpsai_pair.commands.__init__` imports every subcommand module
# at load time, which transitively requires:
#   typer click rich   — Typer CLI framework (click is a typer dep but kept explicit)
#   pyyaml tiktoken    — config + token counting at startup
#   pydantic           — licensing.schema models loaded via commands/orchestrate
#   httpx              — commands/subscription module-level import
#   packaging          — telemetry/auto_archive.py + commands/upgrade_prompt.py,
#                        both run on EVERY mutating command via cli_startup.py's
#                        hooks (missing here previously meant a CC cloud-session
#                        bootstrap still lacked it even after pyproject declared it,
#                        and the pre-T1 hook's ImportError quieting then hid the gap)
#   platformdirs       — commands/doctor_editable_ack.py module-level import
#   tenacity           — gitops/retry.py, re-exported by gitops/__init__.py
# Verified empirically: a venv with just these can run `bpsai-pair --version`,
# `status`, and every hook command wired in `.claude/settings.json`.
# Drift guard: maintained by the paircoder release process against the
# CLI's own import graph -- do not hand-edit; kept in sync automatically
# by `bpsai-pair upgrade`.
#
# Exact-pinned (== not a range) -- same supply-chain rationale as
# PINNED_VERSION above: an unpinned array let every cloud session
# auto-install the LATEST release of each dep, undermining that
# rationale for everything BUT the wheel itself. Each pin must also
# Maintained by the paircoder release/upgrade payload alongside
# PINNED_VERSION above -- do not hand-edit.
CORE_DEPS=(typer==0.27.1 click==8.4.2 rich==15.0.0 tiktoken==0.13.0 pyyaml==6.0.3 pydantic==2.13.4 httpx==0.28.1 packaging==26.3 platformdirs==4.11.1 tenacity==9.1.4)

# Resolve the project root from THIS SCRIPT's location, never from the cwd.
# A cloud session with several repos selected starts with its working
# directory at the workspace parent, so a cwd-relative audit log is written
# outside the repo (or not at all) -- and the audit log is the only durable
# signal that a bootstrap ran and failed. Script-relative also keeps a manual
# `bash /path/to/repo/scripts/bootstrap-remote.sh` writing to that repo.
_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${_SCRIPT_DIR}/.." && pwd)"

AUDIT_LOG="${PROJECT_ROOT}/.paircoder/telemetry/bootstrap_audit.jsonl"

# -- Helpers ------------------------------------------------------------------

_audit_entry() {
    # Append a JSONL entry to the audit log without banner/exit.
    # Used for non-fatal events (context prime failure) and reused by
    # _log_failure for the install-failure path.
    local event="$1"
    local reason="$2"
    local timestamp
    timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "unknown")"
    mkdir -p "$(dirname "${AUDIT_LOG}")" 2>/dev/null || true
    printf '{"event":"%s","reason":"%s","timestamp":"%s"}\n' \
        "${event}" "${reason}" "${timestamp}" >> "${AUDIT_LOG}" 2>/dev/null || true
}

_log_failure() {
    local reason="$1"

    # Loud banner on stderr. CC SessionStart hooks cannot block
    # the session (exit 1 is non-blocking), so stderr is the only
    # operator-visible signal in the moment. The audit log entry below
    # persists for later triage. Banner deliberately verbose -- the
    # previous single-line WARNING was lost in noise during the
    # multi-month bootstrap-stale window before v2.25.6.
    {
        echo ""
        echo "========================================"
        echo "[bootstrap] BOOTSTRAP FAILED: ${reason}"
        echo "========================================"
        echo "[bootstrap] Session will continue, but bpsai-pair may be"
        echo "[bootstrap] unavailable. See ${AUDIT_LOG} for details."
    } >&2

    _audit_entry "bootstrap_failure" "${reason}"
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

# Run status to load .paircoder context. A failure here is not fatal --
# install succeeded, the CLI is functional, this command just primes
# cached state. Audit it quietly so future triage can correlate prime
# failures with downstream weirdness.
# Run from PROJECT_ROOT, not the cwd: in a multi-repo cloud session the cwd is
# the workspace parent, which has no .paircoder/ to prime -- `status` would fail
# there for a reason that has nothing to do with this repo's state.
(cd "${PROJECT_ROOT}" && bpsai-pair status >/dev/null 2>&1) \
    || _audit_entry "context_prime_failed" "bpsai-pair status returned non-zero"
