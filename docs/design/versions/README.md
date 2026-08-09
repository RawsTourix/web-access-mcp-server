# Version design index

Каталог содержит implementation-oriented version plans Web Access MCP.

Version docs не создают новую архитектуру без отдельного design/ADR. Они определяют, **какую часть уже принятого design реализовать сейчас, в каком порядке и какими gates подтвердить**.

## Канонический roadmap

См. `../roadmap.md`.

## Версии

| Версия | Название | Статус |
|---|---|---|
| `v0.1` | Service Foundation | design in progress |
| `v0.2` | Search Runtime | planned |
| `v0.3` | Retrieval & Content Core | planned |
| `v0.4` | Managed Browser Runtime | planned |
| `v0.5` | Native Content Expansion | planned |
| `v0.6` | Durable Jobs Runtime | planned |
| `v0.7` | Distributed Operations & Policy Hardening | planned |
| `v0.8` | REST/MCP & Agent Integration Stabilization | planned |
| `v0.9` | Production Hardening | planned |
| `v1.0` | Stable Web Access | planned |

## Обязательная структура version folder

Минимум:

```text
versions/vX.Y/
├── README.md
└── implementation-sequence.md
```

При необходимости:

```text
migration-plan.md
compatibility.md
acceptance.md
```

## Version README

Должен содержать:

- status;
- goal;
- prerequisites;
- canonical design docs;
- scope;
- explicit non-goals;
- external/public contract impact;
- persistence/migration impact;
- security impact;
- required gates;
- acceptance criteria;
- unresolved blockers (их не должно остаться перед coding prompt).

## Implementation sequence

Должен быть patch-oriented и пригоден для Codex/ChatGPT:

```text
characterization/contracts
→ models/ports
→ infrastructure
→ application
→ REST
→ MCP
→ integration/fault/race tests
→ docs/status
```

Порядок может отличаться по версии, но каждый patch должен иметь:

- exact scope;
- files/modules expected;
- invariants;
- tests;
- non-goals;
- acceptance before next patch.

## Статусы

- `planned` — roadmap milestone существует, детальный design ещё не готов;
- `design in progress` — version docs/ADR уточняются;
- `ready for implementation` — все blockers/ADR закрыты, можно выдавать coding prompt;
- `in implementation` — код разрабатывается;
- `implemented, pending acceptance` — код готов, gates ещё не полностью пройдены;
- `accepted` — все required gates версии пройдены;
- `superseded` — версия/план заменены более новым решением.

## Правило coding handoff

Codex/ChatGPT нельзя просить «самостоятельно выбрать» решение, которое version docs помечают blocker/open question.

Перед статусом `ready for implementation` все такие вопросы должны быть:

- закрыты в design;
- оформлены ADR;
- либо явно удалены из scope текущей версии.
