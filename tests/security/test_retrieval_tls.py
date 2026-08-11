from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import ClientConnectorCertificateError
from aiohttp.abc import AbstractResolver, ResolveResult
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from web_access.core.config import RetrievalSecuritySettings, RetrievalSettings
from web_access.infrastructure.retrieval.client import SafeAioHttpClient
from web_access.infrastructure.retrieval.resolver import ValidatingResolver
from web_access.infrastructure.retrieval.security import RetrievalUrlPolicy


class _LoopbackResolver(AbstractResolver):
    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        return [
            ResolveResult(
                hostname=host,
                host="127.0.0.1",
                port=port,
                family=socket.AF_INET,
                proto=socket.IPPROTO_TCP,
                flags=socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
            )
        ]

    async def close(self) -> None:
        return None


class _ControlledLoopbackValidator:
    def validate_addresses(self, addresses: tuple[str, ...]) -> tuple[object, ...]:
        return tuple(ipaddress.ip_address(address) for address in addresses)


def _certificate_files(root: Path, *, expired: bool = False) -> tuple[Path, Path, Path]:
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Web Access test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=30))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "tls.test")])
    valid_from = now - timedelta(days=10 if expired else 1)
    valid_until = now - timedelta(days=1) if expired else now + timedelta(days=10)
    server = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_until)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("tls.test")]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = root / "ca.pem"
    cert_path = root / "server.pem"
    key_path = root / "server.key"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(server.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_path, cert_path, key_path


async def _tls_server(cert_path: Path, key_path: Path) -> AsyncIterator[int]:
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_context)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        server.close()
        await server.wait_closed()


def _client(port: int, ssl_context: ssl.SSLContext | None) -> SafeAioHttpClient:
    security = RetrievalSecuritySettings(additional_allowed_ports=frozenset({port}))
    policy = RetrievalUrlPolicy(security)
    resolver = ValidatingResolver(_ControlledLoopbackValidator(), _LoopbackResolver())
    return SafeAioHttpClient(
        settings=RetrievalSettings(security=security),
        policy=policy,
        resolver=resolver,
        ssl_context=ssl_context,
    )


@pytest.mark.asyncio
async def test_tls_valid_chain_succeeds_and_hostname_and_ca_are_verified(tmp_path: Path) -> None:
    ca_path, cert_path, key_path = _certificate_files(tmp_path)
    async for port in _tls_server(cert_path, key_path):
        trusted = ssl.create_default_context(cafile=str(ca_path))
        valid_client = _client(port, trusted)
        try:
            response = await valid_client.get(f"https://tls.test:{port}/", timeout_seconds=2)
            assert await response.read() == b"ok"
        finally:
            await valid_client.close()

        hostname_client = _client(port, trusted)
        try:
            with pytest.raises(ClientConnectorCertificateError):
                await hostname_client.get(f"https://wrong.test:{port}/", timeout_seconds=2)
        finally:
            await hostname_client.close()

        untrusted_client = _client(port, ssl.create_default_context())
        try:
            with pytest.raises(ClientConnectorCertificateError):
                await untrusted_client.get(f"https://tls.test:{port}/", timeout_seconds=2)
        finally:
            await untrusted_client.close()


@pytest.mark.asyncio
async def test_tls_expired_certificate_is_rejected(tmp_path: Path) -> None:
    ca_path, cert_path, key_path = _certificate_files(tmp_path, expired=True)
    async for port in _tls_server(cert_path, key_path):
        client = _client(port, ssl.create_default_context(cafile=str(ca_path)))
        try:
            with pytest.raises(ClientConnectorCertificateError):
                await client.get(f"https://tls.test:{port}/", timeout_seconds=2)
        finally:
            await client.close()
