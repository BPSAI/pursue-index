"""Tests for ``pursue_index.clean.qc.schema``.

Pins the verdict typing + the aggregate computation that turns a dict
of per-check verdicts into the ship-blocking signal used by the
runner and the methodology surface.
"""

from __future__ import annotations

import pytest

from pursue_index.clean.qc import schema


# --- aggregate counts ----------------------------------------------------


def test_aggregate_all_pass_returns_pass_with_zero_counts() -> None:
    checks = {
        "hallucinated_facts":     {"verdict": "pass", "severity": "none"},
        "fabricated_redactions":  {"verdict": "pass", "severity": "none"},
        "length_ratio":           {"verdict": "pass", "ratio": 1.0, "severity": "none"},
        "voice_match":            {"verdict": "pass", "severity": "none"},
        "page_boundary_fidelity": {"verdict": "pass", "severity": "none"},
        "ocr_artifact_handling":  {"verdict": "pass", "severity": "none"},
        "verbatim_quotability":   {"verdict": "pass", "severity": "none"},
        "interpretive_cleanups":  {"count": 0, "examples": [], "severity": "none"},
    }
    agg = schema.aggregate_checks(checks)
    assert agg["verdict"] == "pass"
    assert agg["hard_fail_count"] == 0
    assert agg["soft_fail_count"] == 0


def test_aggregate_hard_fail_on_hallucinated_facts() -> None:
    """Per the plan's hard-fail definitions: any one ship-blocker = hard_fail."""
    checks = {
        "hallucinated_facts":     {"verdict": "hard_fail", "severity": "high"},
        "fabricated_redactions":  {"verdict": "pass", "severity": "none"},
        "length_ratio":           {"verdict": "pass", "ratio": 1.0, "severity": "none"},
        "voice_match":            {"verdict": "pass", "severity": "none"},
        "page_boundary_fidelity": {"verdict": "pass", "severity": "none"},
        "ocr_artifact_handling":  {"verdict": "pass", "severity": "none"},
        "verbatim_quotability":   {"verdict": "pass", "severity": "none"},
        "interpretive_cleanups":  {"count": 0, "examples": [], "severity": "none"},
    }
    agg = schema.aggregate_checks(checks)
    assert agg["verdict"] == "hard_fail"
    assert agg["hard_fail_count"] == 1


def test_aggregate_soft_fail_count_sums_individual_soft_fails() -> None:
    """3+ soft fails on a single page should be flagged for human review."""
    checks = {
        "hallucinated_facts":     {"verdict": "pass", "severity": "none"},
        "fabricated_redactions":  {"verdict": "pass", "severity": "none"},
        "length_ratio":           {"verdict": "soft_fail", "ratio": 1.6, "severity": "low"},
        "voice_match":            {"verdict": "pass", "severity": "low"},
        "page_boundary_fidelity": {"verdict": "soft_fail", "severity": "low"},
        "ocr_artifact_handling":  {"verdict": "soft_fail", "severity": "low"},
        "verbatim_quotability":   {"verdict": "pass", "severity": "none"},
        "interpretive_cleanups":  {"count": 0, "examples": [], "severity": "none"},
    }
    agg = schema.aggregate_checks(checks)
    assert agg["verdict"] == "soft_fail"
    assert agg["hard_fail_count"] == 0
    assert agg["soft_fail_count"] == 3


def test_aggregate_voice_match_critical_counts_as_hard_fail() -> None:
    """voice_match has special hard-fail logic: severity=critical → hard fail."""
    checks = {
        "hallucinated_facts":     {"verdict": "pass", "severity": "none"},
        "fabricated_redactions":  {"verdict": "pass", "severity": "none"},
        "length_ratio":           {"verdict": "pass", "ratio": 1.0, "severity": "none"},
        "voice_match":            {"verdict": "soft_fail", "severity": "critical"},
        "page_boundary_fidelity": {"verdict": "pass", "severity": "none"},
        "ocr_artifact_handling":  {"verdict": "pass", "severity": "none"},
        "verbatim_quotability":   {"verdict": "pass", "severity": "none"},
        "interpretive_cleanups":  {"count": 0, "examples": [], "severity": "none"},
    }
    agg = schema.aggregate_checks(checks)
    assert agg["verdict"] == "hard_fail"
    assert agg["hard_fail_count"] == 1


def test_aggregate_not_applicable_does_not_count_as_fail() -> None:
    """`not_applicable` verdicts (skip pages, empty input) should be neutral."""
    checks = {
        "hallucinated_facts":     {"verdict": "not_applicable", "severity": "none"},
        "fabricated_redactions":  {"verdict": "not_applicable", "severity": "none"},
        "length_ratio":           {"verdict": "not_applicable", "ratio": 0.0, "severity": "none"},
        "voice_match":            {"verdict": "not_applicable", "severity": "none"},
        "page_boundary_fidelity": {"verdict": "not_applicable", "severity": "none"},
        "ocr_artifact_handling":  {"verdict": "not_applicable", "severity": "none"},
        "verbatim_quotability":   {"verdict": "not_applicable", "severity": "none"},
        "interpretive_cleanups":  {"count": 0, "examples": [], "severity": "none"},
    }
    agg = schema.aggregate_checks(checks)
    assert agg["verdict"] == "not_applicable"
    assert agg["hard_fail_count"] == 0
    assert agg["soft_fail_count"] == 0
