# ADR-0007 — Content creation: durable creating state + staged blob + explicit finalization

**Статус:** accepted

## 1. Контекст

ContentObject metadata находится в PostgreSQL, payload — в ContentStore.

Одной atomic transaction между PostgreSQL и filesystem/S3 нет.

Нужно корректно переживать crash в любой точке:

- resource ID создан, bytes ещё не записаны;
- staging bytes записаны, metadata не обновлена;
- final blob опубликован, DB update потерян;
- два identical payload создаются concurrently;
- cleanup/reconciler работает параллельно create.

---

## 2. Решение

ContentObject создаётся через explicit lifecycle:

```text
creating
→ available
```

с intermediate durable staging metadata и reconciler.

Physical payload использует content-addressed SHA-256 final key, но logical ContentObject остаётся отдельным owner-scoped Resource.

---

## 3. Creation protocol

### Step 1 — reserve logical resource

PostgreSQL transaction:

```text
INSERT ContentObject(
  content_id,
  owner,
  state=creating,
  representation metadata/provenance intent,
  created_at,
  creation_revision
)
```

Commit.

Public callers не могут читать `creating` payload как available Content.

### Step 2 — stage stream

ContentStore:

```text
stream source
→ staging object/key scoped to content_id/creation token
→ incremental sha256
→ byte count
→ staged metadata
```

No full buffering.

### Step 3 — persist staged metadata

PostgreSQL transaction CAS current `creating` revision:

```text
staging_key (internal)
sha256
size
staged_at
```

Commit.

### Step 4 — finalize physical blob

ContentStore atomically/idempotently promotes staging to:

```text
blobs/sha256/<prefix>/<sha256>
```

Если identical final blob уже существует и integrity совпадает, physical blob reuse разрешён.

### Step 5 — publish logical resource

PostgreSQL transaction CAS:

```text
state = available
storage_key = final hash key
staging_key = null
available_at
```

и при необходимости provenance edges/derived representation metadata, которые должны стать visible вместе с resource.

Commit.

Только после Step 5 normal read возвращает ContentObject.

---

## 4. Почему resource row создаётся до blob

Это даёт durable identity и owner/lifecycle record для reconciliation.

Crash после Step 1 виден как stale `creating` row вместо completely invisible orphan workflow.

Для Browser/Job result можно заранее связать ожидаемый content_id с operation/action metadata.

---

## 5. Crash windows

### После Step 1

DB row `creating`, staging отсутствует.

Reconciler после creation timeout:

```text
→ failed/deleted according retention policy
```

### После Step 2 до Step 3

Staging object может быть orphan без DB staging_key.

Staging namespace имеет TTL/age cleanup; key содержит non-secret creation identity/random token.

### После Step 3 до Step 4

DB знает staging object. Reconciler может retry finalize или cleanup according state/policy.

### После Step 4 до Step 5

Final content-addressed blob существует, DB всё ещё `creating` со staging/hash metadata.

Finalize idempotent; reconciler повторяет Step 4/5 и публикует resource, если integrity подтверждена.

### После Step 5

Resource authoritative `available`.

Late cleanup stale staging token не должен удалить final shared blob.

---

## 6. Finalization idempotency

`ContentStore.finalize(staging, sha256)` должен быть idempotent.

Если final key существует:

- stat/integrity check expected size/hash where feasible;
- если compatible → staging removed/acknowledged;
- если inconsistent → integrity failure, existing blob не перезаписывается silently.

---

## 7. Physical dedup vs logical ownership

Два principals могут иметь:

```text
cnt_A owner=A → storage_key sha256:X
cnt_B owner=B → storage_key sha256:X
```

Они остаются разными ContentObjects.

Authorization проверяет logical resource.

Physical blob может храниться один раз.

Никогда не возвращать «у другого principal уже есть этот hash» как cross-owner information.

---

## 8. Blob deletion

Удаление logical ContentObject не удаляет final hash blob немедленно без проверки references.

Physical GC:

1. определяет, есть ли active/non-deleted ContentObject refs на storage key;
2. если refs нет и retention/grace прошёл → remove blob;
3. concurrent creation/finalization защищается grace/CAS/recheck.

Не нужен mutable reference counter как единственный source of truth; authoritative refs можно проверить PostgreSQL query/reconciliation.

---

## 9. Staging keys

Staging key не является local filesystem path public contract.

Conceptual namespace:

```text
staging/<content_id>/<random-token>.part
```

Filesystem/S3 adapter маппит это во внутреннюю storage semantics.

Raw staging key допускается только internal persistence/debug with redaction as needed.

---

## 10. Provenance

Для derived ContentObject source relation может быть записана на Step 1 как intended source reference, но считается published relation только когда derived object `available`.

Если creation fails, source не должен показывать failed object как доступную representation.

Query available representations фильтрует по `state=available`.

---

## 11. Derived reuse

Перед созданием derived representation ContentApplication может проверить existing compatible available representation:

```text
source_content_id
parser_id/revision
representation schema revision
parameters hash
owner/access policy
```

Если найдено — вернуть existing ContentRef.

Если нет — создать новое `creating` resource.

Concurrent duplicate creates допустимы; physical dedup + позже optional logical uniqueness constraint/reconciliation может сократить дубли. Нельзя вводить global cross-owner unique logical row.

---

## 12. Cancellation

Cancellation до Step 5:

- operation прекращает дальнейший processing;
- `creating` row помечается failed/cancelled-internal или оставляется reconciler-visible according transaction stage;
- staging cleanup best effort;
- final blob, если уже опубликован, GC-ится только после ref check/grace.

Client не получает available ContentRef.

---

## 13. ContentStore port requirements

Нужны operations semantics:

```text
stage_write(stream, staging_identity)
stat_staging
finalize(staging_handle, expected_sha256, expected_size)
open(final_key)
stat(final_key)
remove_staging
remove_final
```

Exact method names могут отличаться.

Application не получает filesystem path.

---

## 14. Filesystem adapter

Использует same-filesystem staging/final root и atomic rename/replace semantics.

Final path content-addressed.

Concurrent same-hash finalize tested.

---

## 15. S3-compatible adapter

Поздний adapter использует object keys того же logical namespace.

S3 rename отсутствует, поэтому finalize реализуется copy/conditional put/head + staging delete/idempotency по object-store semantics.

Application lifecycle остаётся тем же, хотя physical finalize не POSIX rename.

---

## 16. Reconciler

Content reconciler периодически обрабатывает bounded batches:

- stale creating no staging;
- creating with known staging;
- creating where final blob already exists;
- old orphan staging keys;
- available metadata with missing final blob;
- unreferenced final blobs after grace/GC policy.

Multiple reconcilers должны быть idempotent/concurrency-safe.

---

## 17. `available` integrity

Read available ContentObject:

- metadata указывает final storage key;
- ContentStore open/stat должен подтвердить наличие;
- optional hash verification policy для critical reads/background audit.

Если blob missing/corrupt:

```text
resource/storage integrity failure
```

а не empty successful content.

---

## 18. Database states

Exact Content lifecycle enum finalizes in v0.3 implementation, но minimum internal states нужны:

```text
creating
available
failed/deleted/expired согласно resource lifecycle
```

`staged` можно хранить как fields/phase внутри `creating`, а не обязательно отдельный public resource state.

---

## 19. Tests

Fault matrix:

1. crash after row create;
2. crash after staging before DB staging update;
3. crash after DB staging update;
4. crash after physical finalize before available commit;
5. duplicate finalize;
6. two owners same bytes;
7. two same-owner concurrent derived parse;
8. cancellation each phase;
9. reconciler vs active creation;
10. GC vs new reference;
11. final blob missing/corrupt;
12. ContentStore transient failure.

---

## 20. Consequences

Плюсы:

- явные crash windows;
- durable reconciliation identity;
- filesystem/S3 one application contract;
- physical dedup без authorization leak;
- Browser/Retrieval/Jobs создают Content одинаково;
- no giant DB blobs.

Минусы:

- создание ContentObject требует нескольких steps/transactions;
- нужен reconciler;
- orphan storage lifecycle сложнее простого `write file`;
- available latency чуть выше из-за metadata stages.

Trade-off принимается ради fault tolerance/scaling.

---

## 21. Acceptance

1. Content never public `available` до finalized payload metadata commit.
2. Каждый crash window восстанавливается/reconciles.
3. Public result не содержит staging/final local path.
4. Same bytes across owners не объединяют logical ownership.
5. Finalize idempotent.
6. Reconciler multi-instance safe.
7. Filesystem adapter atomic publication tested.
8. S3 adapter later может реализовать same lifecycle без application rewrite.
