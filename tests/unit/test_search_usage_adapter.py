"""Search usage adapter normalization at real driver failure boundaries."""

from __future__ import annotations

from typing import NoReturn, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from web_access.application.search.ports import AttemptStage, SearchUsageUnavailable
from web_access.domain.search import SearchProviderId
from web_access.infrastructure.search.usage import PostgresSearchUsageRepository


class FailingSession:
    async def execute(self, *_arguments: object, **_keywords: object) -> NoReturn:
        raise OSError("driver connection unavailable")


@pytest.mark.asyncio
async def test_driver_connection_errors_are_normalized_for_start_and_update() -> None:
    repository = PostgresSearchUsageRepository(cast(AsyncSession, FailingSession()))

    with pytest.raises(SearchUsageUnavailable, match="create Search attempt"):
        await repository.start_attempt(
            operation_id="op_test",
            principal_id="principal",
            provider_id=SearchProviderId.YANDEX,
            query_item_index=0,
            attempt_number=1,
        )
    with pytest.raises(SearchUsageUnavailable, match="update Search attempt"):
        await repository.mark_stage(
            operation_id="op_test",
            provider_id=SearchProviderId.YANDEX,
            query_item_index=0,
            attempt_number=1,
            stage=AttemptStage.DISPATCH_POSSIBLE,
        )
