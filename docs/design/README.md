# Design-документация Web Access MCP

## Назначение

`docs/design/` — каноническое место полноценной архитектурной, contract и version-документации проекта `web-access-mcp-server`.

Уровни документации:

```text
Concept
→ Design
→ ADR
→ exact public contracts
→ Version implementation plans
→ generated runtime contract fixtures / release evidence
```

Concept отвечает на вопрос **«что строим и почему»**.

Design — **«как система должна быть устроена»**.

ADR — **«какое значимое решение выбрано между альтернативами»**.

`contracts/` — **«какая точная public DTO/schema должна получиться»**.

Versions — **«что реализуем в конкретном milestone и в каком порядке»**.

---

# 1. Навигация

## Concept

- `../project-concept.md`;
- `../architecture-concept.md`.

## Governance/status

- `documentation-plan.md` — правила и первоначальный порядок проектирования;
- `current.md` — фактический текущий статус и следующий допустимый шаг;
- `../AGENTS.md` — обязательные правила для Codex/ChatGPT coding work.

## Cross-cutting foundation

- `principles.md`;
- `glossary.md`;
- `dependency-rules.md`;
- `system-context.md`;
- `runtime-topology.md`;
- `application-contracts.md`;
- `resource-model.md`;
- `persistence.md`;
- `security.md`.

## Components

- `search.md`;
- `retrieval.md`;
- `content.md`;
- `browser.md`;
- `jobs.md`.

## Operations/facades/release

- `observability.md`;
- `policy-and-operations.md`;
- `rest-api.md`;
- `mcp.md`;
- `compatibility.md`;
- `agent-integration.md`;
- `deployment.md`;
- `testing.md`;
- `release-gates.md`;
- `operational-readiness.md`;
- `limitations.md`;
- `roadmap.md`.

## Decisions

- `decisions/README.md` — ADR registry;
- `decisions/ADR-xxxx-*.md` — individual decisions.

## Exact public contracts

- `contracts/README.md`;
- `contracts/common-models.md`;
- `contracts/mcp-tools.md`;
- `contracts/rest-api-v1.md`.

## Versions

- `versions/README.md`;
- `versions/v0.1/` … `versions/v1.0/`.

---

# 2. Канонический владелец темы

У каждой нормы должен быть один владелец.

Примеры:

```text
retry/outcome/batch semantics
→ application-contracts.md

resource ownership/lifecycle
→ resource-model.md

PostgreSQL/Redis/ContentStore consistency
→ persistence.md

Search provider semantics
→ search.md

Browser lifecycle/action semantics
→ browser.md + accepted Browser ADR

MCP semantic catalog
→ mcp.md + ADR-0022

exact MCP DTO/schema
→ contracts/mcp-tools.md

REST semantic facade
→ rest-api.md

exact REST v1 DTO/routes
→ contracts/rest-api-v1.md

implementation order
→ versions/<version>/implementation-sequence.md
```

Другие документы могут ссылаться/кратко повторять контекст, но не должны независимо переопределять contract.

---

# 3. Backend-first invariant

Любая capability проектируется и реализуется в направлении:

```text
предметная задача
→ domain/application semantics
→ ports
→ infrastructure/runtime
→ tests
→ REST projection
→ MCP projection
```

Не наоборот.

REST и MCP используют один application backend, но имеют разные transport-facing DTO и разную granularity.

---

# 4. Public contracts

После определения semantics точные schemas фиксируются в `contracts/`.

Contract spec обязан:

- не менять component lifecycle/security semantics;
- иметь exact bounds/defaults/required/union rules;
- описывать `null`/omission/default;
- не раскрывать infrastructure fields;
- быть пригодным для automatic schema contract tests.

В v0.8 generated runtime artifacts:

```text
OpenAPI
actual FastMCP tool schemas
common error/resource schemas
```

должны быть детерминированно получены из реальной реализации и сравнены с contract specs.

---

# 5. Документация для coding agents

Design намеренно пишется так, чтобы Codex/ChatGPT не пришлось угадывать архитектуру.

Обязательны:

- explicit responsibilities/non-goals;
- invariants;
- lifecycle/state transitions;
- retry/idempotency/unknown-outcome semantics;
- persistence/concurrency boundaries;
- security rules;
- exact public schemas там, где facade уже спроектирован;
- required tests;
- binary acceptance criteria.

Если решение ещё не принято, оно должно быть open question/ADR blocker. Нельзя оставлять фразу «сделать как лучше» в implementation-ready version.

---

# 6. Изменение принятого design

Если новое evidence требует изменить архитектуру:

1. найти canonical owner;
2. обновить/создать ADR при значимом выборе;
3. обновить owner document;
4. обновить dependent public contracts;
5. проверить roadmap/version plans;
6. обновить tests/gates;
7. не оставлять старый competing contract как будто он всё ещё актуален.

Superseded ADR сохраняется как история, но явно помечается.

---

# 7. Текущее состояние

Архитектурный design v0.1→v1.0 первой stable line сформирован.

Точные MCP и REST v1 contract specs также сформированы.

Production implementation ещё не начата; актуальный следующий шаг — `v0.1 Service Foundation` после финального consistency check.

Подробности: `current.md`.
