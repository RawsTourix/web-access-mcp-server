# ADR-0024 — Retry/annotation class учитывает resource creation и billable cost, а не только «чтение»

**Статус:** accepted

## 1. Контекст

Некоторые Web Access operations выглядят read-oriented с точки зрения пользователя, но имеют observable effects внутри/вокруг сервиса:

```text
web_search(provider=yandex)
→ может потребить billable upstream unit

web_fetch
→ HTTP GET
→ создаёт raw/derived ContentObjects и расходует storage/quota

content_parse
→ может создать derived ContentObject
```

Если классифицировать их как безусловно `safe auto-retry` только потому, что они «не нажимают кнопку на сайте», потерянный response может привести к:

- повторной оплате provider request;
- повторному HTTP acquisition;
- дополнительным ContentObjects/storage/quota;
- неоднозначному provenance.

---

## 2. Решение

Trusted retry/execution metadata учитывает **все observable effects**:

1. external side effects;
2. billable upstream effects;
3. durable/transient resource creation;
4. ability to prove idempotent replay.

`readOnlyHint` MCP annotation и Agent retry class не обязаны совпадать с HTTP verb/intuitive «чтением».

---

## 3. `web_search`

Semantic query remains read-only with respect to target web.

Но один и тот же tool может использовать billable provider.

Поэтому core static Agent retry class:

```text
conservative / no blind automatic retry after possible provider dispatch
```

Service/provider adapter может **внутри одного operation** повторить только те failure phases, где по evidence безопасно доказано отсутствие billable/send side effect и policy это разрешает.

После потерянного tool response Agent не должен автоматически делать новый `web_search` только на основании static safe class.

MCP annotations могут сохранять:

```text
readOnlyHint=true
idempotentHint=true
```

как semantic operation hint, но trusted agent retry policy для собственного агента строже из-за cost semantics.

---

## 4. `web_fetch`

`web_fetch` создаёт Content resources.

Поэтому baseline metadata:

```text
readOnlyHint=false
idempotentHint=false
Agent retry = no blind automatic retry after uncertain dispatch/result
```

Это не означает, что HTTP GET считается mutating web action. Причина — observable Web Access resource/quota creation и невозможность гарантировать, что второй acquisition является тем же логическим result.

Если transport failure доказан **до HTTP/resource dispatch**, implementation может вернуть retryable pre-dispatch error; это не разрешает общий blind replay после ambiguous response loss.

---

## 5. `content_parse`

`content_parse` может создавать derived ContentObject, но design требует canonical compatible representation reuse.

Поэтому tool может быть логически idempotent только если implementation доказывает:

```text
same source content
+ same canonical parser capability/revision/profile
→ same compatible representation reused or single logical result
```

До такого доказательства Agent retry policy должна быть conservative.

Version acceptance для `content_parse` обязана иметь duplicate/concurrent/replay tests.

После доказанного canonical reuse допустимо:

```text
idempotentHint=true
Agent retry=idempotent
```

---

## 6. Pure read tools

Безусловно safe read class остаётся только для operations без resource/cost/side-effect ambiguity, например:

```text
content_get
browser_get
browser_snapshot
browser_tabs
browser_events
browser_wait
job_get
```

Даже для них server deadlines/capacity/rate policy остаются обязательными.

---

## 7. Resource creation tools

Любая explicit resource creation baseline conservative:

```text
web_fetch_job
content_parse_job
browser_create
browser_page_create
browser_content
browser_screenshot
```

если нет отдельного request idempotency contract.

REST creation endpoints могут иметь спроектированный `Idempotency-Key`; MCP core baseline не получает generic idempotency-key argument.

---

## 8. Browser mutating actions

ADR не меняет existing rule:

```text
navigate/click/fill/type/press/hover/drag/upload
→ no blind retry after dispatch uncertainty
```

Worker action ledger/status recovery сначала пытается доказать исход того же action ID; новый action call не является retry того же side effect автоматически.

---

## 9. Cost vs idempotency

`idempotent` в математическом/HTTP смысле не означает «бесплатно повторять».

Например два одинаковых Search requests могут вернуть тот же логический result, но дважды потребить billable unit.

Поэтому own Agent Dispatcher должен иметь возможность хранить retry/cost class отдельно от базовых MCP annotations.

---

## 10. Требования к документации/тестам

- `contracts/mcp-tools.md` execution table обновляется;
- agent trusted descriptors для Web Access используют conservative cost/resource semantics;
- `web_fetch` response-loss test не создаёт blind duplicate через Agent;
- `web_search` billable provider response-loss test не вызывает второй Agent-level paid call автоматически;
- `content_parse` idempotent classification разрешается только после canonical reuse concurrency/replay tests;
- REST docs не рекомендуют generic automatic retry request-bound resource-creating operations без idempotency contract.
