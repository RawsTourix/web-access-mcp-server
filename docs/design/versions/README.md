# Version design index

Каталог содержит implementation-oriented version plans Web Access MCP.

Version docs не создают новую архитектуру без отдельного Design/ADR. Они определяют, **какую часть уже принятого design реализовать сейчас, в каком порядке и какими gates подтвердить**.

Канонический roadmap: `../roadmap.md`.

---

# 1. Версии

| Версия | Название | Status |
|---|---|---|
| `v0.1` | Service Foundation | accepted |
| `v0.2` | Search Runtime | implemented, pending acceptance |
| `v0.3` | Retrieval & Content Core | ready; allowed only after v0.2 acceptance |
| `v0.4` | Managed Browser Runtime | ready for implementation |
| `v0.5` | Native Content Expansion | ready for implementation |
| `v0.6` | Durable Jobs Runtime | ready for implementation |
| `v0.7` | Distributed Operations & Policy Hardening | ready for implementation |
| `v0.8` | REST/MCP & Agent Integration Stabilization | ready for implementation |
| `v0.9` | Production Hardening | ready for implementation |
| `v1.0` | Stable Web Access | release contract defined |

Acceptance v0.1 зафиксирован на implementation HEAD:

```text
3e5df8775f99cf15a30e17b56db740c08b00233c
```

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

Design readiness поздней версии не разрешает перепрыгнуть acceptance prerequisites.

---

# 3. Version folder

Для implementation-bearing version минимум:

```text
versions/vX.Y/
├── README.md
└── implementation-sequence.md
```

По необходимости:

```text
migration-plan.md
compatibility.md
acceptance.md
release-checklist.md
```

`v1.0` — release contract, поэтому может использовать release checklist вместо feature sequence.

---

# 4. Version README

Обязан содержать:

- status;
- goal/prerequisites;
- canonical Design/ADR/contracts;
- scope/non-goals;
- public contract impact;
- persistence/security impact;
- required gates;
- acceptance criteria;
- no unresolved implementation blocker before `ready for implementation`.

---

# 5. Implementation sequence

Patch-oriented, пригодный для Codex/ChatGPT.

Typical direction:

```text
preconditions/characterization
→ contracts/models/ports
→ persistence/infrastructure/runtime
→ application
→ REST
→ MCP
→ race/fault/security/load tests according scope
→ docs/evidence closure
```

Concrete version may enforce stricter ordering.

Each patch specifies:

- exact scope/modules;
- invariants;
- forbidden shortcuts;
- tests;
- gate before next patch.

---

# 6. Status vocabulary

- `planned` — milestone exists, detailed design not ready;
- `design in progress` — version design/ADR open;
- `ready for implementation` — architecture blockers closed;
- `in implementation` — code work active;
- `implemented, pending acceptance` — code and coding-agent evidence exist; independent acceptance is not yet granted;
- `accepted` — required gates/evidence green;
- `superseded` — explicit replacement;
- `release contract defined` — stable release milestone defined, reachable only after prerequisites.

---

# 7. Coding handoff

Before target patch read:

```text
docs/AGENTS.md
→ docs/design/current.md
→ relevant component/cross-cutting Design
→ relevant accepted ADR
→ relevant contracts/*
→ target version README
→ target implementation sequence
→ testing/release gates
```

Coding agent не выбирает сам blocker/open-question architecture.

---

# 8. Exact public contract timing

Semantic owners:

```text
REST → ../rest-api.md
MCP  → ../mcp.md
```

Exact target specs:

```text
../contracts/common-models.md
../contracts/mcp-tools.md
../contracts/rest-api-v1.md
../contracts/browser-api-v1.md
../contracts/policy-models.md
../contracts/admin-api-v1.md
```

Specificity:

```text
Browser REST → browser-api-v1.md
Admin REST   → admin-api-v1.md + policy-models.md
Other REST   → rest-api-v1.md
MCP          → mcp-tools.md
```

До v0.8 это reviewed target contracts.

В v0.8 actual FastMCP/OpenAPI/public model artifacts становятся generated executable freeze fixtures after matching reviewed specs.

Implementation/framework inconvenience не является разрешением на silent contract drift.

---

# 9. Cross-version ADR still applies to earlier capabilities

Поздний ADR может уточнять semantics capability, реализованной ранней version, до external freeze.

Пример:

```text
ADR-0024
→ v0.2 Search retry/cost semantics
→ v0.3 Retrieval/Content resource-creation retry semantics
→ v0.4 Browser artifact/action retry semantics
```

Поэтому target coding task обязан читать **current relevant ADR**, а не только ADR, существовавшие в момент первоначального version-plan draft.

После v0.8 freeze такие semantic изменения проходят compatibility policy.
