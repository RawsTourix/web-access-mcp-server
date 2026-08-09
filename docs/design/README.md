# Design-документация Web Access MCP

## Назначение

Каталог `docs/design/` является каноническим местом для **полноценной архитектурной и версионной документации** проекта `web-access-mcp-server`.

Документы верхнего уровня:

- `../project-concept.md` — общая концепция проекта и направление разработки;
- `../architecture-concept.md` — предварительная архитектурная концепция и предполагаемые границы модулей;
- `documentation-plan.md` — правила и порядок проектирования design-документации;
- `current.md` — текущее состояние проектирования и следующий канонический шаг.

Текущий архитектурный фундамент:

- `principles.md` — сквозные архитектурные инварианты;
- `glossary.md` — каноническая терминология;
- `dependency-rules.md` — направление зависимостей и module boundaries;
- `system-context.md` — граница системы и внешние actors;
- `runtime-topology.md` — process topology и runtime boundaries.

Concept-документы отвечают на вопрос **«что мы строим и в каком направлении»**.

Design-документы отвечают на вопрос **«как система должна быть устроена»**.

Version-документы отвечают на вопрос **«какую часть утверждённой архитектуры реализуем сейчас и в каком порядке»**.

---

## 1. Принцип канонического владельца темы

У каждой архитектурной темы должен быть один основной документ-владелец.

Другие документы могут:

- ссылаться на него;
- кратко повторять необходимый контекст;
- уточнять version-specific ограничения.

Они не должны заново определять тот же контракт независимо.

Примеры:

- общая retry/idempotency semantics принадлежит `application-contracts.md`, а не отдельно Search, Browser и MCP;
- ownership и lifecycle ресурсов принадлежат `resource-model.md`;
- общая persistence-модель принадлежит `persistence.md`;
- Search-specific ограничения принадлежат `search.md`;
- MCP agent-facing projection принадлежит `mcp.md`;
- порядок реализации конкретной версии принадлежит `versions/<version>/`.

Если одна и та же норма начинает независимо описываться в нескольких местах, документацию необходимо нормализовать и выбрать одного владельца.

---

## 2. Направление проектирования

Design-документация проектируется в следующем порядке:

```text
общие инварианты
→ system context
→ runtime topology
→ application contracts
→ resource/persistence/security foundation
→ Search / Retrieval / Content / Browser / Jobs
→ observability
→ REST API
→ MCP facade
→ deployment
→ testing and release gates
→ roadmap and versions
```

Нельзя начинать архитектуру с формы MCP-tool или REST endpoint, а затем подстраивать backend под транспорт.

Backend и application contracts проектируются первыми.

---

## 3. Предполагаемая структура

По мере проектирования каталог должен прийти примерно к следующему виду:

```text
docs/design/
├── README.md
├── documentation-plan.md
├── current.md
├── principles.md
├── glossary.md
├── dependency-rules.md
│
├── system-context.md
├── runtime-topology.md
├── application-contracts.md
├── resource-model.md
├── persistence.md
├── security.md
│
├── search.md
├── retrieval.md
├── content.md
├── browser.md
├── jobs.md
│
├── observability.md
├── rest-api.md
├── mcp.md
├── deployment.md
├── testing.md
├── release-gates.md
├── roadmap.md
│
├── decisions/
│   ├── README.md
│   └── ADR-xxxx-....md
│
└── versions/
    ├── README.md
    ├── v0.1/
    ├── v0.2/
    └── ...
```

Это целевая организационная модель документации, а не требование создать пустые файлы заранее.

Документ создаётся тогда, когда его тема действительно проектируется.

---

## 4. Иерархия документации

### Concept

`docs/project-concept.md` и `docs/architecture-concept.md`.

Содержат:

- назначение проекта;
- принципы;
- общие границы ответственности;
- предварительное архитектурное направление;
- идеи, ещё не доведённые до полного технического контракта.

Concept-документы не должны превращаться в детальные implementation plans.

### Design

`docs/design/*.md`.

Содержат утверждённую архитектуру:

- модели;
- контракты;
- invariants;
- lifecycle;
- concurrency;
- persistence;
- failure semantics;
- security;
- interfaces между компонентами;
- acceptance criteria.

### ADR

`docs/design/decisions/`.

ADR используется, когда существует значимое архитектурное решение между несколькими реалистичными альтернативами.

ADR должен фиксировать:

- контекст;
- варианты;
- принятое решение;
- причины;
- последствия;
- что именно решение не определяет.

### Versions

`docs/design/versions/`.

Version-документы не создают новую архитектуру без необходимости.

Они проецируют уже принятый design на последовательность реализации.

Для каждой версии должны быть понятны:

- prerequisites;
- scope;
- explicit non-goals;
- implementation sequence;
- migrations;
- compatibility;
- tests;
- acceptance gates.

---

## 5. Design должен быть пригоден для реализации ИИ-агентом

Документация создаётся с расчётом на то, что по ней будут работать Codex, ChatGPT и другие coding agents.

Поэтому design должен быть:

- однозначным;
- структурированным;
- без скрытых предположений;
- с явными dependency boundaries;
- с точными invariants;
- с понятными failure semantics;
- с explicit non-goals;
- с проверяемыми acceptance criteria;
- без нескольких противоречащих друг другу источников истины.

Фразы вроде:

> «сделать надёжно»

или

> «при необходимости использовать Redis»

без описания точного контракта не являются достаточной архитектурной спецификацией.

Если решение ещё не принято, оно должно быть явно помечено как open question или вынесено в ADR, а не оставлено неявным.

---

## 6. Backend-first

REST и MCP являются transport facades над общим backend/application layer.

При проектировании любой capability используется порядок:

```text
предметная задача
→ domain model
→ application operation
→ ports
→ infrastructure adapters
→ tests
→ REST projection
→ MCP projection
```

Недопустим обратный процесс:

```text
придумать MCP tool
→ подогнать application layer под его schema
```

или:

```text
придумать REST endpoint
→ сделать endpoint фактическим владельцем business logic
```

---

## 7. REST и MCP проектируются после backend-а

REST должен быть мощным программным фасадом к backend capabilities.

MCP должен быть компактным agent-facing фасадом, удобным для LLM.

Они:

- используют один application layer;
- могут иметь разные input/output schemas;
- не обязаны иметь одинаковое количество операций;
- не дублируют business logic;
- не раскрывают случайные детали infrastructure implementation.

MCP agent-facing descriptions и docstrings преимущественно пишутся на русском языке.

---

## 8. Правила изменения design

При изменении принятого архитектурного решения необходимо:

1. найти канонический документ-владелец темы;
2. обновить его первым;
3. проверить документы, которые на него ссылаются;
4. проверить version plans и roadmap;
5. при существенной смене решения добавить или supersede ADR;
6. не оставлять старый контракт как параллельную «альтернативную истину».

---

## 9. Что не нужно фиксировать преждевременно

Не следует превращать design в набор случайных implementation details до анализа соответствующей темы.

В частности, нельзя заранее фиксировать без отдельного решения:

- точные Redis keys;
- точную структуру всех PostgreSQL tables;
- полное дерево REST endpoints;
- окончательный MCP tool catalog;
- произвольные TTL и timeout;
- формат browser-worker transport;
- полный список поддерживаемых файлов;
- конкретные limits только потому, что «нужна цифра».

Сначала определяется семантика и invariant, затем конкретная реализация.

---

## 10. Уже спроектировано

На текущем этапе зафиксированы:

1. `principles.md`;
2. `glossary.md`;
3. `dependency-rules.md`;
4. `system-context.md`;
5. `runtime-topology.md`.

Актуальный статус и открытые вопросы находятся в `current.md`.

---

## 11. Текущий следующий шаг

Следующий общий foundation проектируется в порядке:

1. `application-contracts.md`;
2. `resource-model.md`;
3. `persistence.md`;
4. `security.md`.

После этого можно безопасно переходить к предметным подсистемам:

```text
Search
→ Retrieval
→ Content
→ Browser
→ Jobs
```

Затем проектируются observability, REST, MCP, deployment, testing и только после полной картины — roadmap и version implementation plans.
