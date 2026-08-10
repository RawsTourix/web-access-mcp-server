"""S3 exact application, REST, and MCP Search boundary gates."""

import pytest
from pydantic import BaseModel, ValidationError

from web_access.application.search.models import SearchBatchRequest, SearchQuery
from web_access.transport.mcp.search_schemas import WebSearchInput
from web_access.transport.rest.search_schemas import RestSearchRequest


@pytest.mark.parametrize(
    ("value", "valid"),
    [(0, False), (1, True), (32, True), (33, False)],
)
def test_application_and_rest_batch_boundaries(value: int, valid: bool) -> None:
    payload = {"queries": [{"query": "q"}] * value}
    for model in (SearchBatchRequest, RestSearchRequest):
        if valid:
            model.model_validate(payload)
        else:
            with pytest.raises(ValidationError):
                model.model_validate(payload)


@pytest.mark.parametrize(
    ("value", "valid"),
    [(0, False), (1, True), (8, True), (9, False)],
)
def test_mcp_batch_boundaries(value: int, valid: bool) -> None:
    payload = {"queries": ["q"] * value}
    if valid:
        WebSearchInput.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            WebSearchInput.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "maximum"),
    [(RestSearchRequest, 4096), (WebSearchInput, 2048)],
)
def test_query_text_min_max(model: type[BaseModel], maximum: int) -> None:
    values = (
        ("", False),
        ("q", True),
        ("q" * maximum, True),
        ("q" * (maximum + 1), False),
    )
    for value, valid in values:
        payload: dict[str, object] = {"queries": [{"query": value}]}
        if model is WebSearchInput:
            payload = {"queries": [value]}
        if valid:
            model.model_validate(payload)
        else:
            with pytest.raises(ValidationError):
                model.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "minimum", "maximum"),
    [("page", 1, 100), ("limit", 1, 50)],
)
def test_rest_numeric_boundary_table(field: str, minimum: int, maximum: int) -> None:
    for value, valid in (
        (minimum - 1, False),
        (minimum, True),
        (maximum, True),
        (maximum + 1, False),
    ):
        payload = {"queries": [{"query": "q", field: value}]}
        if valid:
            RestSearchRequest.model_validate(payload)
        else:
            with pytest.raises(ValidationError):
                RestSearchRequest.model_validate(payload)


@pytest.mark.parametrize(("field", "maximum"), [("page", 100), ("limit", 20)])
def test_mcp_numeric_boundary_table(field: str, maximum: int) -> None:
    for value, valid in ((0, False), (1, True), (maximum, True), (maximum + 1, False)):
        payload = {"queries": ["q"], field: value}
        if valid:
            WebSearchInput.model_validate(payload)
        else:
            with pytest.raises(ValidationError):
                WebSearchInput.model_validate(payload)


@pytest.mark.parametrize("model", [RestSearchRequest, WebSearchInput])
@pytest.mark.parametrize("field", ["language", "region", "safe_search", "time_range"])
def test_optional_fields_allow_omission_but_not_explicit_null(
    model: type[BaseModel], field: str
) -> None:
    base: dict[str, object] = {"queries": ["q"]}
    if model is RestSearchRequest:
        base = {"queries": [{"query": "q"}]}
        target = base["queries"][0]  # type: ignore[index]
    else:
        target = base
    model.model_validate(base)
    target[field] = None  # type: ignore[index]
    with pytest.raises(ValidationError):
        model.model_validate(base)


@pytest.mark.parametrize("model", [RestSearchRequest, WebSearchInput])
def test_generated_schema_has_no_null_for_omission_only_fields(model: type[BaseModel]) -> None:
    schema_text = str(model.model_json_schema())
    assert "null" not in schema_text


def test_operator_config_cannot_expand_application_ceiling() -> None:
    with pytest.raises(ValidationError):
        SearchQuery(query="q", page=101)
    with pytest.raises(ValidationError):
        SearchQuery(query="q", limit=51)
