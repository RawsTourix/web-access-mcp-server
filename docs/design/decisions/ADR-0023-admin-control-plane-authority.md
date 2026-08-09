# ADR-0023 — Dynamic policy не может отключить собственный admin control plane

**Статус:** accepted

## 1. Контекст

Ранний policy design включал `admin` в общий набор dynamic capability flags.

Это создаёт self-lockout failure mode:

```text
operator ошибочно выключил admin capability
→ admin policy API начинает запрещать policy update
→ той же policy нельзя вернуть рабочее состояние
```

Полагаться на ручное редактирование PostgreSQL или аварийный rebuild как обычный recovery path неправильно.

---

## 2. Решение

Авторизация **policy/admin control plane** не управляется той же dynamic policy, которую этот control plane изменяет.

Admin REST baseline требует:

```text
trusted AuthProvider principal
+
admin:read / admin:write scope
+
deployment/network security boundary
```

Dynamic policy:

- не может создать `admin:*` scope;
- не может отозвать `admin:*` scope;
- не содержит `admin` в task `CapabilityCode`;
- не может сделать authorized policy recovery endpoint недоступным логическим self-lockout-ом.

---

## 3. Dynamic task capabilities

v1 dynamic capability enum:

```text
search
retrieval
content.read
content.parse
browser.read
browser.interact
jobs.read
jobs.create
```

Они продолжают вычисляться как:

```text
authenticated task scopes
∩ global dynamic policy
∩ principal override
∩ resource ownership/policy
```

---

## 4. Что остаётся защищённым

Это решение **не делает admin API bypass policy/security**.

Admin endpoints всё ещё имеют:

- dedicated admin scopes;
- strict authentication;
- deployment/network restrictions;
- typed request schemas;
- software hard ceilings;
- optimistic revision checks;
- required audit;
- rate/capacity controls из static/operator control-plane settings where needed;
- no generic SQL/Redis/shell access.

---

## 5. Operational disable

Если deployment должен полностью отключить admin HTTP surface, это выполняется **static deployment configuration/network policy**, а не mutable dynamic policy document.

Такой disable требует контролируемого rollout/recovery path.

---

## 6. Break-glass

Production deployment должен иметь документированный способ восстановить admin control plane credential/network access без изменения dynamic policy payload.

Baseline может использовать отдельный configured admin service principal/secret rotation procedure.

Это не означает hardcoded universal credential.

---

## 7. Maintenance/provider controls

Dynamic policy может ограничивать task/provider/resource admission, но authorized admin API остаётся способным:

- прочитать current policy;
- исправить policy;
- rollback policy;
- inspect status/audit;
- выполнить только спроектированные maintenance actions.

Конкретная maintenance action всё равно может быть rejected software hard safety invariant-ом.

---

## 8. Последствия

Плюсы:

- нет dynamic-policy self-lockout;
- recovery path остаётся управляемым;
- authority source проще: admin scope принадлежит AuthProvider/deployment;
- dynamic policy остаётся domain policy task capabilities, а не контроллером собственного control plane.

Минусы:

- admin access нельзя отключить одной dynamic policy кнопкой;
- deployment обязан отдельно управлять admin credentials/network boundary.

Это сознательный trade-off в пользу recoverability.

---

## 9. Требуемые изменения документации/кода

- убрать `admin` из dynamic `CapabilityCode`;
- сохранить `admin:read/admin:write` как REST authorization scopes;
- policy schema/tests должны отклонять `admin` в enabled/disabled task capability lists;
- v0.7 admin policy tests должны включать попытку self-lockout;
- runbook должен содержать admin credential/network recovery procedure.
