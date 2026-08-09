# ADR-0021 — MCP direct operations и durable Job creation используют разные tools

**Статус:** accepted

**Supersedes:** MCP projection choice в ADR-0018 §§24–26, где предлагался `execution=direct|durable` внутри `web_fetch`/`content_parse`.

## 1. Контекст

ADR-0018 правильно разделил request-bound execution и durable Job на backend/application уровне, но первоначально предложил сохранить один MCP tool с discriminator:

```text
web_fetch(execution=direct|durable)
content_parse(execution=direct|durable)
```

При compatibility review это оказалось плохой границей.

Builtin Agent Runtime хранит trusted tool execution metadata, включая:

- read-only/mutating/resource-creating class;
- retry policy;
- timeout profile;
- remote-resource behavior;
- presentation profile.

Эта metadata естественно привязана к **tool identity**.

`direct` и `durable` отличаются не только лимитом input:

```text
direct
→ request-bound operation
→ immediate content/result
→ safe/read-oriented retry semantics

job creation
→ durable Job Resource is created
→ returns JobRef
→ survives disconnect
→ response loss can create ambiguity about whether Job already exists
→ blind retry can create duplicate Job
```

Один tool с двумя execution classes делает trusted integration сложнее и менее точной.

---

## 2. Решение

MCP разделяет direct operation и explicit durable Job creation.

Canonical tools:

```text
web_fetch
web_fetch_job

content_parse
content_parse_job
```

Lifecycle:

```text
web_fetch
→ direct bounded result

web_fetch_job
→ creates retrieval_batch Job
→ returns JobRef

content_parse
→ direct bounded parse result

content_parse_job
→ creates content_parse_batch Job
→ returns JobRef
```

Job lifecycle далее:

```text
job_get
job_cancel
```

---

## 3. Почему это не повтор ошибки `read`/`read_many`

`web_fetch` vs `web_fetch_many` были бы одним и тем же intent/execution semantics и потому не нужны.

Здесь различие принципиальное:

```text
получить результат сейчас
vs
создать отдельный durable resource с собственным lifecycle
```

Это разные operation kinds, result contracts и retry semantics.

Поэтому два tools оправданы.

---

## 4. Naming

Используется suffix:

```text
*_job
```

а не:

```text
*_async
*_background
*_durable
```

Причины:

- явно сообщает, что result = Job Resource;
- совпадает с `job_get/job_cancel` lifecycle vocabulary;
- `async` двусмысленно как programming implementation;
- `background` не гарантирует durability;
- `durable` точный, но менее прикладной термин для LLM.

Description на русском подробно объясняет lifecycle.

---

## 5. `web_fetch`

Остаётся canonical direct stateless/batch-first tool.

Baseline:

```text
urls: 1..8
```

Он не принимает execution mode и не создаёт Job.

Если input слишком велик для direct contract:

- validation error;
- structured hint может рекомендовать `web_fetch_job`.

Service не переключает mode автоматически.

---

## 6. `web_fetch_job`

Назначение:

> Создать долговечную задачу получения большого набора известных HTTP(S)-URL. Возвращает `JobRef` сразу; выполнение продолжается независимо от текущего MCP-соединения. Для проверки результата используйте `job_get`.

Input baseline:

```text
urls: 1..256
```

Common agent-facing Retrieval options могут добавляться только если уже существуют stable application/MCP concepts.

No Browser/L2.

---

## 7. `content_parse`

Direct L1 Native Parsing existing ContentObjects.

Batch-first direct limit фиксируется version schema (v0.8 freeze baseline: 1..8 ContentObjects unless earlier implementation has stricter compatible limit).

No parser implementation ID.

No Job creation.

---

## 8. `content_parse_job`

Создаёт `content_parse_batch` Job.

Input:

```text
content_ids: 1..256
```

Возвращает JobRef.

No L2.

Existing compatible representations may be reused by Job handler.

---

## 9. Tool execution semantics

Now each tool has one stable trusted class.

### `web_fetch`

```text
read-oriented/safe
request-bound
no remote Job handle
```

### `content_parse`

```text
read-oriented / representation-producing
safe/idempotent according immutable source + representation reuse
request-bound
```

### `web_fetch_job`

```text
creates durable Job Resource
never blind automatic retry after uncertain call outcome
returns JobRef
```

### `content_parse_job`

Same resource-creating/never-blind-retry semantics.

### `job_get`

```text
read-only/safe
```

### `job_cancel`

```text
idempotent cancellation request
```

---

## 10. Lost response after Job creation

If caller loses response from `*_job`, it may not know JobRef.

Blind tool retry is forbidden by trusted semantics.

Future improvement may add explicit client idempotency key/call recovery protocol, but baseline does not collapse intentional duplicate Jobs by hidden input hash heuristic.

Own Agent Runtime may surface unknown resource-creation outcome according Dispatcher policy.

---

## 11. Structured hint from direct tool

When direct request violates direct-size/request-bound constraint, server can return trusted hint:

```text
processing_requires_job
related_capability/tool = web_fetch_job | content_parse_job
```

Because suggested tool is part of the same trusted service contract, exact recommendation is appropriate.

Hint does not invoke it automatically.

---

## 12. REST remains different

REST can keep explicit typed Job creation endpoints:

```text
POST /api/v1/jobs/retrieval-batches
POST /api/v1/jobs/content-parse-batches
```

No need to mirror MCP naming exactly.

REST request-bound retrieval/content endpoints remain separate.

---

## 13. Compatibility impact

ADR-0021 must be reflected in:

- `mcp.md`;
- v0.6 README/implementation sequence;
- v0.8 schema freeze;
- agent trusted descriptors.

Pre-implementation design change, so no backward runtime compatibility burden exists yet.

---

## 14. Tests

1. `web_fetch` schema has no execution discriminator;
2. `web_fetch` rejects > direct max and returns repairable error/hint;
3. `web_fetch_job` creates JobRef;
4. `content_parse` direct only;
5. `content_parse_job` creates JobRef;
6. `*_job` annotations/trusted integration marked resource-creating/never-blind-retry;
7. `job_get/job_cancel` lifecycle works;
8. descriptions clearly distinguish direct vs Job tool before schema retrieval;
9. no automatic direct→Job transition.

---

## 15. Consequences

Плюсы:

- one stable execution/retry class per MCP tool;
- simpler trusted Agent Dispatcher integration;
- easier descriptions/schemas;
- lost Job-create response treated honestly;
- no mixed result union;
- Job lifecycle obvious to LLM.

Минусы:

- two additional MCP tools;
- same broad business capability has direct and durable variants;
- caller must choose the correct lifecycle explicitly.

Trade-off accepted because execution lifecycle is a real semantic boundary, not accidental batching duplication.

---

## 16. Не определяется

- future client idempotency key for Job creation;
- automatic agent recovery of lost JobRef;
- future generic typed `job_start` union;
- native MCP Tasks projection.
