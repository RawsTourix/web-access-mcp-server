# ADR-0010 — Browser snapshot: ARIA semantic view + snapshot-scoped exact ElementRefs

**Статус:** accepted

## 1. Контекст

LLM должен видеть страницу и взаимодействовать с конкретными элементами без CSS/XPath.

Требования одновременно конфликтуют:

- ref должен быть удобным для LLM;
- action должен работать через Playwright Locator/actionability;
- dynamic DOM не должен приводить к клику по «похожему» новому элементу;
- ref не должен быть вечным selector;
- snapshot/result должен быть bounded;
- implementation не должна мутировать DOM служебными `data-*` атрибутами без необходимости.

---

## 2. Рассмотренные варианты

### A. Публичный CSS/XPath selector

Отклонён: хрупок, LLM вынуждена понимать DOM, легко hallucinate selector, stale identity плохо проверяется.

### B. Вставлять `data-web-access-ref` в DOM

Даёт точный selector, но мутирует страницу и может влиять на CSS/JS/observers.

### C. Хранить только ElementHandle и выполнять action через ElementHandle

Identity точная, но Playwright рекомендует Locator-based actions; handle по своей природе stale и не даёт удобного пере-разрешения/validation diagnostics.

### D. Private LocatorRecipe + snapshot-time ElementHandle identity anchor

Worker хранит short-lived exact handle и private locator recipe. При action recipe заново разрешается в Locator, затем candidate DOM node сравнивается с original handle. Action выполняется Locator-ом только после identity match.

---

## 3. Решение

Принимается вариант **D**.

Snapshot содержит два логических слоя:

```text
Semantic page representation
+
Actionable element inventory with opaque element_ref
```

Worker memory хранит `SnapshotRefMap`:

```text
snapshot_id
page_id/page_generation
created_at/expires_at
refs:
  element_ref -> {
    ElementHandle identity anchor,
    private LocatorRecipe,
    semantic fingerprint,
  }
```

Public client не видит recipe/ElementHandle.

---

## 4. Semantic representation

Baseline использует Playwright Locator ARIA snapshot capability текущей locked version для semantic/accessibility-oriented representation страницы/корневой области.

Conceptually:

```text
page.locator("body").aria_snapshot()
```

или эквивалентный поддерживаемый Locator API locked Playwright version.

Точная сигнатура проверяется integration test, а public Browser Snapshot schema не зависит от YAML/string формата private Playwright API навсегда.

---

## 5. Actionable inventory

Отдельно worker перечисляет **семантически интерактивные** DOM elements baseline:

- native links/buttons/form controls;
- contenteditable;
- elements с standard interactive ARIA roles;
- focusable/tabindex controls в bounded policy.

Не использовать generic `div` с визуальным `cursor:pointer` как implicit interactive heuristic baseline.

Сайт без семантических interactive markers может быть менее управляем через core MCP; advanced locator/evaluate capability может быть отдельным future tool/REST permission.

---

## 6. ElementRef

Public ref:

```text
el_<random opaque id>
```

scoped к:

```text
BrowserSession
BrowserPage
Snapshot
Page generation
```

Он не является Resource вне live session.

---

## 7. LocatorRecipe generation

Для каждого actionable element worker строит private recipe с приоритетом **детерминированных locator sources**, например:

1. unique stable DOM id;
2. configured test-id attribute, если unique;
3. unique role + accessible name;
4. unique associated label/name/placeholder semantics;
5. structural CSS path/nth-of-type fallback.

Recipe selection — locator implementation detail, не LLM heuristic.

Recipe всегда проверяется на однозначность snapshot-time.

---

## 8. Identity anchor

После выбора candidate worker сохраняет exact `ElementHandle` snapshot-time.

Handle используется **не как public selector и не как основной action API**, а как short-lived identity anchor конкретного DOM node.

При snapshot eviction handle обязательно dispose/release.

---

## 9. Semantic fingerprint

Дополнительно сохраняется bounded fingerprint:

- tag;
- role;
- accessible/ARIA snapshot fragment;
- selected stable attributes/state;
- page generation.

Fingerprint используется для diagnostics и defensive validation, но **не может заменить exact node identity check**, если handle ещё валиден.

---

## 10. Action resolution

При `browser_click/fill/...`:

1. найти snapshot/ref map;
2. проверить session/page/generation/TTL;
3. получить private LocatorRecipe;
4. построить Locator;
5. `count == 1`, иначе stale/ambiguous;
6. получить current ElementHandle candidate;
7. сравнить DOM identity с stored anchor через Playwright evaluate/JS handle equality;
8. если identity различна → `stale_target`;
9. если та же → выполнить action через **Locator**, используя Playwright actionability/auto-wait;
10. вернуть action result.

Никакого heuristic retargeting.

---

## 11. Если stored handle detached

Detached/invalid identity anchor:

```text
stale_target
```

Даже если recipe теперь находит очень похожий элемент.

Agent делает новый snapshot.

---

## 12. Почему false-stale допустим

Dynamic DOM может перестроить элемент так, что logically «та же кнопка» стала новым DOM node.

Web Access предпочитает:

```text
false negative → новый snapshot
```

вместо:

```text
false positive → action на другом элементе
```

Это security/correctness выбор.

---

## 13. Snapshot retention

Initial defaults:

```text
max snapshots per page = 3
snapshot/ref TTL = 5 minutes
max actionable refs per snapshot = 300
```

Configurable within hard safety ceilings.

При eviction:

- ElementHandles dispose;
- refs become stale;
- snapshot metadata/event может сохраняться только как ContentObject, но live refs больше не работают.

---

## 14. Snapshot size

Initial budgets:

```text
MCP inline semantic snapshot = up to 30,000 chars
backend generated semantic snapshot hard handling budget = 256,000 chars
REST inline default = up to 100,000 chars
```

Если full structured snapshot больше facade inline budget:

- worker serializes full bounded snapshot representation as internal artifact;
- Control Plane ingests it into Content;
- result содержит preview + `snapshot_content_id`;
- actionable refs relevant to returned inline inventory сохраняются bounded.

Если backend hard generation budget exceeded, snapshot returns `snapshot_too_large`/partial warning according implementation rather than unbounded response.

---

## 15. Stored snapshot representation

Большой stored snapshot может быть `application/json`/text representation containing:

- semantic snapshot text/tree;
- actionable inventory labels + element_ref values;
- page/snapshot metadata.

Важно: ContentObject может пережить live ref TTL, поэтому stored historical `element_ref` после TTL **не гарантированно actionable**.

Schema clearly marks refs as snapshot-time ephemeral.

---

## 16. Actionable inventory fields

Public item baseline:

```text
element_ref
role/tag/type
accessible/name text preview
state (disabled/checked/expanded/value where safe)
short context/path label if useful
```

No private selector.

Sensitive input values (password fields) redacted.

---

## 17. Frames

Private LocatorRecipe включает frame context/path when element is inside iframe.

Public ref остаётся единой opaque string.

Core MCP не требует `frame_id` parameter для каждого action.

Cross-origin iframe access следует возможностям Playwright; security policy/visibility ограничивает snapshot data appropriately.

---

## 18. Shadow DOM

LocatorRecipe может использовать Playwright-supported shadow-piercing locator semantics where applicable.

Public ref не меняется.

Integration tests должны покрывать representative open shadow DOM.

Closed shadow roots могут быть недоступны; это honest limitation, не повод JS bypass.

---

## 19. Snapshot freshness metadata

Result включает:

```text
snapshot_id
page_id
page_generation
session_revision
created_at
expires_at
truncated/has_full_content flags
```

LLM может понимать stale diagnostic, но не вычисляет ref internals.

---

## 20. Snapshot after navigation

Navigation increments page generation и инвалидирует все previous refs немедленно.

Snapshot maps предыдущей generation dispose eagerly.

---

## 21. DOM mutation без navigation

Page generation может не измениться.

Exact ElementHandle identity check всё равно обнаруживает replacement/detach.

Это основная причина identity anchor поверх recipe.

---

## 22. Security

- no DOM mutation with service markers baseline;
- no public selectors;
- password/secret form values redacted;
- page text/name remains untrusted;
- element_ref randomness не является authorization;
- ownership/session validation before ref lookup;
- snapshot map bounded to avoid handle leaks.

---

## 23. Performance

Generating ARIA snapshot + actionable inventory can be expensive on huge pages.

Therefore:

- bounded budgets;
- no automatic snapshot after every action;
- full document reading uses `browser_content`, not giant repeated snapshot;
- actions use existing snapshot map;
- performance baseline measured v0.4 load tests.

Optimization cannot weaken exact identity validation silently.

---

## 24. Tests

Required real-browser scenarios:

1. unique button click;
2. duplicate role/name buttons;
3. DOM insertion shifts structural index;
4. original element removed + identical replacement → stale;
5. text/state mutation same node → identity stays valid if recipe still resolves same node;
6. navigation invalidates refs;
7. snapshot eviction/TTL;
8. iframe element;
9. shadow DOM;
10. disabled/hidden actionability;
11. password value redaction;
12. huge page snapshot ContentRef fallback;
13. max refs bounded;
14. handle disposal/leak soak.

---

## 25. Consequences

Плюсы:

- LLM не пишет CSS/XPath;
- exact DOM identity checked;
- Locator actionability retained;
- dynamic replacement безопасно stale;
- no service DOM attributes;
- internal locator strategy can evolve.

Минусы:

- snapshot map держит ElementHandles в worker memory;
- snapshot generation дороже простого screenshot;
- recipe generation/identity comparison implementation сложнее;
- inaccessible/non-semantic custom controls могут не попасть core inventory.

Trade-off принимается ради safe agent interaction.

---

## 26. Не определяется

- exact semantic snapshot public JSON shape;
- exact CSS recipe generator implementation;
- exact interactive role allowlist;
- exact `aria_snapshot()` normalization/parser;
- future advanced locator tool.

Эти details фиксируются v0.4 implementation sequence/tests, сохраняя identity-anchor invariant.
