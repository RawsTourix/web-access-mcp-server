# ADR-0016 — S3-compatible ContentStore: boto3 adapter с тем же staging/finalization lifecycle

**Статус:** accepted

## 1. Контекст

v0.1/v0.3 имеют `ContentStore` port и filesystem implementation.

Для multi-replica/production deployment нужен shared object storage, чтобы:

- любой Control Plane replica мог читать ContentObject;
- Browser/Job results не зависели от local disk одного API container;
- replicas могли масштабироваться stateless относительно blob bytes;
- retention/backup/storage policy отделялись от application process.

Application lifecycle уже определён ADR-0007:

```text
ContentObject creating
→ staging bytes
→ persist hash/size
→ physical finalize
→ DB available
```

S3 adapter не должен менять эту semantics.

---

## 2. Решение

Добавить:

```text
S3CompatibleContentStore
```

на базе официального AWS SDK for Python:

```text
boto3 / botocore
```

Adapter поддерживает Amazon S3 и совместимые object stores, которые реализуют необходимый subset API.

Application/API не зависит от конкретного vendor.

---

## 3. Почему boto3

- официальный AWS Python SDK;
- зрелая S3 API support;
- multipart upload/download support;
- configurable endpoint для S3-compatible services;
- stable botocore retry/signing/TLS behavior;
- меньше dependency/maintenance risk, чем выбор неофициального async wrapper как core storage dependency.

---

## 4. Async application boundary

Boto3 является blocking SDK.

`ContentStore` application port остаётся async-friendly.

Concrete S3 adapter выполняет blocking network/file-transfer operations через **отдельный bounded thread executor**, не default unbounded/shared executor event loop.

Концептуально:

```text
async ContentApplication
→ S3ContentStore
→ bounded S3 I/O executor
→ boto3
```

Requirements:

- fixed/configurable max workers;
- admission/backpressure;
- cancellation/deadline awareness между transfer phases;
- no blocking boto3 call directly в asyncio event loop;
- metrics queue/in-flight/latency.

---

## 5. Configuration

`ContentStoreSettings` S3 profile содержит server-controlled:

```text
backend = s3
bucket
prefix
region
endpoint_url | null
access key/secret/session credential references or workload credentials
TLS/CA settings
transfer concurrency/part size
executor concurrency
```

Client/MCP не выбирает bucket/endpoint/key.

Secrets скрыты из logs/status/public config.

---

## 6. Object namespace

Logical namespace соответствует ADR-0007.

Пример:

```text
<prefix>/staging/<content_id>/<random-token>.part
<prefix>/blobs/sha256/ab/<full-sha256>
```

Public ContentRef не содержит S3 key.

---

## 7. Stage write

`stage_write` получает bounded byte stream.

Adapter:

1. создаёт staging key;
2. streaming/multipart upload в staging object;
3. параллельно application/source layer вычисляет/передаёт expected hash и size либо adapter вычисляет их через staging local stream wrapper;
4. закрывает multipart upload только после успешной передачи всех частей;
5. возвращает opaque staging handle/stat.

Не буферизовать целый large ContentObject в RAM.

---

## 8. Multipart uploads

Для объектов выше configured threshold использовать S3 multipart upload/managed transfer.

Requirements:

- bounded part/concurrency;
- abort multipart upload на failure/cancellation where possible;
- stale multipart uploads имеют lifecycle/cleanup policy на bucket/service уровне;
- upload ID никогда не становится public handle;
- incomplete multipart audit/reconciliation observable.

Bucket lifecycle rule для abort incomplete multipart uploads рекомендуется как defense in depth.

---

## 9. Final key

Final physical key content-addressed:

```text
blobs/sha256/<prefix>/<sha256>
```

Logical ContentObject owner isolation остаётся PostgreSQL/resource layer.

Один physical object может обслуживать несколько logical ContentObjects с одинаковыми bytes без cross-owner disclosure.

---

## 10. S3 finalize

S3 не имеет POSIX rename.

`finalize(staging, expected_sha256, expected_size)` выполняет:

1. HEAD final key;
2. если compatible final уже существует → reuse;
3. иначе copy staging object → final key;
4. verify final HEAD metadata/size according integrity policy;
5. delete staging object best effort;
6. вернуть finalized storage handle.

Для размера, где обычный `CopyObject` недостаточен/неоптимален, adapter использует multipart copy/managed equivalent.

Application protocol ADR-0007 не меняется.

---

## 11. Concurrent identical finalize

Два concurrent writers одного hash могут одновременно попытаться publish final key.

Correctness requirement:

- final bytes immutable by hash identity;
- оба writers ожидают одинаковый SHA-256/size;
- successful identical object acceptable;
- mismatch/corruption → integrity error;
- никто не должен silently overwrite hash key несовместимыми bytes.

Adapter не полагается на logical ContentObject uniqueness.

---

## 12. Hash integrity

SHA-256 application metadata является canonical content hash.

S3 ETag **не считается универсальным content MD5**, особенно для multipart uploads.

Нельзя использовать ETag вместо SHA-256 integrity.

При upload/finalization сохраняются expected SHA-256/size в DB и optionally object metadata/tags where useful.

---

## 13. Encryption

Baseline production:

- TLS in transit;
- server-side encryption configured bucket/provider side.

Поддержка SSE-S3/SSE-KMS или S3-compatible equivalent задаётся operator settings.

Raw encryption keys не передаются через application/MCP.

Client-side encryption является отдельным future design, если потребуется.

---

## 14. Credentials

Preferred production order:

1. workload/instance/task identity where platform supports it;
2. mounted secret/environment credentials;
3. static local test credentials only в controlled profile.

ContentStore credentials доступны Control Plane/Job components, которым реально нужен storage, но **не Browser session subprocess** согласно ADR-0013.

---

## 15. Read

`open/read` должен поддерживать bounded streaming.

Application cursor/range semantics могут использовать S3 Range requests, если это корректно для requested Content representation.

Не требуется скачивать весь object для чтения небольшого range.

Read validates owner/resource in application layer before adapter access.

---

## 16. Delete/GC

Logical delete/expiration сначала меняет PostgreSQL resource lifecycle.

Physical hash object удаляется только GC после проверки, что active logical references отсутствуют.

S3 adapter:

- delete final object idempotent;
- tolerate already-missing object as appropriate;
- report permission/storage failures;
- no bucket-wide destructive operation from ordinary application path.

---

## 17. Reconciliation

Content reconciler должен работать одинаково для filesystem/S3:

- stale creating;
- known staging object;
- final exists but DB not available;
- available DB row but final missing;
- orphan staging;
- unreferenced final after grace.

S3 listing может быть дорогим, поэтому normal reconciliation предпочтительно идёт от durable DB metadata/staging prefixes in bounded batches; full storage inventory — maintenance task, не request path.

---

## 18. S3-compatible compatibility

Не каждый «S3-compatible» продукт идеально реализует все AWS details.

Release profile проверяет минимум:

- multipart upload;
- HEAD;
- GET/range;
- copy/finalize path;
- delete;
- list staging prefix where maintenance requires;
- TLS/auth;
- concurrent same-key behavior.

Reference local deployment может использовать MinIO или другой compatible service, но product brand не является application contract.

---

## 19. Local development

Filesystem ContentStore остаётся самым простым default local profile.

Дополнительный Compose profile должен позволить поднять S3-compatible test storage и прогнать adapter contract suite.

Это не означает обязательный object store для каждого developer run.

---

## 20. Retry semantics

S3 operations имеют bounded SDK/application retries только для transient safe phases.

Особое внимание:

- multipart part retry допустим по SDK semantics;
- finalize copy idempotent по expected hash/key;
- delete staging idempotent;
- DB `available` commit не повторяет whole upload без reconciliation check.

Deadline/cancellation не должны создавать бесконечный background transfer в executor.

---

## 21. Thread executor shutdown

Service shutdown:

- stop admission new transfers;
- bounded wait active critical transfer phase;
- cancel queued tasks;
- close boto3 clients/resources as applicable;
- shutdown dedicated executor;
- unfinished staging остаётся reconciler/lifecycle-visible.

No process exit with hidden unbounded transfer threads.

---

## 22. Metrics

Минимально:

- active/queued S3 operations;
- upload/download bytes;
- multipart count;
- staging/finalize latency;
- copy/reuse rate;
- SDK retries;
- S3 errors by normalized class;
- executor saturation;
- orphan staging cleanup;
- integrity failures.

Bucket/key/content IDs не используются как high-cardinality metric labels.

---

## 23. Tests

Contract suite должна прогоняться против filesystem и S3-compatible adapter.

S3-specific:

1. small stage/finalize/read;
2. multipart stage;
3. cancellation/abort;
4. duplicate same-hash finalize;
5. concurrent same-hash finalize;
6. final exists/reuse;
7. final mismatch/integrity failure fixture;
8. crash between copy and DB available via application fault injection;
9. orphan staging cleanup;
10. range read;
11. missing final object;
12. credential/permission failure;
13. endpoint/TLS failure;
14. bounded executor saturation/backpressure;
15. service shutdown with active transfer;
16. multiple API replicas share same ContentObject.

---

## 24. Consequences

Плюсы:

- production shared blob storage;
- official SDK;
- same application lifecycle as filesystem;
- multi-replica Content access;
- multipart support;
- S3-compatible deployment flexibility.

Минусы:

- blocking boto3 requires dedicated thread executor;
- object-store finalize сложнее rename;
- copy/multipart/reconciliation adds I/O/cost;
- S3-compatible implementations require contract testing.

Trade-off принимается ради mature official SDK и сохранения чистого application port.

---

## 25. Не определяется

- конкретный production object storage vendor;
- exact bucket name/prefix;
- exact multipart threshold/part size;
- exact encryption policy vendor-side;
- MinIO version;
- backup/replication lifecycle;
- CDN/public URL generation.

Никакой ContentObject baseline не становится публично доступным через unsigned S3 URL.
