# Документация Web Access MCP

## Назначение

Этот каталог — входная точка в concept, architecture, exact public contracts и version-specific документацию проекта.

Перед изменением production-кода или public contracts coding agent должен восстановить repository design context, а не проектировать систему заново из одного task prompt.

---

# Быстрый порядок чтения

## Для общего понимания

1. [`project-concept.md`](project-concept.md)
2. [`architecture-concept.md`](architecture-concept.md)
3. [`design/README.md`](design/README.md)
4. [`design/current.md`](design/current.md)
5. [`design/roadmap.md`](design/roadmap.md)

## Перед реализацией конкретной версии

1. [`AGENTS.md`](AGENTS.md)
2. [`design/current.md`](design/current.md)
3. [`design/principles.md`](design/principles.md)
4. [`design/dependency-rules.md`](design/dependency-rules.md)
5. relevant component design;
6. relevant accepted ADR from [`design/decisions/README.md`](design/decisions/README.md);
7. relevant exact public contract from [`design/contracts/README.md`](design/contracts/README.md), если версия затрагивает facade/schema;
8. `design/versions/vX.Y/README.md`;
9. `design/versions/vX.Y/implementation-sequence.md` или release checklist;
10. [`design/testing.md`](design/testing.md);
11. [`design/release-gates.md`](design/release-gates.md).

---

# Основные разделы

```text
docs/
├── project-concept.md
├── architecture-concept.md
├── AGENTS.md
└── design/
    ├── README.md
    ├── current.md
    ├── roadmap.md
    ├── cross-cutting/component designs
    ├── decisions/
    ├── contracts/
    └── versions/
```

`design/README.md` — подробный индекс canonical design topics.

---

# Иерархия решений

При противоречии использовать порядок:

```text
accepted current ADR + canonical Design semantics
→ exact public contract spec for facade shape
→ current version specification
→ implementation sequence
→ architecture concept
→ project concept
```

`contracts/` не может сам изменить lifecycle/security semantics Design/ADR; он фиксирует точную transport-facing форму уже принятого решения.

Если новый ADR supersedes старое решение, canonical/version/contracts обновляются consistency patch.

---

# Для Codex/ChatGPT

Обязательно прочитать [`AGENTS.md`](AGENTS.md).

Главный принцип:

> Реализовывать принятую архитектуру и target version, а не изобретать более простой shortcut или новый public API без явного design change.

Особенно запрещено самостоятельно ослаблять/переопределять:

- security boundary;
- ownership;
- lifecycle/recovery;
- transaction/outbox/fencing semantics;
- exact REST/MCP contract;
- release gates.

Текущий следующий implementation milestone указан в [`design/current.md`](design/current.md).
