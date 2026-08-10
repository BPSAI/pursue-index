"""Tests for the second citable field on a resolved claim (spec §6c, PV1.5).

``content_previously_published`` may rest on a named prior publication instead
of a fetchable artifact, so ``prior_publication`` is the one field on a resolved
claim that can carry a citation without an ``artifact_url`` beside it. It
reaches the claim from the government's CSV prose by way of the Tier-0 detector,
and it serialises into ``identifier-claims.json`` as the thing a reader is
pointed at — which makes it exactly as citable a field as ``artifact_url``.

So both fields answer to the same question at construction: is this something a
reader can follow? A bare outlet name and a bare domain answer yes; an absolute
http(s) URL answers yes; a URI in another scheme and a protocol-relative value
answer no.
"""

from __future__ import annotations

import pytest

from pursue_index.provenance import ProvenanceTier
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim


def _claim(prior_publication: str) -> ResolvedClaim:
    return ResolvedClaim(
        card_id="cometa-1",
        tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
        source=ResolutionSource.GOVERNMENT_DESCRIPTION,
        prior_publication=prior_publication,
    )


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html;base64,PHN2Zz4=",
        "file:///etc/passwd",
        "//documents.example.gov/a.pdf",
        "java\tscript:alert(1)",
    ],
)
def test_a_prior_publication_that_names_no_address_is_refused(value: str) -> None:
    with pytest.raises(ValueError):
        _claim(value)


@pytest.mark.parametrize(
    "value",
    ["COMETA report", "Time", "Time:", "dvidshub.net", "https://www.dvidshub.net/x"],
)
def test_a_prior_publication_a_reader_can_follow_is_kept_verbatim(value: str) -> None:
    assert _claim(value).prior_publication == value


def test_deserialisation_answers_the_same_question() -> None:
    """A stored claim is read back through the same constructor, so the rule holds."""
    with pytest.raises(ValueError):
        ResolvedClaim.from_dict(
            {
                "card_id": "cometa-1",
                "tier": "content_previously_published",
                "source": "government_description",
                "prior_publication": "javascript:alert(1)",
            }
        )
