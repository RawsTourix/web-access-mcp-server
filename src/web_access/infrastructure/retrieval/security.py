"""Strict URL, destination, and DNS answer policy for arbitrary Retrieval."""

from __future__ import annotations

import ipaddress
import unicodedata
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

from web_access.core.config import RetrievalSecuritySettings


class InvalidRetrievalUrl(ValueError):
    """URL syntax or caller-controlled target properties are invalid."""


class BlockedDestinationError(PermissionError):
    """A syntactically valid target violates the server-owned egress policy."""


@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    requested_url: str
    normalized_url: str
    scheme: str
    ascii_host: str
    port: int
    ip_literal: ipaddress.IPv4Address | ipaddress.IPv6Address | None


class RetrievalUrlPolicy:
    def __init__(self, settings: RetrievalSecuritySettings) -> None:
        self._additional_ports = settings.additional_allowed_ports
        self._internal_networks = tuple(
            ipaddress.ip_network(cidr, strict=True) for cidr in settings.internal_cidrs
        )
        self.revision = settings.policy_revision

    def validate_url(self, requested_url: str) -> ValidatedUrl:
        if not 1 <= len(requested_url) <= 8192:
            raise InvalidRetrievalUrl("URL length is outside the Retrieval bound")
        if any(unicodedata.category(character) == "Cc" for character in requested_url):
            raise InvalidRetrievalUrl("URL contains control characters")
        try:
            parsed = urlsplit(requested_url)
            port = parsed.port
        except ValueError as error:
            raise InvalidRetrievalUrl("URL authority is malformed") from error
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise InvalidRetrievalUrl("URL scheme is not allowed")
        if parsed.username is not None or parsed.password is not None:
            raise InvalidRetrievalUrl("URL userinfo is not allowed")
        if not parsed.hostname:
            raise InvalidRetrievalUrl("URL requires a valid hostname")
        raw_host = parsed.hostname
        if "%" in raw_host:
            raise InvalidRetrievalUrl("scoped or encoded-percent host is not allowed")
        ascii_host = self._normalize_host(raw_host)
        selected_port = port if port is not None else (80 if scheme == "http" else 443)
        if selected_port not in {80 if scheme == "http" else 443, *self._additional_ports}:
            raise BlockedDestinationError("destination port is not allowed")
        literal = self._parse_ip_literal(ascii_host)
        if literal is not None:
            self.validate_addresses((literal,))
        elif ascii_host == "localhost" or ascii_host.endswith(".localhost"):
            raise BlockedDestinationError("localhost destinations are blocked")
        normalized = self._normalized_url(parsed, scheme, ascii_host, selected_port, port)
        return ValidatedUrl(
            requested_url=requested_url,
            normalized_url=normalized,
            scheme=scheme,
            ascii_host=ascii_host,
            port=selected_port,
            ip_literal=literal,
        )

    def validate_addresses(
        self,
        addresses: tuple[
            ipaddress.IPv4Address | ipaddress.IPv6Address | str,
            ...,
        ],
    ) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        if not addresses:
            raise BlockedDestinationError("DNS resolution returned no addresses")
        validated: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for value in addresses:
            try:
                address = ipaddress.ip_address(value)
            except ValueError as error:
                raise BlockedDestinationError("DNS returned an invalid address") from error
            effective: ipaddress.IPv4Address | ipaddress.IPv6Address = address
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
                effective = address.ipv4_mapped
            if (
                not effective.is_global
                or effective.is_loopback
                or effective.is_private
                or effective.is_link_local
                or effective.is_multicast
                or effective.is_unspecified
                or effective.is_reserved
            ):
                raise BlockedDestinationError("destination address is not public")
            if any(effective in network for network in self._internal_networks):
                raise BlockedDestinationError("destination address belongs to an internal CIDR")
            validated.append(address)
        return tuple(dict.fromkeys(validated))

    def _normalize_host(self, host: str) -> str:
        normalized = host.rstrip(".").lower()
        if not normalized or len(normalized) > 253:
            raise InvalidRetrievalUrl("hostname length is invalid")
        try:
            return normalized.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise InvalidRetrievalUrl("hostname IDNA form is invalid") from error

    def _parse_ip_literal(self, host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            return None

    def _normalized_url(
        self,
        parsed: SplitResult,
        scheme: str,
        ascii_host: str,
        selected_port: int,
        explicit_port: int | None,
    ) -> str:
        host = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
        default_port = 80 if scheme == "http" else 443
        authority = host
        if explicit_port is not None and selected_port != default_port:
            authority = f"{host}:{selected_port}"
        path = parsed.path or "/"
        return urlunsplit((scheme, authority, path, parsed.query, ""))
