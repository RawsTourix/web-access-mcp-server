from __future__ import annotations

import ipaddress

import pytest

from web_access.core.config import RetrievalSecuritySettings
from web_access.infrastructure.retrieval.security import (
    BlockedDestinationError,
    InvalidRetrievalUrl,
    RetrievalUrlPolicy,
)


@pytest.fixture
def policy() -> RetrievalUrlPolicy:
    return RetrievalUrlPolicy(
        RetrievalSecuritySettings(
            additional_allowed_ports=frozenset({8443}),
            internal_cidrs=("93.184.216.0/24",),
        )
    )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.net/resource",
        "https://user:secret@example.net/",
        "https://example.net:65536/",
        "https://[fe80::1%25eth0]/",
        "https://example.net/\x00bad",
        "https:///missing-host",
    ],
)
def test_invalid_url_forms_are_rejected(policy: RetrievalUrlPolicy, url: str) -> None:
    with pytest.raises(InvalidRetrievalUrl):
        policy.validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "https://[::1]/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://100.64.0.1/",
        "http://localhost/",
        "http://service.localhost/",
        "https://example.net:444/",
    ],
)
def test_blocked_literal_name_and_port_destinations(policy: RetrievalUrlPolicy, url: str) -> None:
    with pytest.raises(BlockedDestinationError):
        policy.validate_url(url)


def test_idna_query_fragment_and_operator_port_handling(policy: RetrievalUrlPolicy) -> None:
    validated = policy.validate_url("https://пример.рф:8443/a?b=1#ignored")
    assert validated.ascii_host == "xn--e1afmkfd.xn--p1ai"
    assert validated.port == 8443
    assert validated.normalized_url == "https://xn--e1afmkfd.xn--p1ai:8443/a?b=1"


def test_dns_policy_rejects_private_mixed_and_configured_internal_answers(
    policy: RetrievalUrlPolicy,
) -> None:
    public = ipaddress.ip_address("8.8.8.8")
    assert policy.validate_addresses((public,)) == (public,)
    with pytest.raises(BlockedDestinationError):
        policy.validate_addresses(("8.8.8.8", "10.0.0.1"))
    with pytest.raises(BlockedDestinationError):
        policy.validate_addresses(("93.184.216.34",))
    with pytest.raises(BlockedDestinationError):
        policy.validate_addresses(("::ffff:10.0.0.1",))
