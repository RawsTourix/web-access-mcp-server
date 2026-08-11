# Yandex Search API verification — 2026-08-11

Implementation contract verified against current official Yandex Cloud AI Studio documentation.

- API line: Yandex Search API v2, synchronous `WebSearch.Search` REST method.
- Endpoint: operator-configured, official default
  `https://searchapi.api.cloud.yandex.net/v2/web/search`.
- Authentication: `Authorization: Api-Key <API_key>`; the API key needs the
  `yc.search-api.execute` scope and is never caller-provided.
- Request: JSON REST/transcoded field names are CamelCase. Required `query` contains
  `searchType` and `queryText`; `folderId` identifies the configured folder.
- Response: JSON object whose `rawData` bytes field is Base64-encoded XML when
  `responseFormat=FORMAT_XML`.
- Pagination: upstream page numbering starts at zero; the application page starts at one.
- Query text: `queryText` is bounded to 400 characters. The service-wide Search limit is wider, so the Yandex capability rejects the provider-specific excess before admission.
- Query words: the official technical limit is 40 words per request. The adapter and application capability use deterministic whitespace-delimited counting and reject known excess before admission.
- Result window: at most 250 results are available per search query. With flat grouping, `(application page * groupsOnPage)` must not exceed 250 and is checked before admission.
- Result limit: `groupSpec.groupsOnPage` is 1–100 for XML. The adapter uses flat grouping and one
  document per group so the neutral limit has direct semantics.
- Folder: `folderId` is bounded to 50 characters and is validated at configuration/bootstrap.
- Region: the upstream field is bounded to 100 characters. This implementation requires configured
  positive decimal region IDs; invalid mappings fail configuration/bootstrap. Region ranking is only
  available for Russian and Turkish search types and arrives solely through the neutral registry.
- Safe search: `FAMILY_MODE_NONE`, `FAMILY_MODE_MODERATE`, and `FAMILY_MODE_STRICT` map exactly to
  the neutral off, moderate, and strict values.
- Language: `l10n` changes response notifications, not result language. Search type chooses a
  provider corpus/domain but is operator configuration. Therefore v0.2 does not claim a neutral
  language capability for Yandex.
- Time range: current REST `period` supports all time, day, two weeks, and month. The neutral day
  and month values are supported; neutral year is rejected before attempt admission.
- Errors: Yandex HTTP `400`, `401`, and `403` describe a server-owned provider request/configuration
  rejection after Web Access client authentication. They normalize to upstream gateway errors, not
  Web Access client `401`/`403` or `422`. HTTP `429` remains provider rate limiting; `5xx` remains an
  upstream failure. An XML `error` element is terminal provider evidence; code 15 represents an empty
  result and code 10002 documents the maximum-word-count rejection.
- Request ID: the method response schema does not guarantee an ID field. A bounded `x-request-id`
  response header is retained when supplied, but clients cannot depend on it.

The local `internet-search-bot/src/mcp/yandex_search_library.py` was reviewed read-only. It confirms
the XML document fields (`doc`, `url`, `domain`, `title`, `passages`, `modtime`) and API-key auth,
but its deferred `searchAsync` polling flow and snake_case REST payload are not reused because the
current official synchronous REST contract is authoritative.

Official sources checked:

- <https://aistudio.yandex.ru/docs/en/search-api/api-ref/WebSearch/search.html>
- <https://aistudio.yandex.ru/docs/en/search-api/concepts/web-search.html>
- <https://aistudio.yandex.ru/docs/en/search-api/concepts/limits.html>
- <https://aistudio.yandex.ru/docs/en/search-api/operations/web-search-sync.html>
- <https://yandex.cloud/en/docs/iam/concepts/authorization/api-key>
- <https://aistudio.yandex.ru/docs/en/search-api/reference/error-codes.html>
