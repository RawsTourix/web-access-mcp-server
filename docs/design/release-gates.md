# Release gates Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **общих критериев допуска implementation/version к завершению и release**.

Version plan выбирает применимые gates и добавляет version-specific acceptance, но не может ослабить общие security/consistency invariants без изменения design/ADR.

---

# 1. Главный принцип

Версия считается завершённой не потому, что:

```text
«код написан и happy path работает»
```

а потому, что выполнены проверяемые gates по:

- design consistency;
- contracts;
- persistence;
- security;
- lifecycle/concurrency;
- fault/recovery;
- deployment;
- integration;
- performance для реализованного scope.

---

# 2. Gate G0 — Design completeness

Перед implementation/release scope должен иметь канонический design.

Требования:

- component responsibilities/non-goals определены;
- application operations описаны;
- ports/dependencies определены;
- lifecycle/concurrency/retry/failure semantics определены;
- persistence/security impact определён;
- acceptance criteria существуют;
- implementation-relevant open questions закрыты или явно отложены вне scope;
- design docs не противоречат друг другу;
- `current.md`/roadmap/version status актуальны.

Coding agent не должен самостоятельно принимать архитектурное решение, отмеченное design как open и необходимое для текущего patch.

---

# 3. Gate G1 — Build/static quality

Обязательные проверки:

- dependency lock разрешается reproducibly;
- package/build импортируется;
- formatter/linter green;
- type checks green согласно принятому уровню strictness;
- architecture import checks green;
- no committed secrets;
- migrations имеют один ожидаемый head;
- docs links/schema examples checks green, если соответствующее tooling уже введено.

Новых ignored type/lint errors без documented reason не допускается.

---

# 4. Gate G2 — Unit/application contracts

Все unit/contract tests текущего scope green.

Особенно:

- OperationOutcome invariants;
- batch/partial success;
- warning/hint/error separation;
- ownership;
- retry/unknown outcome;
- state machines;
- application ports;
- no hidden orchestration.

Ни один critical invariant не должен быть проверен только E2E случайно.

---

# 5. Gate G3 — Public schema contracts

Если версия изменяет REST/MCP:

- actual OpenAPI tests green;
- actual FastMCP schema tests green;
- catalog/operationId diff reviewed;
- descriptions/constraints complete;
- internal fields absent;
- breaking change либо отсутствует, либо явно оформлена version/migration strategy;
- own-agent compatibility fixtures updated осознанно.

---

# 6. Gate G4 — Persistence/migrations

Если scope затрагивает durable state:

- real PostgreSQL integration green;
- migrations empty→head green;
- previous supported schema→head green;
- constraints/concurrency verified;
- transaction boundaries tested;
- rollback paths tested;
- no hidden repository commits;
- migration compatible с declared rollout strategy.

---

# 7. Gate G5 — Cross-system consistency

Если scope затрагивает PostgreSQL + Redis/ContentStore/worker boundary:

обязательны crash-window tests.

Примеры:

- Job + Outbox;
- duplicate publish;
- Content staging/finalization;
- Browser routing loss;
- resource cleanup/reconciliation.

Нельзя закрыть gate только unit mock-ом cross-system failure.

---

# 8. Gate G6 — Security baseline

Для каждого реализованного external input surface:

- threat-specific negative tests green;
- ownership checks green;
- secrets/error redaction green;
- resource limits существуют;
- unsafe defaults отсутствуют;
- dependency/container scan reviewed;
- no unresolved Critical security finding;
- High finding либо исправлен, либо release blocked до отдельного explicit security decision.

Нельзя «отложить SSRF» после выпуска Retrieval/Browser.

---

# 9. Gate G7 — Search

Применяется версиям с Search.

Требования:

- no hidden provider fallback;
- batch/partial failure green;
- default/explicit provider selection green;
- provider capability rejection green;
- SearXNG adapter controlled integration green;
- Yandex adapter protocol tests green, если входит scope;
- cache freshness semantics tested;
- billable accounting tested без live billing default CI;
- provider outage/degraded readiness tested;
- snippets остаются untrusted metadata.

---

# 10. Gate G8 — Retrieval

Применяется версиям с Retrieval.

Требования:

- SSRF matrix green;
- redirect revalidation green;
- TLS verification default;
- streaming size/decompression limits green;
- timeout/cancellation green;
- batch isolation green;
- 4xx/5xx response/body semantics tested;
- Content handoff green;
- no Browser fallback;
- no arbitrary auth/header proxy common surface.

---

# 11. Gate G9 — Content

Применяется версиям с Content.

Требования:

- raw Content immutable;
- format identification multi-signal;
- parser registry extensible;
- L0/L1/L2 boundary verified;
- scanned PDF/no-native-text does not call OCR;
- parser limits/security corpus green;
- derived provenance/revision green;
- large result uses ContentRef;
- ContentStore adapter contract green;
- staging/orphan reconciliation green;
- isolated parser execution tested, если scope его включает.

---

# 12. Gate G10 — Browser

Применяется версиям с Browser.

Требования:

- real Chromium integration green;
- BrowserSession independent from transport connection;
- worker ownership/routing tested;
- session action serialization green;
- element_ref stale/ambiguity safety green;
- actionability behavior green;
- mutating duplicate delivery does not double-execute;
- response loss returns `unknown` where required;
- worker loss → session lost;
- TTL/reaper/close races green;
- popup/download/upload Content handoff green;
- private/internal browser egress blocked;
- worker sandbox/least privilege deployment verified;
- no unrestricted evaluate tool ordinary surface.

---

# 13. Gate G11 — Jobs

Применяется версиям с durable Jobs.

Требования:

- Job + Outbox atomic transaction;
- at-least-once duplicate-safe publish;
- DB claim prevents double execution;
- attempt lease/fencing green;
- worker crash/retry green;
- retry finite/backoff durable;
- cancellation races green;
- stale attempt cannot overwrite terminal result;
- reconciler green;
- large result ContentRefs;
- admission quotas/backpressure.

---

# 14. Gate G12 — Observability/health

Для production-capable версии:

- structured logs with redaction;
- operation IDs propagated;
- low-cardinality metrics;
- component metrics exist;
- liveness/readiness/degraded status tested;
- dependency outage reflected correctly;
- worker capacity/drain distinguishable from crash;
- telemetry backend failure does not cascade;
- key leak/backlog/error conditions alertable.

---

# 15. Gate G13 — REST

Если REST facade входит scope:

- actual OpenAPI contract green;
- common error mapping green;
- auth/owner isolation green;
- batch partial success green;
- content streaming green;
- Browser typed endpoints green;
- no raw infrastructure/provider leakage;
- unknown fields rejected;
- request/response limits green;
- operational/admin surface separated.

---

# 16. Gate G14 — MCP

Если MCP facade входит scope:

- real MCP client discovers expected catalog;
- full schema retrieval works;
- recursive field descriptions/constraints green;
- Russian agent-facing descriptions reviewed;
- web_search/web_fetch distinction clear;
- no `*_many` duplicates;
- Browser refs/lifecycle green;
- large result bounded ContentRef/cursor;
- structured repairable errors/hints;
- annotations/trusted agent metadata consistent;
- generic MCP client green;
- own-agent integration green;
- server reconnect does not define resource lifecycle.

---

# 17. Gate G15 — Deployment

Для версии, объявленной deployable:

- reference Compose starts cleanly from empty state;
- migration one-shot succeeds;
- only intended ingress exposed;
- health probes green;
- dependency restart tested;
- API replica restart safe;
- Job Worker restart safe;
- Browser Worker restart/lost-session semantics green;
- persistent volumes/storage configured;
- secrets not baked/logged;
- proxy streaming MCP/Content works.

---

# 18. Gate G16 — Rolling upgrade

Для release с persisted/distributed compatibility changes:

- old→new migration tested;
- mixed API versions tested where promised;
- Browser Worker protocol rolling compatibility/drain tested;
- queued Jobs compatible/migrated;
- MCP/REST client compatibility reviewed;
- rollback/forward-fix strategy documented.

---

# 19. Gate G17 — Race/fault recovery

Critical concurrency/fault suites green.

Required relevant scenarios repeated/randomized, not one pass.

No known reproducible race may remain marked flaky/ignored in implemented lifecycle.

Failpoint/crash tests должны подтверждать recovery, а не только failure detection.

---

# 20. Gate G18 — Load baseline

Перед production release реализованные capabilities имеют reproducible baseline:

- throughput;
- latency distribution;
- memory/CPU;
- browser capacity;
- queue/backlog behavior;
- Content throughput.

Hard regression thresholds устанавливаются после первого baseline, а не заранее.

---

# 21. Gate G19 — Soak/leak

Перед production-ready Browser/worker release выполняется длительный soak.

После cleanup/reconciliation:

- BrowserContexts/pages не растут бесконечно;
- zombie Chromium processes отсутствуют;
- temp files/downloads bounded;
- DB pool стабилен;
- Redis leases/outbox backlog восстанавливается;
- orphan Content bounded/reconciled;
- memory growth объясним/bounded.

---

# 22. Gate G20 — Own-agent integration

Для builtin use в `internet-search-bot`:

- Streamable HTTP connect;
- tool discovery;
- schema lookup;
- calls;
- Content handles;
- BrowserSession cleanup;
- presentation metadata mapping;
- retry semantics;
- server restart/reconnect;
- optional Job lifecycle

проверяются на совместимых contract revisions.

Agent repository не должен требовать private Python imports Web Access.

---

# 23. Gate G21 — Documentation consistency

Перед version acceptance:

- `current.md` актуален;
- roadmap/status актуален;
- component design соответствует implementation;
- version non-goals соблюдены;
- new ADR добавлены/linked;
- obsolete decisions superseded, а не оставлены параллельно;
- examples/schema names совпадают с code.

---

# 24. Zero-failure policy

Required gate suite завершается:

```text
0 failed
0 errors
0 unexpected xfail/xpass
```

Known intentional skips разрешены только с documented reason/environment condition.

Нельзя принимать version с «два теста иногда падают, но rerun зелёный».

---

# 25. Flaky policy

Known flaky test является открытым quality defect.

Release gate требует:

- устранить race/flakiness;
- либо доказать, что test неверен и удалить/переписать его;
- не скрывать бесконечным retry.

CI может повторять тест для диагностики, но original flake учитывается.

---

# 26. Skips

Skip допустим для:

- platform-specific optional capability;
- live billable provider profile без secret;
- heavy nightly suite в PR tier;
- feature, явно не входящей в текущую version.

Обязательный acceptance test реализованного scope не может быть permanently skipped.

---

# 27. Live external tests

Live internet/provider smoke полезен, но не является единственным доказательством correctness.

Default CI:

- не зависит от публичных сайтов;
- не делает billable calls.

Release/manual live profile имеет bounded budget и фиксирует дату/provider revision.

---

# 28. Security scan policy

Release artifacts проходят выбранные dependency/container/secret scans.

Результаты классифицируются, а не blindly ignored.

False positive требует documented disposition.

Critical/High policy определяется Gate G6.

---

# 29. Performance regression

После появления baseline version change не должна превышать установленный regression budget без:

- объяснения;
- нового baseline/design rationale;
- принятого tradeoff.

Особенно отслеживаются Browser memory/session и Retrieval/Content large payload.

---

# 30. Resource leak gate

Любая новая Resource type/capability должна иметь cleanup/reconciliation acceptance.

Нельзя выпустить create operation без проверенного terminal/expiration cleanup path.

---

# 31. Retry/cost gate

Billable/provider/network retries проверяются на bounded behavior.

Нельзя выпускать retry loop, способный при outage:

- бесконечно тратить Yandex budget;
- создавать retry storm;
- обходить rate limits.

---

# 32. No hidden orchestration gate

Integration tests должны доказать отсутствие запрещённых hidden transitions:

```text
Search → Retrieval
Retrieval → Browser
Content L1 → OCR/L2
request-bound → Job
```

если caller явно их не инициировал.

---

# 33. Release evidence

Для крупной version acceptance желательно сохранять machine-readable/report artifact:

- commit SHA;
- test counts/results;
- skipped reasons;
- schema diffs;
- migration revision;
- security scan summary;
- load/soak summary, если gate применим;
- live-provider calls = 0/default или explicit budget report.

Это упрощает независимую проверку.

---

# 34. Version-specific gates

Каждый `versions/vX.Y/` document обязан перечислить:

```text
Required gates
Not-applicable gates + reason
Additional version gates
```

Нельзя просто написать «все тесты проходят» без указания, какие классы проверок требуются.

---

# 35. Intermediate implementation patches

Не каждый internal patch обязан проходить full production soak/load, но обязан сохранять baseline предыдущего принятого этапа.

Version implementation sequence может вводить progressive gates:

```text
patch N
→ unit/contract

patch M
→ integration

final version
→ full applicable release gates
```

---

# 36. Coding-agent handoff gate

Большой prompt для Codex/ChatGPT должен содержать:

- canonical docs to read;
- exact implementation scope;
- explicit non-goals;
- files/modules expected;
- migration rules;
- required tests/gates;
- prohibition on silently resolving open architecture questions.

Результат coding agent проверяется фактическими gates, а не его текстовым отчётом.

---

# 37. Acceptance criteria Release Gate system

Gate system считается пригодным, если:

1. Любая версия может однозначно перечислить необходимые проверки.
2. Critical component имеет отдельный gate.
3. Race/security/fault/load не спрятаны под «tests pass».
4. Public schema changes имеют отдельный contract gate.
5. Deployment/upgrade имеют отдельные gates.
6. Own-agent integration явно проверяется.
7. Flaky tests не маскируются retry.
8. Billable external network не нужен default CI.
9. Design/docs consistency является release requirement.
10. Machine-readable evidence можно сохранить для независимого review.

---

# 38. Open questions

До первой production release необходимо определить:

1. Exact static/type tools и strictness.
2. Exact security scan policy/tooling.
3. Baseline hardware/profiles для load.
4. Soak duration/resource limits после Browser benchmark.
5. Performance regression budgets после baseline.
6. Format release evidence (Markdown + JSON report, CI artifacts и т.п.).
7. Cross-repository Agent integration workflow.
8. Какие gates required для каждой ранней pre-1.0 version.
9. Definition production-ready milestone/version.

Эти вопросы будут закрыты roadmap/version planning после завершения design.
