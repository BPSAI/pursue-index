# Interpreter for repo scripts. Bare `python` resolves to whichever venv is
# active in the caller's shell; these targets depend on this repo's deps, so
# default to the repo venv. Override with `make PYTHON=... <target>`.
PYTHON ?= .venv/bin/python

# Fail closed: every recipe line runs under bash with errexit + pipefail, so a
# builder piped through `| tail` fails the target when the builder fails
# (plain /bin/sh reports only tail's status). A step whose failure is meant
# to be tolerated must say so explicitly in its recipe.
SHELL := /bin/bash
.SHELLFLAGS := -eo pipefail -c
# .SHELLFLAGS needs GNU make >= 3.82 (which also added the `oneshell`
# feature); older makes ignore it silently, so refuse to run there.
ifeq ($(filter oneshell,$(.FEATURES)),)
$(error GNU make >= 3.82 is required (.SHELLFLAGS); this is $(MAKE_VERSION))
endif

.PHONY: install install-dev scrape-inspect scrape download ocr ingest serve \
        test lint typecheck fmt db-up db-down clean

# ---- setup ----
install:
	uv venv && . .venv/bin/activate && uv pip install -e .

install-dev:
	uv venv && . .venv/bin/activate && uv pip install -e ".[dev]"

# ---- pipeline shortcuts ----
scrape-inspect:
	pursue scrape inspect --out data/inspect/

scrape:
	pursue scrape run --pages all --out data/manifests/release_01.json

download:
	pursue download run --manifest data/manifests/release_01.json

ocr:
	pursue ocr run --manifest data/manifests/release_01.json

ingest:
	pursue index ingest --manifest data/manifests/release_01.json

serve:
	pursue serve

# ---- dev quality ----
test:
	$(PYTHON) -m pytest

lint:
	ruff check src tests

typecheck:
	mypy src

fmt:
	ruff format src tests
	ruff check --fix src tests

# ---- infra ----
db-up:
	docker compose up -d postgres

db-down:
	docker compose down

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +

# ---- Sprint 4n: release runbook automation ----
# Codifies the site release checklist (docs/runbooks/ship-tranche.md).
# `make ship-ready` runs the full deterministic-AC chain pre-commit.

.PHONY: ship-ready
# Order matters: astro-build BEFORE test/gate-mirror so test_dist_dir_exists +
# test_card_page_coverage can see the freshly-built dist tree. `test` is here
# because no CI job runs the unit suite; gate-mirror then mirrors release-gate.
# (Caught 2026-05-22 on a clean rebuild — those integration tests
# rely on web/dist being current.)
#
# build-commit runs before any builder and records the commit whose code builds
# the release. stamp writes data/build-stamp.json after the last data write
# (snapshot-rotate), naming that commit. The stamp is then required, and its
# commit must be on the published branch, so every release cites code anyone
# can check out.
ship-ready: release-completeness build-commit rebuild-derivatives registry-root snapshot-rotate stamp astro-build asset-budget test gate-mirror arch-check staleness
	@$(PYTHON) scripts/build_stamp.py verify --root . --require --public-ref '$(PUBLIC_REF)'
	@echo ""
	@echo "ship-ready: ALL GATES PASSED. Safe to commit."
	@echo "  next: git add -A && git commit -m '...' && git push origin feature-branch && open PR to main"

# ---- build stamp ----
# The published branch. A release's builder commit must already be on it, so
# the stamp cites code that anyone can fetch and rebuild from.
# Fixed: `override` ignores a PUBLIC_REF given on the command line or in the
# environment, so the publication check cannot be pointed at another ref.
override PUBLIC_REF := origin/main
# Code paths: a change here, committed or not, is code the stamp would not cite.
# The builders, and the site code and build config. The JSON under web/src/data
# is excluded: it is stamped data that the build writes. The code beside it
# (manifest-loader.ts, types.ts) stays checked.
STAMP_CODE_PATHS := src scripts web/scripts web/src ':(exclude,glob)web/src/data/**/*.json' \
	web/package.json web/package-lock.json web/astro.config.mjs Makefile pyproject.toml
# Recorded inside .git (never tracked, never published).
BUILT_WITH = $$(git rev-parse --git-path pursue-build-commit)
# Shell checks that fail closed: if git itself fails, the check fails (an empty
# capture from a failed git must not read as "clean").
# No tracked change and no untracked file under the code paths:
STAMP_CODE_CLEAN = out=$$(git status --porcelain --untracked-files=all -- $(STAMP_CODE_PATHS)) \
	&& test -z "$$out"
# Gitignored files under the code paths can still be imported (a stray
# scripts/x.py shadows a real module). Bytecode caches and egg-info are the only
# ignored files allowed there.
STAMP_NO_IGNORED_CODE = ign=$$(git ls-files --others --ignored --exclude-standard -- $(STAMP_CODE_PATHS)) \
	&& test -z "$$(printf '%s\n' "$$ign" | grep -vE '^$$|(^|/)__pycache__/|\.egg-info/' || true)"

.PHONY: build-commit stamp
build-commit:
	@$(STAMP_CODE_CLEAN) \
		|| { echo "build-commit: uncommitted code under $(STAMP_CODE_PATHS)" >&2; exit 1; }
	@$(STAMP_NO_IGNORED_CODE) \
		|| { echo "build-commit: gitignored files under the code paths" >&2; exit 1; }
	@git merge-base --is-ancestor HEAD '$(PUBLIC_REF)' \
		|| { echo "build-commit: HEAD is not on $(PUBLIC_REF); build from published code" >&2; exit 1; }
	@git rev-parse HEAD > "$(BUILT_WITH)"
	@echo "build-commit: building with $$(git rev-parse --short HEAD)"

stamp:
	@test -f "$(BUILT_WITH)" || { echo "stamp: no build-commit recorded" >&2; exit 1; }
	@test "$$(cat "$(BUILT_WITH)")" = "$$(git rev-parse HEAD)" \
		|| { echo "stamp: HEAD moved since build-commit" >&2; exit 1; }
	@$(STAMP_CODE_CLEAN) \
		|| { echo "stamp: code changed during the build" >&2; exit 1; }
	@$(STAMP_NO_IGNORED_CODE) \
		|| { echo "stamp: gitignored files appeared under the code paths" >&2; exit 1; }
	@$(PYTHON) scripts/build_stamp.py write --root . --builder-commit "$$(cat "$(BUILT_WITH)")"

# First prerequisite of ship-ready: refuse a release before spending build time
# on it when an AUD card has no transcript, a VID/AUD card has no registered
# bytes, or a transcript is channel-duplicated. Repo + data root only.
.PHONY: release-completeness
release-completeness:
	@$(PYTHON) scripts/check_release_completeness.py

.PHONY: asset-budget
# Fail-closed static-asset size gate (mirrors release-gate steps 4d + 6c).
# Workers refuses any single static asset over 25 MiB; every file under
# web/public and the built web/dist must be <= 24 MiB, with chunk manifests
# matching their parts. Runs after astro-build so web/dist is current.
asset-budget:
	$(PYTHON) scripts/check_asset_budget.py

.PHONY: gate-mirror
# Local mirror of CI release-gate checks: snapshot mirror coverage, finds citations,
# finds validator, card page coverage, alias destinations, derived payload coverage.
gate-mirror:
	$(PYTHON) -m pytest tests/unit/test_snapshot_mirror_coverage.py \
	       tests/unit/test_finds_citations.py \
	       tests/unit/test_finds_validator.py \
	       tests/integration/test_card_page_coverage.py \
	       tests/integration/test_alias_destinations.py \
	       tests/integration/test_derived_payload_coverage.py
	@# Mirrors release-gate step 4h: fail-closed, no downgrade switch.
	$(PYTHON) scripts/build_qc_coverage.py --out "$$(mktemp -t qc-coverage.XXXXXX.json)"

.PHONY: staleness
staleness:
	@$(PYTHON) scripts/runbook_staleness_check.py

.PHONY: verify-deploy
verify-deploy:
	@$(PYTHON) scripts/runbook_verify_deploy.py

# Passed to the builders that guard against a shrinking corpus (pages.json,
# embed_index.json). Empty by default: a shrink fails the target. To accept one
# on purpose (audited in data/audit-log.jsonl):
#   make rebuild-derivatives SHRINK_ARGS='--allow-shrink --reason "why"'
SHRINK_ARGS ?=

.PHONY: rebuild-derivatives
rebuild-derivatives:
	@echo "==> Rebuild derivatives (mirrors, cards-summary, byte-history, csv-archive, pages.json, llms.txt, qc-coverage, OG images)"
	@cp data/manifests/latest.json web/src/data/manifest.json
	@# The Worker resolves /card/<old_id> renames from the ASSETS copy, not
	@# data/card-aliases.json (where the ingest gate appends them).
	@cp data/card-aliases.json web/public/data/card-aliases.json
	@cd web && node scripts/build_byte_history.mjs > /dev/null
	@cd web && node scripts/build_cards_summary.mjs > /dev/null
	@cd web && node scripts/build_csv_archive.mjs > /dev/null
	@# build_search_data refuses a shrinking corpus (exit 1, ids on stderr). A
	@# bare `| tail -1` would report tail's status and hide the ids, so capture
	@# the output, fail on the builder's own status, and show only the summary
	@# line on success.
	@out=$$($(PYTHON) scripts/build_search_data.py $(SHRINK_ARGS) 2>&1) || { echo "$$out"; exit 1; }; echo "$$out" | tail -1
	@# LS1.4 superseded build_llms_txt.mjs with the Python generator, which is
	@# what release-gate step 4b checks (`build_llms_txt.py --check`). The .mjs
	@# emits no provenance line, so leaving it here silently reverted the
	@# gate-required output and reddened CI on every release that ran the
	@# generator before `make ship-ready`, exactly as the runbook said to.
	@# The `| tail -1` lines below fail the target when the builder fails
	@# (pipefail, see SHELL/.SHELLFLAGS at the top).
	@$(PYTHON) scripts/build_llms_txt.py 2>&1 | tail -1
	@$(PYTHON) scripts/build_pages_cleaned.py 2>&1 | tail -1
	@$(PYTHON) scripts/build_photo_card_index.py 2>&1 | tail -1
	@$(PYTHON) scripts/build_video_card_index.py 2>&1 | tail -1
	@$(PYTHON) scripts/build_finds_og_images.py 2>&1 | tail -1
	@# QC status for every distinct card, from the manifest, the clean-QC
	@# bundle, pages.json and the image-observations index. Runs after
	@# build_search_data so it reads the current pages.json. No `| tail`: a
	@# failing builder must fail the target.
	@$(PYTHON) scripts/build_qc_coverage.py
	@# Derived retrieval/browse payloads that feed /chat, /search, /atlas and
	@# the gallery. These generators worked but nothing invoked them, so the
	@# deployed embed_index.json / atlas-layout.json / video-posters tracked
	@# the manifest only when someone remembered to run them by hand.
	@#
	@# No `| tail` here: piping masks the exit code, and a builder that exits
	@# non-zero must fail the target rather than leave a stale payload behind.
	@# Their output is a line or two anyway.
	@#
	@# Order is load-bearing. atlas runs LAST because it is the one with
	@# optional imports (the projection stack) and so the one most likely to
	@# be missing a dependency; embed and posters must have already landed
	@# when it does, or an atlas that cannot import leaves them unbuilt too.
	@# embed precedes atlas because atlas projects the embed index.
	@#
	@# Requires the NAS embed root + r2-mirror (present in the operator ship
	@# env; same precondition as embed above).
	@echo "==> Propagate derived payloads (embed / posters / atlas)"
	@$(PYTHON) scripts/build_embed_data.py $(SHRINK_ARGS)
	@# The Worker's retrieval text (data/retrieve/): pages.json cut to what
	@# /api/retrieve reads, sharded in embed_index row order. Needs both of
	@# them current, so it runs right after embed; committed files only.
	@$(PYTHON) scripts/build_retrieve_rows.py
	@$(PYTHON) scripts/build_video_posters.py
	@$(PYTHON) scripts/build_atlas_layout.py
	@# Catch-all: split any web/public/data payload still over the 24 MiB
	@# static-asset budget (the builders above already write through the
	@# chunk writer; this covers any other generator). `asset-budget` is
	@# what fails an oversize tree.
	@$(PYTHON) scripts/chunk_public_assets.py

.PHONY: registry-root
registry-root:
	@echo "==> Recompute registry-root"
	@$(PYTHON) scripts/registry_root.py \
		--registry data/asset-bytes-registry.jsonl \
		--root data/registry-root.txt \
		--manifest data/registry-root-manifest.txt

.PHONY: snapshot-rotate
snapshot-rotate:
	@echo "==> Rotate manifest snapshot (only if csv_sha differs from latest indexed)"
	@$(PYTHON) scripts/runbook_snapshot_rotate.py

.PHONY: arch-check
arch-check:
	@echo "==> Arch check (modified .py source files)"
	@# Advisory by design: a finding is printed, not fatal. Under pipefail
	@# that has to be explicit, as does "no modified files" (grep exits 1).
	@modified=$$(git diff --name-only HEAD | { grep -E '^(src|scripts)/.*\.py$$' || true; } | sed -n '1,20p'); \
	if [ -n "$$modified" ]; then \
		for f in $$modified; do \
			bpsai-pair arch check "$$f" 2>&1 | tail -3 \
				|| echo "  arch check exited non-zero for $$f (advisory, not blocking)"; \
		done; \
	else \
		echo "  (no modified .py source files to check)"; \
	fi

.PHONY: astro-build
astro-build:
	@echo "==> Astro build"
	@# Fails the target when the build fails; prints the full build output
	@# in that case, only the summary tail on success.
	@cd web && { out=$$(npm run build 2>&1) || { echo "$$out"; exit 1; }; echo "$$out" | tail -3; }

.PHONY: hooks-install
hooks-install:
	@bash scripts/install-hooks.sh

# The operator's local display-date approval UI (port 5555 by default):
#   make dates-ui [DATES_UI_ARGS='--port 5556 --no-browser']
.PHONY: dates-ui
dates-ui:
	$(PYTHON) scripts/curate_dates_ui.py $(DATES_UI_ARGS)

# Pin /removed preservation copies into the integrity layer (operator-run,
# needs R2 credentials in the environment):
#   make pin-removed [PIN_REMOVED_ARGS=--dry-run]
.PHONY: pin-removed
pin-removed:
	$(PYTHON) scripts/r2_pin_removed.py $(PIN_REMOVED_ARGS)

# ---- Release artifacts ----
# Rebuild the published payloads from a release's intermediates asset alone
# (docs/intermediates.md):
#   make intermediates-check TARBALL=<path to .tar.gz> EXPECT=<sha256 from the release notes>
# (ALLOW_UNPINNED=1 in place of EXPECT accepts SHA256SUMS alone, which only
# catches corruption.)
.PHONY: intermediates-check
intermediates-check:
	@test -n "$(TARBALL)" || { echo "TARBALL=<intermediates-<tag>.tar.gz> is required" >&2; exit 2; }
	$(PYTHON) scripts/intermediates.py rebuild-check --tarball "$(TARBALL)" \
		$(if $(EXPECT),--expect-sha256 "$(EXPECT)") $(if $(ALLOW_UNPINNED),--allow-unpinned)

.PHONY: bundle-copy
bundle-copy:
	@if [ -z "$$PURSUE_DATA_ROOT" ]; then \
		echo "bundle-copy: PURSUE_DATA_ROOT not set"; \
		exit 1; \
	fi
	@nas_root="$$PURSUE_DATA_ROOT"; \
	v_dir=""; best=-1; \
	for d in "$$nas_root/curate/published"/v[0-9]*; do \
		n="$${d##*/v}"; \
		case "$$n" in ""|*[!0-9]*) continue;; esac; \
		if [ -d "$$d" ] && [ "$$n" -gt "$$best" ]; then best="$$n"; v_dir="$$d"; fi; \
	done; \
	if [ -z "$$v_dir" ]; then \
		echo "bundle-copy: no published version directories found in $$nas_root/curate/published"; \
		exit 1; \
	fi; \
	bundle="$$v_dir/clean-qc-bundle.json"; \
	if [ -f "$$bundle" ]; then \
		dest="$${BUNDLE_DEST:-web/public/data/clean-qc-bundle.json}"; \
		mkdir -p "$$(dirname "$$dest")"; \
		src_bytes=$$(wc -c < "$$bundle"); \
		cp "$$bundle" "$$dest"; \
		dest_bytes=$$(wc -c < "$$dest"); \
		echo "bundle-copy: copied $$bundle"; \
		echo "  source: $$src_bytes bytes"; \
		echo "  dest: $$dest_bytes bytes"; \
		exit 0; \
	fi; \
	echo "bundle-copy: clean-qc-bundle.json not found in $$v_dir"; \
	exit 1
