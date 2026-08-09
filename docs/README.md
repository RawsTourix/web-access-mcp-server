# Документация Web Access MCP

## Назначение

Этот каталог является входной точкой в архитектурную и version-specific документацию проекта.

Перед изменением production-кода или public contracts coding agent должен восстановить контекст по соответствующим каноническим документам, а не проектировать архитектуру заново из одного task prompt.

---

# Быстрый порядок чтения

## Для общего понимания

1. [`project-concept.md`](project-concept.md)
2. [`architecture-concept.md`](architecture-concept.md)
3. [`design/README.md`](design/README.md)
4. [`design/current.md`](design/current.md)
5. [`design/roadmap.md`](design/roadmap.md)

## Перед реализацией конкретной версии

1. [`design/principles.md`](design/principles.md)
2. [`design/dependency-rules.md`](design/dependency-rules.md)
3. relevant component design;
4. relevant ADR from [`design/decisions/README.md`](design/decisions/README.md);
5. `design/versions/vX.Y/README.md`;
6. `design/versions/vX.Y/implementation-sequence.md` или release checklist;
7. [`design/testing.md`](design/testing.md);
8. [`design/release-gates.md`](design/release-gates.md).

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
    └── versions/
```

`design/README.md` является подробным индексом canonical design topics.

---

# Иерархия решений

При противоречии использовать порядок:

```text
accepted current ADR / canonical Design
→ current version specification
→ implementation sequence
→ architecture concept
→ project concept
```

Concept documents объясняют направление и не должны переопределять более позднее инженерное решение.

Если новый ADR supersedes старое решение, связанные canonical/version docs обновляются consistency patch.

---

# Для Codex/ChatGPT

Обязательно прочитать [`AGENTS.md`](AGENTS.md).

Главный принцип:

> Реализовывать принятую архитектуру, а не изобретать более простой shortcut без явного design change.

Особенно запрещено самостоятельно ослаблять:

- security boundary;
- ownership;
- lifecycle/recovery;
- transaction/outbox/fencing semantics;
- public REST/MCP contract;
- release gates.
