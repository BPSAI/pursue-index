---
id: pursue-vision-augment
type: feature
status: superseded
created: 2026-05-10
superseded_at: 2026-05-25
priority: superseded
depends_on: []
---

# Superseded

This plan is superseded by the consolidated three-tier architecture
plan in pursue-opsec-staging:

  `findings/2026-05-25-vision-augmentation-and-image-observations-architecture.md`

The original single-tier framing here was structurally insufficient
to address the Zhang VLM error patterns discovered in Phase 2 direct
examination of the helicopter-case imagery (2026-05-25). The new
plan preserves the Tier 3 implementation guidance from this doc
(engine module shape, editorial bar, bring-up phases) in its
appendix; the architectural changes (Tier 1 work lives in pursue-
curate as a new `image-observations` suite; supersede-and-quarantine
policy replaces the original "purely additive" framing) live in
opsec for cross-project orchestration.

Operator orchestrates from opsec.
