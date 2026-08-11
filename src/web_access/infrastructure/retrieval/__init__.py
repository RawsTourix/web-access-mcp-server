"""Safe arbitrary-URL Retrieval infrastructure."""

from web_access.application.retrieval.ports import (
    DecompressionLimitExceeded,
    RedirectBlocked,
    ResponseTooLarge,
    RetrievalConnectionError,
    RetrievalPolicyError,
    TooManyRedirects,
    UnsupportedContentEncoding,
)
from web_access.infrastructure.retrieval.client import SafeAioHttpClient
from web_access.infrastructure.retrieval.fetcher import SafeHttpFetcher
from web_access.infrastructure.retrieval.resolver import ValidatingResolver
from web_access.infrastructure.retrieval.security import (
    BlockedDestinationError,
    InvalidRetrievalUrl,
    RetrievalUrlPolicy,
    ValidatedUrl,
)

__all__ = [
    "BlockedDestinationError",
    "DecompressionLimitExceeded",
    "InvalidRetrievalUrl",
    "RedirectBlocked",
    "ResponseTooLarge",
    "RetrievalConnectionError",
    "RetrievalPolicyError",
    "RetrievalUrlPolicy",
    "SafeAioHttpClient",
    "SafeHttpFetcher",
    "TooManyRedirects",
    "UnsupportedContentEncoding",
    "ValidatedUrl",
    "ValidatingResolver",
]
