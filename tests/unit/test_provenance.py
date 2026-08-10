"""Tests for the tiered, dated provenance claim model (spec §5).

The model deliberately makes the unsupportable claim *unrepresentable*:

* A positive :class:`ProvenanceClaim` can only assert that a release (or its
  content) was *previously released* — and only when it carries a source, an
  artifact URL, an establishing date, and the ``date_basis`` that date rests
  on. None of those can be silently defaulted.
* There is no boolean ``is_novel`` field and no tier meaning "not previously
  released". The honest negative is :class:`NoPriorReleaseFound`, which states
  only that a search found nothing and explicitly disclaims that absence of a
  prior release is established.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date

import pytest

from pursue_index.provenance import (
    NO_PRIOR_RELEASE_DISCLAIMER,
    POSITIVE_TIERS,
    DateBasis,
    NoPriorReleaseFound,
    ProvenanceClaim,
    ProvenanceTier,
    from_dict,
)


def _claim(**overrides) -> ProvenanceClaim:
    kwargs = dict(
        tier=ProvenanceTier.PREVIOUSLY_RELEASED,
        identifier="doc-abc123",
        source="wayback",
        artifact_url="https://web.archive.org/web/2019/https://example.gov/doc.pdf",
        established_date=date(2019, 3, 14),
        date_basis=DateBasis.WAYBACK_FIRST_CAPTURE,
    )
    kwargs.update(overrides)
    return ProvenanceClaim(**kwargs)


# --------------------------------------------------------------------------- #
# Tier vocabulary (spec §5)                                                    #
# --------------------------------------------------------------------------- #


def test_four_tiers_from_spec_are_exposed():
    """Exactly the four §5 tiers exist — no more, no fewer."""
    assert {t.value for t in ProvenanceTier} == {
        "previously_released",
        "previously_released_in_part",
        "content_previously_published",
        "no_prior_release_found",
    }


def test_no_tier_means_not_previously_released():
    """No tier asserts novelty / "not previously released"."""
    for tier in ProvenanceTier:
        assert "novel" not in tier.value
        assert "not_previously" not in tier.value


def test_positive_tiers_exclude_the_negative_outcome():
    """The three positive tiers are the ones a claim may assert."""
    assert set(POSITIVE_TIERS) == {
        ProvenanceTier.PREVIOUSLY_RELEASED,
        ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART,
        ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
    }
    assert ProvenanceTier.NO_PRIOR_RELEASE_FOUND not in POSITIVE_TIERS


def test_date_basis_distinguishes_the_four_sources():
    """date_basis never conflates the four ways an establishing date arises."""
    assert {b.value for b in DateBasis} == {
        "wayback_first_capture",
        "http_last_modified",
        "publisher_date",
        "pdf_creation_date",
    }


# --------------------------------------------------------------------------- #
# The claim record carries no boolean novelty field                           #
# --------------------------------------------------------------------------- #


def test_claim_has_no_boolean_novelty_field():
    names = {f.name for f in fields(ProvenanceClaim)}
    assert "is_novel" not in names
    for f in fields(ProvenanceClaim):
        assert f.type is not bool
        assert "novel" not in f.name


def test_claim_carries_the_required_evidence():
    claim = _claim()
    assert claim.identifier == "doc-abc123"
    assert claim.source == "wayback"
    assert claim.artifact_url.startswith("https://web.archive.org/")
    assert claim.established_date == date(2019, 3, 14)
    assert claim.date_basis is DateBasis.WAYBACK_FIRST_CAPTURE


# --------------------------------------------------------------------------- #
# Unsupportable / undated claims raise rather than defaulting                  #
# --------------------------------------------------------------------------- #


def test_claim_without_source_url_raises():
    with pytest.raises(ValueError, match="artifact URL"):
        _claim(artifact_url="")


def test_claim_without_date_basis_raises():
    with pytest.raises((TypeError, ValueError)):
        _claim(date_basis=None)


def test_claim_without_establishing_date_raises():
    with pytest.raises((TypeError, ValueError)):
        _claim(established_date=None)


def test_claim_without_identifier_raises():
    with pytest.raises(ValueError, match="identifier"):
        _claim(identifier="   ")


def test_claim_without_source_raises():
    with pytest.raises(ValueError, match="source"):
        _claim(source="")


def test_positive_claim_cannot_use_the_negative_tier():
    """You cannot dress up "found nothing" as a positive claim."""
    with pytest.raises(ValueError, match="no_prior_release_found"):
        _claim(tier=ProvenanceTier.NO_PRIOR_RELEASE_FOUND)


# --------------------------------------------------------------------------- #
# The honest negative                                                          #
# --------------------------------------------------------------------------- #


def test_no_prior_release_found_carries_what_was_searched():
    neg = NoPriorReleaseFound(
        identifier="doc-xyz",
        sources_searched=("wayback", "publisher"),
        searched_date=date(2026, 8, 6),
    )
    assert neg.identifier == "doc-xyz"
    assert neg.sources_searched == ("wayback", "publisher")
    assert neg.tier is ProvenanceTier.NO_PRIOR_RELEASE_FOUND


def test_no_prior_release_found_requires_something_searched():
    with pytest.raises(ValueError, match="searched"):
        NoPriorReleaseFound(identifier="doc-xyz", sources_searched=())


def test_no_prior_release_found_serialises_with_explicit_disclaimer():
    neg = NoPriorReleaseFound(identifier="doc-xyz", sources_searched=("wayback",))
    payload = neg.to_dict()
    assert "absence of a prior release is not established" in payload.values()
    assert NO_PRIOR_RELEASE_DISCLAIMER == "absence of a prior release is not established"
    assert NO_PRIOR_RELEASE_DISCLAIMER in payload.values()


# --------------------------------------------------------------------------- #
# Lossless round-trip serialisation                                           #
# --------------------------------------------------------------------------- #


def test_positive_claim_round_trips_losslessly():
    for tier in POSITIVE_TIERS:
        original = _claim(tier=tier)
        restored = from_dict(original.to_dict())
        assert restored == original
        assert isinstance(restored, ProvenanceClaim)


def test_every_date_basis_round_trips():
    for basis in DateBasis:
        original = _claim(date_basis=basis)
        assert from_dict(original.to_dict()) == original


def test_negative_result_round_trips_losslessly():
    original = NoPriorReleaseFound(
        identifier="doc-xyz",
        sources_searched=("wayback", "publisher", "dvids"),
        searched_date=date(2026, 8, 6),
    )
    restored = from_dict(original.to_dict())
    assert restored == original
    assert isinstance(restored, NoPriorReleaseFound)


def test_negative_result_round_trips_without_search_date():
    original = NoPriorReleaseFound(identifier="doc-xyz", sources_searched=("wayback",))
    assert from_dict(original.to_dict()) == original


def test_from_dict_rejects_unknown_kind():
    with pytest.raises(ValueError, match="kind"):
        from_dict({"kind": "wishful_thinking"})


def test_claim_rejects_a_non_http_artifact_url() -> None:
    """`artifact_url` is the address a citation points at, so it names one.

    The value arrives verbatim from a third-party sitemap `<loc>`, and these
    records exist to become /methodology citations. Only an absolute http(s)
    URL is something a reader can open, and the question is settled at
    construction — the one place every path into a record goes through — rather
    than left to whatever renders it."""
    for value in ("javascript:alert(1)", "data:text/html;base64,PHNjcmlwdD4=", "file:///etc/passwd"):
        with pytest.raises(ValueError, match="scheme"):
            _claim(artifact_url=value)


def test_claim_accepts_http_and_https() -> None:
    for ok in ("https://vault.fbi.gov/UFO", "http://www.ufoevidence.org/topics/Cometa.htm"):
        assert _claim(artifact_url=ok).artifact_url == ok
