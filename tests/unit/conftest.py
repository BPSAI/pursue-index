"""Fixtures shared by the upstream-fetch tests."""

from __future__ import annotations

import socket

import pytest

PUBLIC_IP = "93.184.216.34"


@pytest.fixture()
def dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Name resolution without a network: ``{host: ip}``; any unlisted host gets a public IP."""
    table: dict[str, str] = {}

    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        ip = table.get(str(host), PUBLIC_IP)
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return table
