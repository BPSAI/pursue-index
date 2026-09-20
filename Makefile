# Interpreter for repo scripts. Bare `python` resolves to whichever venv is
# active in the caller's shell; these targets depend on this repo's deps, so
# default to the repo venv. Override with `make PYTHON=... <target>`.
PYTHON ?= .venv/bin/python

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
	pytest

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
# Codifies pursue-opsec-staging/runbooks/site-release-checklist.md.
# `make ship-ready` runs the full deterministic-AC chain pre-commit.

.PHONY: ship-ready
# Order matters: astro-build BEFORE gate-mirror so test_dist_dir_exists +
# test_card_page_coverage can see the freshly-built dist tree.
# (Caught 2026-05-22 on a clean rebuild — those integration tests
# rely on web/dist being current.)
ship-ready: release-completeness rebuild-derivatives registry-root snapshot-rotate astro-build gate-mirror arch-check staleness
	@echo ""
	@echo "ship-ready: ALL GATES PASSED. Safe to commit."
	@echo "  next: git add -A && git commit -m '...' && git push origin feature-branch && open PR to main"
	@echo ""

# First prerequisite of ship-ready: refuse a release before spending build time
# on it when an AUD card has no transcript, a VID/AUD card has no registered
# bytes, or a transcript is channel-duplicated. Repo + data root only.
.PHONY: release-completeness
release-completeness:
	@$(PYTHON) scripts/check_release_completeness.py

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
	@echo "==> Rebuild derivatives (mirror, cards-summary, byte-history, csv-archive, pages.json, llms.txt, OG images)"
	@cp data/manifests/latest.json web/src/data/manifest.json
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
	@$(PYTHON) scripts/build_llms_txt.py 2>&1 | tail -1
	@$(PYTHON) scripts/build_pages_cleaned.py 2>&1 | tail -1
	@$(PYTHON) scripts/build_photo_card_index.py 2>&1 | tail -1
	@$(PYTHON) scripts/build_video_card_index.py 2>&1 | tail -1
	@$(PYTHON) scripts/build_finds_og_images.py 2>&1 | tail -1
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
	@$(PYTHON) scripts/build_video_posters.py
	@$(PYTHON) scripts/build_atlas_layout.py

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
	@modified=$$(git diff --name-only HEAD | grep -E '^(src|scripts)/.*\.py$$' | head -20); \
	if [ -n "$$modified" ]; then \
		for f in $$modified; do bpsai-pair arch check "$$f" 2>&1 | tail -3; done; \
	else \
		echo "  (no modified .py source files to check)"; \
	fi

.PHONY: astro-build
astro-build:
	@echo "==> Astro build"
	@cd web && npm run build 2>&1 | tail -3

.PHONY: hooks-install
hooks-install:
	@bash scripts/install-hooks.sh

# ---- Release artifacts ----
.PHONY: bundle-copy
bundle-copy:
	@if [ -z "$$PURSUE_DATA_ROOT" ]; then \
		echo "bundle-copy: PURSUE_DATA_ROOT not set"; \
		exit 1; \
	fi
	@nas_root="$$PURSUE_DATA_ROOT"; \
	for v_dir in "$$nas_root/published"/v*; do \
		if [ ! -d "$$v_dir" ]; then \
			echo "bundle-copy: no published version directories found in $$nas_root/published"; \
			exit 1; \
		fi; \
		bundle="$$v_dir/clean-qc-bundle.json"; \
		if [ -f "$$bundle" ]; then \
			dest="web/public/data/clean-qc-bundle.json"; \
			mkdir -p "$$(dirname "$$dest")"; \
			src_bytes=$$(wc -c < "$$bundle"); \
			cp "$$bundle" "$$dest"; \
			dest_bytes=$$(wc -c < "$$dest"); \
			echo "bundle-copy: copied $$bundle"; \
			echo "  source: $$src_bytes bytes"; \
			echo "  dest: $$dest_bytes bytes"; \
			exit 0; \
		fi; \
	done; \
	echo "bundle-copy: clean-qc-bundle.json not found in $$nas_root/published/v*/"; \
	exit 1
