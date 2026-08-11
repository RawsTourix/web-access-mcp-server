"""Safe arbitrary-URL Retrieval infrastructure."""

from web_access.infrastructure.retrieval.client import SafeAioHttpClient
from web_access.infrastructure.retrieval.fetcher import (
    DecompressionLimitExceeded,
    RedirectBlocked,
    ResponseTooLarge,
    SafeHttpFetcher,
    TooManyRedirects,
    UnsupportedContentEncoding,
)
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
    "RetrievalUrlPolicy",
    "SafeAioHttpClient",
    "SafeHttpFetcher",
    "TooManyRedirects",
    "UnsupportedContentEncoding",
    "ValidatedUrl",
    "ValidatingResolver",
]
