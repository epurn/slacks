"""Shared, network-free fakes for the FTY-073 adversarial suite.

Not a test module (the leading underscore keeps pytest from collecting it). It
provides the injectable seams the security tests use so the boundaries are
exercised with no real DNS or sockets: a scriptable resolver, a canned-response
opener, and an opener that explodes if a blocked request ever reaches transport.
"""

from __future__ import annotations

import socket
from typing import Any, Literal


def resolver_returning(*ips: str) -> Any:
    """A fake ``getaddrinfo`` resolving any host to each of ``ips`` (in order).

    Multiple addresses model a host with several DNS records, so a test can prove
    the policy inspects *every* resolved address (one private IP among public ones
    must still fail closed). IPv6 literals get an ``AF_INET6`` family so the
    returned ``getaddrinfo`` tuples are realistic, though the policy only reads the
    address string.
    """

    def _resolve(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        infos: list[Any] = []
        for ip in ips:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            infos.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port)))
        return infos

    return _resolve


def resolver_raising(exc: Exception) -> Any:
    """A fake ``getaddrinfo`` that raises ``exc`` (models a DNS lookup failure)."""

    def _resolve(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        raise exc

    return _resolve


def resolver_empty() -> Any:
    """A fake ``getaddrinfo`` returning no addresses (host resolves to nothing)."""

    def _resolve(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    return _resolve


class FakeHeaders:
    """Minimal stand-in for an ``http.client`` headers object the fetcher reads."""

    def __init__(self, content_type: str, charset: str | None = "utf-8") -> None:
        self._content_type = content_type
        self._charset = charset

    def get_content_type(self) -> str:
        return self._content_type

    def get_content_charset(self) -> str | None:
        return self._charset


class FakeResponse:
    """A context-manager HTTP response exposing only what the openers read."""

    def __init__(
        self,
        body: bytes,
        *,
        content_type: str = "application/json",
        charset: str | None = "utf-8",
    ) -> None:
        self._body = body
        self.headers = FakeHeaders(content_type, charset)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: Any) -> Literal[False]:
        return False

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            return self._body
        return self._body[:amount]


class FakeOpener:
    """An opener returning a canned response (or raising) without any socket."""

    def __init__(self, response: Any = None, *, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc

    def open(self, request: Any, timeout: float | None = None) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._response


class ExplodingOpener:
    """An opener that fails if touched — proves a blocked request never egresses."""

    def open(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("transport must not be reached for a blocked request")
