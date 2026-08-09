# Architecture Decision Records

Каталог содержит значимые архитектурные решения Web Access MCP.

ADR используется, когда существует несколько реалистичных вариантов, а выбор влияет на contracts, runtime topology, security, consistency или последующие implementation stages.

## Статусы

- `proposed` — решение подготовлено, но ещё может быть изменено до implementation;
- `accepted` — решение принято и является частью текущего design;
- `superseded` — заменено более новым ADR;
- `rejected` — вариант рассмотрен и явно не принят.

## Правила

ADR должен содержать:

1. контекст;
2. требования;
3. рассмотренные варианты;
4. решение;
5. последствия/trade-offs;
6. что решение намеренно не определяет;
7. ссылки на затронутые design docs.

Если ADR меняет ранее принятый design, сначала обновляется канонический документ-владелец темы либо изменения выполняются одним согласованным patch.

## Реестр

| ADR | Решение | Статус |
|---|---|---|
| [ADR-0001](ADR-0001-browser-worker-transport.md) | Browser Worker actions используют direct internal HTTP/RPC; Redis остаётся coordination/routing layer, а не action bus | accepted |
