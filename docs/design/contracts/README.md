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

- [`common-models.md`](common-models.md) — общие public result/error/resource/cursor модели и сериализация.
- [`mcp-tools.md`](mcp-tools.md) — exact freeze-candidate MCP input/output contracts, bounds, unions и execution metadata для catalog ADR-0022.
- [`rest-api-v1.md`](rest-api-v1.md) — exact freeze-candidate обычного REST `/api/v1`: Search/Retrieval/Content/Browser/Jobs + базовые operational references.
- [`policy-models.md`](policy-models.md) — exact dynamic non-secret task policy, global defaults/maxima, principal overrides и PolicySnapshot serialization.
- [`admin-api-v1.md`](admin-api-v1.md) — exact protected `/api/v1/admin/*`: policy revisions/overrides, provider/usage diagnostics, audit, worker drain и typed maintenance.

`admin-api-v1.md` является более специфичным exact contract для `/api/v1/admin/*`. Если ранняя краткая admin-секция `rest-api-v1.md` не перечисляет более поздний exact endpoint, приоритет для admin namespace имеет `admin-api-v1.md` при сохранении общей REST semantics `../rest-api.md`.

Generated actual FastMCP schemas и OpenAPI в v0.8 являются executable contract artifacts и должны соответствовать совокупности этих specs.

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
9. Contract spec не имеет права самовольно расширять capability beyond canonical component/facade design.
10. Generated actual FastMCP/OpenAPI contract в v0.8 должен соответствовать этим specs или design меняется явно до freeze.
11. Dynamic policy не хранит secrets и не может логически отключить собственный admin recovery control plane (ADR-0023).

---

# Compatibility

После v0.8 freeze изменения проверяются через `../compatibility.md`:

- removal/rename/meaning change — breaking;
- bounds/default/required changes — compatibility-sensitive;
- additive optional output fields проходят compatibility review;
- новый MCP tool требует отдельного semantic intent/execution-class review;
- новый REST endpoint может быть additive, если не меняет существующую semantics;
- policy schema revision требует rolling-software compatibility;
- behavioral retry/ownership/security/admin-authority change считается contract change даже без изменения JSON shape.
