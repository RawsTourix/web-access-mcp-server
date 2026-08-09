# Public contract specifications

## Назначение

Этот каталог содержит **точные transport-facing DTO/schema contracts**, когда component/facade design уже определил семантику.

Иерархия:

```text
component/application design
→ accepted ADR
→ facade design (REST/MCP)
→ contracts/* exact DTO/schema
→ version implementation
→ generated actual contract fixture (v0.8+)
```

Contract spec не может изменить lifecycle/security semantics, определённые каноническим Design/ADR.

---

# Документы

- [`common-models.md`](common-models.md) — общие public result/error/resource/cursor модели.
- [`mcp-tools.md`](mcp-tools.md) — exact freeze-candidate MCP input/output contracts для tool catalog ADR-0022.

REST exact contract может дополняться отдельным документом после проверки текущего `rest-api.md`; v0.8 generated OpenAPI является окончательным executable contract artifact.

---

# Правила

1. Agent-facing descriptions/field descriptions — на русском.
2. Имена полей/коды — английские.
3. Every bound encoded machine-readable where schema language supports it.
4. Unknown input fields forbidden unless explicitly designed.
5. `null`, omission и default не смешиваются.
6. Cross-field invariants выражаются JSON Schema `oneOf`/discriminator и runtime validation.
7. Runtime error remains structured/repairable.
8. Internal provider/Playwright/SQL/Redis fields не попадают сюда.
9. Generated actual FastMCP/OpenAPI contract в v0.8 должен соответствовать этим specs или design меняется явно до freeze.
