"""Which hosts an asset reference may name.

The reference is taken off the page being scraped, and the same check is
applied to the response's final URL, so the set of acceptable hosts is what
decides where the staged bytes can have come from. It is exactly two things:
the site serving the page, and the named delivery hosts that site publishes
its media through. A delivery network is shared infrastructure, so its hosts
are named in full rather than by suffix — one tenant's name is not another's.
"""

from __future__ import annotations

from pursue_index.av_fetch.client import (
    ASSET_DELIVERY_HOSTS,
    check_asset_url,
)

_PAGE_URL = "https://www.dvidshub.net/video/1006119"


def test_a_named_delivery_host_is_accepted() -> None:
    url = f"https://{ASSET_DELIVERY_HOSTS[0]}/video/2605/DOD_111688723.mp4"
    assert check_asset_url(url, page_url=_PAGE_URL) is None


def test_another_name_on_the_same_delivery_network_is_not_accepted() -> None:
    url = "https://someoneelse.cloudfront.net/video/DOD_111688723.mp4"
    assert check_asset_url(url, page_url=_PAGE_URL) is not None


def test_the_page_host_and_its_site_siblings_are_accepted() -> None:
    for host in ("www.dvidshub.net", "dvidshub.net", "media.dvidshub.net"):
        url = f"https://{host}/video/DOD_111688723.mp4"
        assert check_asset_url(url, page_url=_PAGE_URL) is None, host


def test_a_host_sharing_only_a_public_suffix_with_the_page_is_not_accepted() -> None:
    url = "https://elsewhere.co.uk/DOD_111688723.mp4"
    assert check_asset_url(url, page_url="https://www.example.co.uk/video/1") is not None


def test_a_longer_name_merely_ending_in_the_site_domain_is_not_accepted() -> None:
    url = "https://notdvidshub.net/DOD_111688723.mp4"
    assert check_asset_url(url, page_url=_PAGE_URL) is not None
