"""Safe arbitrary-URL Retrieval infrastructure."""

from web_access.infrastructure.retrieval.client import SafeAioHttpClient
from web_access.infrastructure.retrieval.resolver import ValidatingResolver
from web_access.infrastructure.retrieval.security import (
    BlockedDestinationError,
    InvalidRetrievalUrl,
    RetrievalUrlPolicy,
    ValidatedUrl,
)

__all__ = [
    "BlockedDestinationError",
    "InvalidRetrievalUrl",
    "RetrievalUrlPolicy",
    "SafeAioHttpClient",
    "ValidatedUrl",
    "ValidatingResolver",
]
