#!/usr/bin/env bash
# Install git hooks that enforce the release runbook gates locally.
#
# Wires the pre-commit hook to run `python scripts/runbook_staleness_check.py`
# (Phase 4 staleness grep) on every commit. Anything that adds stale-state
# prose (hardcoded card / page / agency counts, stale CSV URL references)
# blocks the commit with a clear pointer to the file:line:excerpt.
#
# Run once after `git clone`:
#
#   bash scripts/install-hooks.sh
#
# Or via the Makefile target:
#
#   make hooks-install
#
# Hooks are NOT versioned in git (.git/hooks/ is local-only by design), so
# every clone needs this re-run. CI doesn't need it — Phase 4 also runs as
# part of `make ship-ready` and as the verify-staleness GH Action.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
HOOK_PATH="${REPO_ROOT}/.git/hooks/pre-commit"

cat > "${HOOK_PATH}" <<'HOOK'
#!/usr/bin/env bash
# pursue-index pre-commit hook — Phase 4 staleness gate.
#
# Blocks commits that contain hardcoded state contradicting the current
# manifest. Installed by `scripts/install-hooks.sh`.
#
# Bypass (rare, audit trail):
#   git commit --no-verify -m "..."

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Only fire when the commit actually touches prose-bearing surfaces.
staged=$(git diff --cached --name-only \
  | grep -E '^(README\.md|\.paircoder/context/project\.md|web/src/(pages|components|content/finds|lib)/.*\.(astro|tsx|mdx|ts))$' \
  || true)

if [ -z "$staged" ]; then
  exit 0
fi

cd "${REPO_ROOT}"

if ! python scripts/runbook_staleness_check.py; then
  cat <<MSG

Commit blocked by Phase 4 staleness check.

Fix the flagged hits, OR bypass with:
  git commit --no-verify -m "..."

Bypassing is for emergencies only. Drift accumulates fast.
MSG
  exit 1
fi
HOOK

chmod +x "${HOOK_PATH}"
echo "installed: ${HOOK_PATH}"
echo "  bypass when needed: git commit --no-verify -m '...'"
