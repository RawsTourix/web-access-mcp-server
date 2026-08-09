# Version design index

Каталог содержит implementation-oriented version plans Web Access MCP.

Version docs не создают новую архитектуру без отдельного Design/ADR. Они определяют, **какую часть уже принятого design реализовать сейчас, в каком порядке и какими gates подтвердить**.

Канонический roadmap: `../roadmap.md`.

---

# 1. Версии

| Версия | Название | Design status |
|---|---|---|
| `v0.1` | Service Foundation | ready for implementation |
| `v0.2` | Search Runtime | ready for implementation |
| `v0.3` | Retrieval & Content Core | ready for implementation |
| `v0.4` | Managed Browser Runtime | ready for implementation |
| `v0.5` | Native Content Expansion | ready for implementation |
| `v0.6` | Durable Jobs Runtime | ready for implementation |
| `v0.7` | Distributed Operations & Policy Hardening | ready for implementation |
| `v0.8` | REST/MCP & Agent Integration Stabilization | ready for implementation |
| `v0.9` | Production Hardening | ready for implementation |
| `v1.0` | Stable Web Access | release contract defined |

Эти статусы относятся только к **дизайну**. Ни одна будущая версия не считается реализованной/accepted, пока нет фактического кода и required release evidence.

---

# 2. Canonical implementation order

```text
v0.1 Foundation
→ v0.2 Search
→ v0.3 Retrieval & Content Core
→ v0.4 Browser
→ v0.5 Content Expansion
→ v0.6 Durable Jobs
→ v0.7 Operations/Policy
→ v0.8 Contract/Agent stabilization
→ v0.9 Production hardening
→ v1.0 stable release
```

Design readiness следующей версии **не разрешает** реализовывать её до acceptance prerequisites.

---

# 3. Обязательная структура version folder

Минимум для implementation-bearing version:

```text
versions/vX.Y/
├── README.md
└── implementation-sequence.md
```

Дополнительно по необходимости:

```text
migration-plan.md
compatibility.md
acceptance.md
release-checklist.md
```

`v1.0` является release contract и может использовать release checklist вместо обычного feature implementation sequence.

---

# 4. Version README обязан содержать

- status;
- goal;
- prerequisites;
- canonical Design/ADR/contracts;
- scope;
- explicit non-goals;
- external/public contract impact;
- persistence/migration impact;
- security impact;
- required gates;
- acceptance criteria;
- unresolved blockers — их не должно остаться перед `ready for implementation`.

---

# 5. Implementation sequence

Должен быть patch-oriented и пригоден для Codex/ChatGPT.

Обычное направление:

```text
preconditions/characterization
→ contracts/models/ports
→ persistence/infrastructure/runtime
→ application services
→ REST
→ MCP
→ fault/race/security/load tests по scope
→ documentation/evidence closure
```

Но конкретная версия может иметь более строгий порядок. Например Browser сначала строит ownership/worker/subprocess/egress runtime и только затем Playwright facade.

Каждый patch должен иметь:

- exact scope;
- expected modules/files;
- invariants;
- forbidden shortcuts/non-goals;
- tests;
- gate before next patch.

---

# 6. Статусы implementation

- `planned` — milestone существует, detailed design ещё не готов;
- `design in progress` — version design/ADR уточняются;
- `ready for implementation` — architecture blockers закрыты, можно готовить coding task;
- `in implementation` — код разрабатывается;
- `implemented, pending acceptance` — production code готов, required gates ещё не полностью пройдены;
- `accepted` — required gates/evidence версии пройдены;
- `superseded` — версия/plan заменены явно;
- `release contract defined` — стабильный release milestone описан, но может быть достигнут только после acceptance prerequisites.

---

# 7. Coding handoff rule

Перед coding prompt обязательно читать:

```text
docs/AGENTS.md
→ docs/design/current.md
→ target component design
→ accepted ADR
→ relevant docs/design/contracts/*
→ target version README
→ target implementation-sequence
→ testing/release-gates
```

Codex/ChatGPT нельзя просить самостоятельно выбрать решение, которое остаётся blocker/open question. Перед implementation оно должно быть:

- закрыто Design/ADR;
- либо явно исключено из scope текущей версии.

---

# 8. Public contract timing

Semantic public facade design принадлежит `rest-api.md`/`mcp.md`.

Exact DTO/schema baseline принадлежит:

- `../contracts/common-models.md`;
- `../contracts/mcp-tools.md`;
- `../contracts/rest-api-v1.md`.

До v0.8 implementation эти specs являются target contracts.

В v0.8 generated actual FastMCP schemas/OpenAPI становятся executable freeze-candidate fixtures. Если реализация не может корректно воспроизвести contract, исправляется Design/ADR явно — не производится скрытое расхождение документации и кода.
