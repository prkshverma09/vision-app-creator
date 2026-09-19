"""Webhook transport validation with resolver and pinned-connection boundaries."""
from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from .models import Destination


class DestinationSafetyError(RuntimeError):
    pass


class DeliveryRateLimited(RuntimeError):
    pass


class Resolver(Protocol):
    async def resolve(self, hostname: str) -> list[str]: ...


class HttpConnector(Protocol):
    async def request(
        self, url: str, address: str, payload: bytes, signature: str
    ) -> TransportResponse: ...


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body_size: int = 0
    redirect_url: str | None = None


class SystemResolver:
    async def resolve(self, hostname: str) -> list[str]:
        # Resolution is isolated behind this port so component tests never use DNS.
        infos = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        return sorted({str(info[4][0]) for info in infos})


class StaticResolver:
    def __init__(self, answers: dict[str, list[str]]) -> None:
        self._answers = answers

    async def resolve(self, hostname: str) -> list[str]:
        return list(self._answers.get(hostname, []))


class SafeWebhookTransport:
    """Validates DNS and pins the connector to an approved public address.

    The connector must connect to ``address`` while preserving the URL hostname for
    TLS/SNI. Redirects are never followed, preventing a validated public endpoint
    from redirecting to an internal service.
    """

    def __init__(
        self,
        destinations: dict[str, Destination],
        resolver: Resolver,
        connector: HttpConnector,
        *,
        allowed_destination_refs: frozenset[str] | None = None,
        max_payload_bytes: int = 64_000,
        max_response_bytes: int = 64_000,
        max_requests_per_destination: int = 100,
    ) -> None:
        if allowed_destination_refs is not None:
            unknown = set(destinations) - allowed_destination_refs
            if unknown:
                raise DestinationSafetyError("destination is not production-allowlisted")
        self._destinations = dict(destinations)
        self._resolver = resolver
        self._connector = connector
        self._max_payload = max_payload_bytes
        self._max_response = max_response_bytes
        self._max_requests = max_requests_per_destination
        self._request_counts: dict[str, int] = {}

    async def send(self, destination_ref: str, payload: bytes, signature: str) -> int:
        destination = self._destinations.get(destination_ref)
        if destination is None:
            raise DestinationSafetyError("unknown destination reference")
        if len(payload) > self._max_payload:
            raise DestinationSafetyError("payload exceeds configured bound")
        count = self._request_counts.get(destination_ref, 0)
        if count >= self._max_requests:
            raise DeliveryRateLimited(destination_ref)

        hostname = urlsplit(destination.url).hostname
        if hostname is None:
            raise DestinationSafetyError("destination hostname is missing")
        addresses = await self._resolver.resolve(hostname)
        if not addresses:
            raise DestinationSafetyError("destination DNS returned no addresses")
        parsed = [_public_address(value) for value in addresses]
        # Every answer must be safe. This rejects DNS rebinding/mixed public-private sets.
        if not all(parsed):
            raise DestinationSafetyError("destination DNS includes a non-public address")

        self._request_counts[destination_ref] = count + 1
        response = await self._connector.request(destination.url, addresses[0], payload, signature)
        if response.redirect_url is not None or 300 <= response.status < 400:
            raise DestinationSafetyError("webhook redirects are forbidden")
        if response.body_size > self._max_response:
            raise DestinationSafetyError("webhook response exceeds configured bound")
        return response.status


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise DestinationSafetyError("DNS returned an invalid address") from error
    return address.is_global


@dataclass(frozen=True)
class SinkRequest:
    destination: str
    payload: dict[str, object]
    signature: str
    connected_address: str | None = None


class InMemoryWebhookSink:
    """No-network WebhookTransport and low-level connector fake."""

    def __init__(self, *, failures: int = 0, redirect_url: str | None = None) -> None:
        self.failures = failures
        self.redirect_url = redirect_url
        self.requests: list[SinkRequest] = []

    async def send(self, destination_ref: str, payload: bytes, signature: str) -> int:
        return await self._capture(destination_ref, None, payload, signature)

    async def request(
        self, url: str, address: str, payload: bytes, signature: str
    ) -> TransportResponse:
        status = await self._capture(url, address, payload, signature)
        return TransportResponse(status=status, redirect_url=self.redirect_url)

    async def _capture(
        self, destination: str, address: str | None, payload: bytes, signature: str
    ) -> int:
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("injected webhook failure")
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise ValueError("webhook payload must be an object")
        self.requests.append(SinkRequest(destination, decoded, signature, address))
        return 200
