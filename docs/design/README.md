# Design-документация Web Access MCP

## Назначение

`docs/design/` — каноническое место архитектурной, contract и version-документации проекта.

Иерархия:

```text
Concept
→ Design semantics/invariants
→ ADR
→ exact public contracts
→ version implementation plans
→ generated runtime contract fixtures / release evidence
```

`current.md` показывает фактический статус и следующий допустимый шаг.

---

# 1. Навигация

## Concept

- `../project-concept.md`;
- `../architecture-concept.md`.

## Governance/status

- `documentation-plan.md`;
- `current.md`;
- `../AGENTS.md`.

## Foundation

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

## ADR

- `decisions/README.md`;
- `decisions/ADR-xxxx-*.md`.

## Exact public contracts

Index: `contracts/README.md`.

Current specs:

```text
contracts/common-models.md
contracts/mcp-tools.md
contracts/rest-api-v1.md
contracts/browser-api-v1.md
contracts/policy-models.md
contracts/admin-api-v1.md
```

## Versions

- `versions/README.md`;
- `versions/v0.1/` … `versions/v1.0/`.

---

# 2. Канонический владелец темы

У архитектурной нормы один основной owner.

Examples:

```text
operation/outcome/retry/batch
→ application-contracts.md

resource ownership/lifecycle
→ resource-model.md

PostgreSQL/Redis/ContentStore consistency
→ persistence.md

Search semantics
→ search.md

Browser semantics
→ browser.md + Browser ADR

policy/quota/operator semantics
→ policy-and-operations.md + ADR-0019/0020/0023

MCP semantic facade
→ mcp.md

exact MCP DTO
→ contracts/mcp-tools.md

REST semantics
→ rest-api.md

exact normal REST
→ contracts/rest-api-v1.md

exact Browser REST
→ contracts/browser-api-v1.md

exact dynamic policy
→ contracts/policy-models.md

exact Admin REST
→ contracts/admin-api-v1.md

implementation order
→ versions/<version>/implementation-sequence.md
```

Более общий документ не переопределяет более специфичный exact contract; exact contract не отменяет lifecycle/security semantics Design/ADR.

---

# 3. Backend-first invariant

Любая capability:

```text
предметная задача
→ domain/application semantics
→ ports
→ infrastructure/runtime
→ tests
→ REST projection
→ MCP projection
```

REST/MCP share backend; transport schemas могут различаться.

---

# 4. Contract discipline

Exact public spec создаётся только после semantic design.

Обязательные свойства:

- exact required/default/bounds;
- discriminated unions/cross-field invariants;
- explicit null/omission semantics;
- unknown fields rejected;
- no infrastructure/provider/worker leakage;
- structured errors;
- bounded result;
- compatibility classification.

Current MCP target = **28 semantic tools**.

Current REST target split by specificity:

```text
rest-api-v1.md
+ browser-api-v1.md
+ admin-api-v1.md/policy-models.md
```

---

# 5. ADR/current precedence

Если evidence меняет принятое решение:

1. create/update/supersede ADR;
2. update canonical Design owner;
3. update exact contracts;
4. update version plans;
5. update tests/gates/status.

Не оставлять два одновременно «правильных» варианта.

Examples already applied:

- ADR-0012 partially superseded by ADR-0013;
- ADR-0022 partially refined/superseded by ADR-0024/0025;
- dynamic task policy admin self-lockout removed by ADR-0023.

---

# 6. Documentation for coding agents

Implementation-ready docs должны исключать архитектурные догадки.

Нужны:

- responsibilities/non-goals;
- state/lifecycle;
- persistence/concurrency;
- retry/idempotency/unknown outcome;
- security;
- exact facade schemas;
- required tests;
- acceptance gates.

Если решение не принято — оно blocker/open question, а не «сделать как удобнее».

---

# 7. Generated executable contracts

В v0.8 фактическая реализация генерирует:

```text
FastAPI OpenAPI
actual FastMCP schemas/annotations
common serialized error/resource fixtures
```

Они:

- сравниваются с `contracts/*`;
- сохраняются как golden fixtures;
- получают CI-visible diff;
- меняются только через compatibility review.

---

# 8. Текущее состояние

Design первой v1.0 line сформирован; production implementation ещё не начат.

После финального consistency check новый feature-design следует остановить и переходить к реализации **только v0.1 Service Foundation**.

Подробнее: `current.md`.
