"""Build-only exemptions and the dependency paths that reach them.
"""

from __future__ import annotations

import pytest

from tests.support.web_audit_support import (
    ALLOW,
    ALLOWLIST,
    LOCK,
    REAL_LOCK,
    ROOTS_ALLOW,
    TODAY,
    _pc,
    _report,
    _vuln,
    gate,
)

# --- a transitive skip needs EVERY path to come from a build-only root.


def _roots_decide(lock, pkg="postcss"):
    return gate.decide(_report(_vuln(pkg, "high")), ROOTS_ALLOW, lock=lock, today=TODAY)


def test_reached_only_from_a_build_only_root_is_exempt():
    assert _roots_decide(_pc()).ok


def test_a_runtime_root_reaching_it_directly_makes_it_runtime():
    lock = _pc(("node_modules/preact", ("10.0.0", ["postcss"])))
    d = _roots_decide(lock)
    assert not d.ok
    assert any("preact" in f and "runtime" in f for f in d.failures)


def test_a_deep_transitive_runtime_path_makes_it_runtime():
    lock = _pc(
        ("node_modules/preact", ("10.0.0", ["a"])),
        ("node_modules/a", ("1.0.0", ["b"])),
        ("node_modules/b", ("1.0.0", ["postcss"])),
    )
    assert not _roots_decide(lock).ok


def test_a_runtime_path_to_a_transitive_of_the_exempt_package_is_caught():
    # nanoid is exempt, but preact -> nanoid is a runtime path to it.
    lock = _pc(("node_modules/preact", ("10.0.0", ["nanoid"])))
    assert not _roots_decide(lock, pkg="nanoid").ok


def test_optional_and_peer_edges_count_as_paths():
    for kind in ("optionalDependencies", "peerDependencies"):
        lock = _pc(("node_modules/preact", ("10.0.0", {kind: ["postcss"]})))
        assert not _roots_decide(lock).ok, kind


def test_a_runtime_root_that_is_itself_the_package_is_runtime():
    allow = {**ROOTS_ALLOW, "build_only": {"preact@10.0.0": "wrongly listed"}}
    d = gate.decide(_report(_vuln("preact", "high")), allow, lock=_pc(), today=TODAY)
    assert not d.ok


def test_a_nested_copy_is_resolved_the_way_node_does():
    # preact's own nested postcss shadows the top-level one for preact only.
    nested = ("node_modules/preact/node_modules/postcss", ("8.5.0", []))
    on_runtime = _pc(("node_modules/preact", ("10.0.0", ["postcss"])), nested)
    assert not _roots_decide(on_runtime).ok
    # With no edge from preact, the nested copy is not reachable from it.
    off_runtime = _pc(nested)
    assert _roots_decide(off_runtime).ok


def test_without_build_only_roots_nothing_is_exempt():
    allow = {**ROOTS_ALLOW}
    allow.pop("build_only_roots")
    d = gate.decide(_report(_vuln("postcss", "high")), allow, lock=_pc(), today=TODAY)
    assert not d.ok


def test_a_root_that_depends_on_a_package_by_a_missing_lock_entry_is_ignored():
    lock = _pc(("node_modules/preact", ("10.0.0", ["not-installed"])))
    assert _roots_decide(lock).ok


def test_build_only_roots_need_reasons():
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only_roots": {"astro": ""}})
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only_roots": ["astro"]})


def test_committed_exemptions_are_not_reachable_from_a_runtime_root():
    allow = gate.load_allowlist(ALLOWLIST)
    assert allow["build_only_roots"], "the committed allowlist must name its build-only roots"
    runtime = gate.runtime_roots(REAL_LOCK, allow["build_only_roots"])
    assert {"preact", "minisearch", "regl-scatterplot", "@preact/signals"} <= set(runtime)
    for key in allow["build_only"]:
        name = key.rsplit("@", 1)[0]
        assert gate.not_build_only(name, allow, REAL_LOCK) is None, key


def test_unknown_package_counts_as_runtime():
    d = gate.decide(_report(_vuln("brand-new-lib", "high")), {"build_only": {}})
    assert not d.ok


def test_moderate_and_low_do_not_fail():
    d = gate.decide(
        _report(_vuln("preact", "moderate"), _vuln("minisearch", "low")), ALLOW
    )
    assert d.ok


def test_transitive_entry_is_covered_by_its_source_package():
    # @astrojs/mdx is critical only because it depends on astro.
    mdx = {
        "name": "@astrojs/mdx",
        "severity": "critical",
        "via": ["astro"],
        "effects": [],
        "range": "*",
        "nodes": [],
        "fixAvailable": False,
    }
    astro = _vuln("astro", "critical", "GHSA-crit-0000-0000")
    assert gate.decide(_report(astro, mdx), ALLOW, lock=LOCK, today=TODAY).ok
    # With the source unaccepted, the failure is reported on the source.
    bad = gate.decide(_report(_vuln("astro", "critical"), mdx), ALLOW, lock=LOCK, today=TODAY)
    assert not bad.ok


def test_high_with_only_string_via_and_no_source_fails():
    orphan = {
        "name": "ghost",
        "severity": "high",
        "via": ["missing"],
        "effects": [],
        "range": "*",
        "nodes": [],
        "fixAvailable": False,
    }
    assert not gate.decide(_report(orphan), ALLOW, lock=LOCK, today=TODAY).ok


@pytest.mark.parametrize("sev", ["none", "severe", "HIGH", "", None, 3])
def test_unknown_severity_fails_closed(sev):
    entry = _vuln("preact", "low")
    entry["severity"] = sev
    d = gate.decide(_report(entry), ALLOW, lock=LOCK, today=TODAY)
    assert not d.ok
    assert any("severity" in f for f in d.failures)


def test_unknown_severity_on_an_advisory_fails_closed():
    entry = _vuln("preact", "low")
    entry["via"][0]["severity"] = "catastrophic"
    d = gate.decide(_report(entry), ALLOW, lock=LOCK, today=TODAY)
    assert not d.ok


@pytest.mark.parametrize("sev", ["info", "low", "moderate", "high", "critical"])
def test_every_documented_severity_is_understood(sev):
    d = gate.decide(_report(_vuln("postcss", sev)), ALLOW, lock=LOCK, today=TODAY)
    assert not any("severity" in f for f in d.failures)
