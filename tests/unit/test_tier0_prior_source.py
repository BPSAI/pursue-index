"""Tests for the prior-source capture in a Tier-0 claim (spec §5).

``originally released on <source> on <date>`` captures whatever token the CSV
put there, and that token lands in a tracked artifact as the named prior source
— the thing a later stage resolves, and a reader treats as a pointer. Two shapes
are what the rule expects and are kept verbatim: a bare domain
("dvidshub.net") and a plain outlet name ("Time"), neither of which carries a
scheme. An absolute http(s) URL is kept verbatim too.

Everything else names nothing a reader can follow, so it never becomes a prior
source: a URI in another scheme, a protocol-relative ``//host/path`` (which
leaves the scheme for whatever renders it to decide), and a value that is only
URI-shaped after characters with no text of their own are removed.
"""

from __future__ import annotations

from datetime import date

import pytest

from pursue_index.provenance import DateBasis, ProvenanceTier, is_citable_prior_source
from pursue_index.tier0_sweep import Tier0Claim, detect_claim


def _card(description: str) -> dict:
    return {
        "card_id": "t0-1",
        "title": "ODNI-UAP-D001, Narrative",
        "asset_filename": "t0-1.pdf",
        "description": description,
    }


def test_a_named_domain_is_kept_verbatim() -> None:
    claim = detect_claim(
        _card("This imagery was originally released on dvidshub.net on May 22, 2026.")
    )
    assert claim is not None
    assert claim.prior_source == "dvidshub.net"
    assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED


def test_an_http_source_is_kept_verbatim() -> None:
    claim = detect_claim(
        _card("Originally released on https://www.dvidshub.net/x on May 22, 2026.")
    )
    assert claim is not None
    assert claim.prior_source == "https://www.dvidshub.net/x"


@pytest.mark.parametrize(
    "token",
    ["javascript:alert(1)", "data:text/html;base64,PHN2Zz4=", "file:///etc/passwd"],
)
def test_a_non_web_uri_never_becomes_a_prior_source(token: str) -> None:
    claim = detect_claim(_card(f"Originally released on {token} on May 22, 2026."))
    assert claim is None


@pytest.mark.parametrize("token", ["javascript:alert(1)", "ftp://example.gov/x"])
def test_the_claim_type_refuses_a_non_web_uri_prior_source(token: str) -> None:
    with pytest.raises(ValueError):
        Tier0Claim(
            card_id="t0-2",
            identifier="t0-2.pdf",
            title="x",
            tier=ProvenanceTier.PREVIOUSLY_RELEASED,
            evidence="Originally released on it on May 22, 2026.",
            prior_source=token,
            date_basis=DateBasis.PUBLISHER_DATE,
            stated_date=date(2026, 5, 22),
        )


@pytest.mark.parametrize(
    "value",
    ["//documents.example.gov/a.pdf", "//example.gov", "// example.gov/a.pdf"],
)
def test_a_protocol_relative_value_names_no_address(value: str) -> None:
    """``//host/path`` states a host but no scheme, so it is not an address.

    Which scheme it resolves to is decided by whatever renders it, not by the
    value — so it is not something a reader can follow, and a citation needs
    the whole address written out.
    """
    assert is_citable_prior_source(value) is False


@pytest.mark.parametrize(
    "value",
    ["java\tscript:alert(1)", "java\nscript:alert(1)", "data\r:text/html,x", "htt\np://a.gov/x"],
)
def test_a_value_that_is_only_uri_shaped_once_stripped_is_not_an_address(value: str) -> None:
    """A citable URL is the exact characters a reader would follow.

    Characters that carry no text of their own — tab, carriage return, line
    feed and the rest of the C0 range — are removed before the value is read,
    so a scheme split across them is recognised as the scheme it is. A value
    that only becomes URI-shaped after that removal is not an address as
    written, so it is not citable either.
    """
    assert is_citable_prior_source(value) is False


@pytest.mark.parametrize(
    "value",
    ["Time:", "Time: The Weekly Magazine", "The Black Vault:", "dvidshub.net", "COMETA report"],
)
def test_a_bare_outlet_name_or_domain_stays_citable(value: str) -> None:
    """A colon ending an outlet name is punctuation, not a scheme separator.

    The rule reads prose, so the captured token is usually a bare domain or an
    outlet name; ``Time:`` is the latter with the clause's colon attached. A
    colon only introduces a scheme when something URI-shaped follows it.
    """
    assert is_citable_prior_source(value) is True


@pytest.mark.parametrize(
    "value", ["http://a.gov/x", "https://www.dvidshub.net/x", "HTTPS://A.GOV/X"]
)
def test_an_absolute_web_url_stays_citable(value: str) -> None:
    assert is_citable_prior_source(value) is True
