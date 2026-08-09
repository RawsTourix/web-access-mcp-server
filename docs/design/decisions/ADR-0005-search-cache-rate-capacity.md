# ADR-0005 — Search cache, rate limiting и provider capacity

**Статус:** accepted

## 1. Контекст

Search должен:

- уменьшать повторные provider calls;
- не превышать provider rate limits;
- не создавать burst при нескольких API replicas;
- учитывать billable Yandex usage;
- не смешивать cache/rate/capacity в одну primitive;
- сохранять privacy search queries.

---

## 2. Решение — три независимых механизма

```text
SearchCache
ProviderRateLimiter
ProviderConcurrencyLimiter
```

Они имеют разные semantics и отдельные ports/policies.

---

## 3. SearchCache

Baseline backend:

```text
Redis
```

Cache хранит **normalized SearchQueryResult provider response**, достаточный для возврата клиенту без нового upstream call.

Не кэшируется raw credential/provider client object.

---

## 4. Cache key

Raw query text не используется непосредственно как Redis key.

Формируется canonical cache request representation:

```text
provider_id
provider/config revision
query
page
limit
language
region
safe_search
time_range
Search normalization/cache schema revision
cache scope principal/shared
```

Затем key строится через cryptographic hash canonical serialization.

Это:

- уменьшает утечку query через Redis tooling/key listing;
- даёт stable bounded keys;
- позволяет version invalidation.

Hash не является security encryption: cache access всё равно защищается Redis network/auth policy.

---

## 5. Cache scope default

Baseline:

```text
principal-scoped cache
```

`principal_id`/derived opaque scope участвует в cache identity.

Причина: search query может быть чувствительной, а response metadata `cached=true` в shared cache способна стать межпринципным timing/existence side-channel.

---

## 6. Shared cache — optional policy

Operator позднее может включить:

```text
shared_public
```

для deployments, где клиенты принадлежат одной trust domain и экономия provider calls важнее query isolation.

Это explicit configuration policy, а не default.

MCP/REST caller не выбирает cache scope произвольно.

---

## 7. Cache TTL

TTL задаётся provider/search policy configuration.

Не хардкодится в application logic.

Разные providers могут иметь разные TTL из-за:

- freshness;
- cost;
- rate limits.

Response всегда отражает original `retrieved_at` и `cached=true`.

---

## 8. Cache serialization

Cache value имеет versioned typed schema.

Предпочтительно JSON/msgpack-like safe serialization без `pickle`.

`pickle` запрещён для Redis data, который потенциально может быть corrupted/untrusted, из-за code execution risk.

Точный encoder фиксируется implementation; JSON является baseline preference.

---

## 9. Cache corruption

Если cache value:

- невалиден;
- schema revision unknown;
- parse failed,

он считается cache miss, удаляется/инвалидируется best effort и не ломает Search operation, если provider доступен.

Corruption metric/log emitted без содержимого query/value.

---

## 10. Stampede protection

Одновременные identical misses не должны создавать N provider calls по возможности.

SearchCache layer может использовать bounded distributed single-flight/short lock на cache key.

Requirements:

- lock short-lived/lease-based;
- потеря lock не нарушает correctness;
- client deadline respected;
- если wait слишком долгий, policy может выполнить independent provider call или вернуть capacity error согласно config;
- Redis lock не является durable business invariant.

Точная implementation фиксируется v0.2 sequence.

---

## 11. Rate limiting

ProviderRateLimiter ограничивает **частоту фактических upstream query calls**, а не количество HTTP/MCP requests к Web Access.

Batch из 20 queries расходует 20 provider rate units, если все дошли до upstream.

Cache hit rate unit не расходует.

---

## 12. Distributed token bucket

Baseline algorithm:

```text
Redis-backed token bucket
```

Atomic update через Lua/script/server-side atomic primitive.

Key scope conceptually:

```text
provider
+
principal/deployment policy scope
```

Policy fields:

```text
capacity (burst)
refill rate
cost per query
```

Exact numbers configurable.

---

## 13. Why token bucket

По сравнению с простым fixed-window `INCR` token bucket:

- контролирует average rate;
- позволяет bounded burst;
- не создаёт двойной burst на границе window;
- естественно возвращает estimated retry-after.

---

## 14. Provider global vs principal rate

Могут существовать одновременно:

```text
principal/provider bucket
provider/global bucket
```

Query разрешён только если оба допускают call.

Это позволяет защищать:

- quota клиента;
- общий provider credential/upstream limit.

Reservation обоих buckets должна быть спроектирована атомарно/компенсируемо; первая реализация может использовать одну Lua operation над совместимыми keys одного Redis instance.

---

## 15. Rate limit failure

Если token недоступен:

```text
outcome/error = rate_limited
```

и возвращается `retry_after` только если limiter способен вычислить его корректно.

Search не переключает provider автоматически.

Можно вернуть hint об альтернативном enabled provider, если это objective capability information и policy это разрешает.

---

## 16. Redis outage и rate enforcement

Для provider, где rate/budget enforcement является обязательным safety/cost control:

```text
Redis rate limiter unavailable
→ fail closed для новых upstream calls
```

Нельзя silently bypass limiter.

Cache может деградировать в miss, но rate enforcement — отдельное решение.

Для локального/test provider explicit config может разрешать local fallback limiter, но production default — fail closed.

---

## 17. Concurrency limit

Rate limit не ограничивает количество одновременно открытых slow upstream requests.

Поэтому существует отдельный:

```text
ProviderConcurrencyLimiter
```

который ограничивает in-flight provider calls.

---

## 18. Baseline concurrency implementation

Для v0.2 принимается двухуровневая модель:

```text
per-replica asyncio semaphore
+
Redis distributed lease semaphore для provider global cap
```

Если distributed global cap не нужен configured provider profile, можно использовать только local cap.

Billable/default production provider должен иметь explicit global capacity policy.

---

## 19. Distributed semaphore

Redis lease semaphore requirements:

- unique holder token per upstream call;
- TTL/lease;
- atomic acquire;
- release only by holder;
- expired holder освобождает slot после worker crash;
- bounded wait/deadline;
- no unbounded queue in API memory.

Это operational coordination, не durable Resource.

Точная Lua/Redis data structure фиксируется implementation tests.

---

## 20. Lease duration

Lease должна покрывать provider max call deadline + safety margin.

Если request длится дольше, implementation либо renew lease, либо использует deadline, гарантированно короче lease.

Нельзя позволить lease expire во время ещё живого provider call и тем самым превысить global concurrency cap.

---

## 21. Capacity outcome

Если concurrency slot нельзя получить до bounded admission timeout/deadline:

```text
provider_capacity_unavailable
```

Это отличается от rate limit.

Retryability зависит от remaining deadline/policy.

---

## 22. Order of execution

Canonical Search provider flow:

```text
validate/capabilities
→ cache lookup
→ optional single-flight
→ rate-limit reservation
→ concurrency slot
→ provider call
→ accounting
→ normalize
→ cache write
→ release slot
```

Implementation может оптимизировать порядок reservation/slot acquisition, но не должен расходовать billable/rate unit для cache hit.

---

## 23. Cancellation

Если request cancelled:

- waiting rate/capacity stops;
- acquired concurrency lease released;
- provider call cancelled where possible;
- rate token уже consumed может не возвращаться, потому что reservation отражает фактическую admission к upstream attempt; exact refund policy не должна создавать возможность abuse/double-spend.

Baseline: consumed rate token не refund автоматически.

---

## 24. Billing accounting relationship

Rate token consumption ≠ подтверждённый billable charge.

Accounting отдельно фиксирует actual upstream attempt/result.

Cache hit:

```text
rate token = 0
concurrency slot = 0
billable call = 0
```

---

## 25. Cache write failure

Если provider call успешен, но Redis cache write failed:

- Search result остаётся `succeeded`;
- warning/telemetry cache unavailable по необходимости;
- billable/provider result не теряется;
- следующий identical request может снова вызвать provider.

Cache не является correctness dependency.

---

## 26. Rate limiter state privacy

Rate keys не содержат raw query.

Principal scope uses opaque/stable identifier/fingerprint, а не Bearer token.

Metrics labels не содержат principal ID при unbounded cardinality.

---

## 27. Tests

Обязательны:

- principal cache isolation;
- optional shared cache;
- cache key revision invalidation;
- corrupted cache value;
- identical miss single-flight;
- batch query costs N units;
- cache hit costs 0;
- token bucket refill/burst;
- boundary timing;
- global + principal limit;
- Redis failure fail-closed for rate;
- distributed concurrency across multiple simulated replicas;
- lease expiry after crash;
- holder-only release;
- cancellation release;
- no unbounded waiting.

---

## 28. Consequences

Плюсы:

- predictable multi-replica provider behavior;
- Yandex cost protected;
- cache/privacy boundary explicit;
- rate и concurrency не смешаны;
- Redis outage behavior deterministic;
- no hidden provider fallback.

Минусы:

- Redis становится required dependency для production provider calls с mandatory rate enforcement;
- distributed semaphore/Lua scripts требуют careful race testing;
- principal-scoped cache уменьшает cross-user hit ratio.

Эти trade-offs принимаются ради correctness/privacy/cost control.

---

## 29. Не определяется

- конкретные refill rates/capacity;
- exact Redis key format;
- exact Lua scripts;
- cache TTL values;
- initial shared cache policy;
- exact single-flight wait policy.

Они конфигурируются/фиксируются v0.2 implementation sequence и load/provider constraints.
