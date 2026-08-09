# ADR-0009 — Browser Worker registry, session routing и self-fencing lease

**Статус:** accepted

## 1. Контекст

ADR-0001 выбрал direct RPC к owning Browser Worker.

Теперь необходимо определить:

- как API replicas узнают endpoint текущего worker;
- как обнаруживается worker restart/loss;
- как session route восстанавливается после Redis loss;
- как stale/partitioned worker перестаёт выполнять actions;
- как избежать ложного failover live BrowserContext.

---

## 2. Решение — sources of truth

```text
PostgreSQL
→ authoritative BrowserSession lifecycle + owner worker_id/generation

Redis
→ ephemeral worker registry + session route cache

Browser Worker memory
→ live BrowserContext/session state
```

Redis loss не удаляет durable BrowserSession row, но может временно сделать route unavailable до worker re-registration/cache rebuild.

---

## 3. Worker identity

Worker имеет два identifiers:

```text
worker_id
worker_generation
```

`worker_id` — stable logical instance identity в рамках deployment, обычно configuration/hostname/stateful replica identity.

`worker_generation` — random opaque value на каждый process startup.

Restart меняет generation.

---

## 4. Registration

Browser Worker на startup вызывает authenticated internal Control Plane endpoint:

```text
register(worker_id, generation, endpoint, capacity, runtime/profile revision)
```

Control Plane:

1. проверяет internal service principal;
2. валидирует endpoint against internal network policy;
3. проверяет runtime compatibility;
4. пишет/обновляет Redis worker registry;
5. возвращает lease timing/config metadata;
6. worker начинает heartbeat loop.

---

## 5. Redis worker key

Logical namespace:

```text
wa:browser:worker:v1:<worker_id>
```

Value/hash содержит bounded metadata:

```text
generation
internal_endpoint
state
capacity
active_sessions
profile/runtime revision
last_heartbeat/server timestamp
```

Key имеет TTL.

Никаких external client tokens/secrets.

---

## 6. Heartbeat defaults

Initial defaults:

```text
heartbeat interval = 5 seconds
worker lease TTL = 20 seconds
final loss grace = 30 seconds total without confirmed heartbeat
```

Все значения configurable, но validation сохраняет:

```text
heartbeat << lease TTL <= final loss grace
```

Control Plane timestamps authoritative where possible.

---

## 7. Worker self-fencing

Ключевой invariant:

> Worker, который не способен подтвердить lease у Control Plane, не должен продолжать бесконечно обслуживать mutating browser actions.

Worker отслеживает время последнего successful heartbeat acknowledgement.

Если lease TTL истёк локально:

```text
worker → fenced/draining
→ reject new session creates/actions
→ begin bounded cleanup/close live sessions
```

Это защищает от network partition, где stale worker всё ещё жив, но Control Plane уже не может безопасно считать его owner.

---

## 8. Final loss decision

Control Plane/Reconciler не обязан помечать BrowserSessions `lost` ровно в момент первого Redis TTL expiry.

До `final loss grace` допускается:

- worker temporarily unavailable;
- actions получают retryable worker-unavailable до remaining deadline;
- session остаётся `ready`/unavailable-in-practice.

После final grace без той же generation heartbeat:

```text
BrowserSession → lost
```

и больше не resurrected.

---

## 9. Worker recovery до final loss

Если **тот же process/generation** восстанавливает heartbeat до final loss decision и ещё не self-fenced/закрыл sessions:

- registry восстанавливается;
- existing sessions могут продолжить работу.

Если worker уже self-fenced/закрыл конкретную session, он сообщает её отсутствие, и Control Plane помечает session `lost`.

---

## 10. Recovery после final loss запрещён

Если PostgreSQL BrowserSession уже `lost`:

- поздний heartbeat того же worker не resurrect session;
- worker registration response/next reconciliation сообщает terminal session IDs или worker получает command очистить остаточные contexts;
- actions к lost session rejected даже если stale worker утверждает, что context ещё существует.

Это делает durable state authority окончательной после loss decision.

---

## 11. Session routing metadata

PostgreSQL BrowserSession row хранит:

```text
worker_id
worker_generation
```

после успешного create/ready transition.

Не хранить internal endpoint как authoritative durable field: endpoint может меняться между deployment/network revisions.

---

## 12. Redis session route cache

Optional fast route key:

```text
wa:browser:session:v1:<session_id>
```

с:

```text
worker_id
worker_generation
session revision
```

TTL не превышает session max lifetime + grace.

Route cache можно восстановить из PostgreSQL BrowserSession.

---

## 13. Routing algorithm

Control Plane:

1. validate session/owner/state in application repository;
2. получить worker_id/generation из session metadata;
3. прочитать current worker registry;
4. generation должен совпадать;
5. endpoint берётся только из current registry;
6. direct RPC согласно ADR-0001.

Redis session route может ускорить шаг 2, но application authorization/state check не обходится.

---

## 14. Redis loss

После Redis restart/flush:

- workers heartbeat/register снова создают worker registry;
- session route cache cold;
- API читает PostgreSQL owner worker IDs;
- если required worker generation reappears в final grace → route recovers;
- иначе session → lost после grace.

Redis loss сам по себе не означает мгновенную потерю live session.

---

## 15. Session creation placement

Placement использует worker registry.

Candidate worker:

- `ready`;
- compatible revision/profile;
- active_sessions < capacity;
- heartbeat current.

Selection baseline:

```text
минимальный active_sessions / capacity ratio
```

Tie-break deterministic/randomized stable enough to avoid hotspot; exact strategy internal.

---

## 16. Capacity race

Registry active count является observational, а не atomic reservation.

Final capacity enforcement выполняет worker под локальным lock при create_session RPC.

Если выбранный worker ответил `capacity_unavailable` **до создания BrowserContext**:

- Control Plane может выбрать другой ready worker в пределах create deadline;
- это safe placement retry, потому что rejected worker доказал no session creation.

Никакой Redis distributed slot reservation baseline не нужен для correctness.

---

## 17. BrowserSession creation crash protocol

Control Plane flow:

1. DB insert `creating` BrowserSession;
2. выбрать worker;
3. DB записать intended `worker_id/generation` в creating metadata/revision;
4. direct RPC create с заранее server-generated `session_id`;
5. worker создаёт live session + initial page и возвращает result;
6. DB CAS `creating → ready`, сохраняет worker/page metadata;
7. write Redis route cache;
8. return client.

---

## 18. Crash после worker create до DB ready

Durable row остаётся `creating` с intended worker.

Reconciler после bounded creation timeout:

- пытается запросить owning worker session status;
- если live context существует, **закрывает его**;
- помечает logical session `failed`;
- не публикует orphan session как ready задним числом.

Причина: original caller мог не получить handle/result; safer cleanup, чем hidden resource resurrection.

---

## 19. Crash после DB ready до response

Session остаётся valid `ready` и будет очищена client explicit close/TTL/reaper.

Client, потерявший response, может создать новую session; старая является bounded orphan resource и expire.

Baseline MCP не добавляет idempotency-key argument только ради этого rare internal-resource duplicate.

REST может позже использовать Idempotency-Key на create.

---

## 20. Session close routing unavailable

Если explicit close не может достичь owning worker:

- durable session → `closing`/cleanup_requested;
- best-effort RPC повторяется/reconciler до final worker loss/cleanup deadline;
- при подтверждённом worker loss session terminal `lost`, live context считается недоступным и worker self-fencing обязан его закрыть при partition;
- client close operation возвращает honest lifecycle outcome, не fake success.

---

## 21. API replica statelessness

Ни один API replica не хранит единственный authoritative routing map в RAM.

Local cache допустим на короткий TTL, но Redis/PostgreSQL/worker generation validation остаются canonical recovery path.

---

## 22. Registry endpoint validation

Worker-advertised endpoint должен быть:

- internal HTTP(S) scheme according deployment policy;
- host/IP in approved internal network/service discovery namespace;
- allowed port;
- no userinfo/query fragments;
- not arbitrary public URL.

Compromised worker credential не должен зарегистрировать browser action endpoint на интернет attacker host без policy check.

---

## 23. Worker states

Registry states baseline:

```text
starting
ready
draining
fenced
failed
```

`at_capacity` лучше выражать capacity counters, а не отдельным durable state; placement просто исключает candidate.

---

## 24. Drain

Operator/deployment marks worker draining через internal control/config.

Worker heartbeat advertises `draining`.

- no new sessions;
- existing actions continue;
- rolling shutdown follows deployment.md.

---

## 25. Tests

Required:

1. register/heartbeat TTL;
2. worker restart same ID new generation;
3. stale generation routing rejected;
4. temporary heartbeat outage recover before grace;
5. self-fence after lease expiry;
6. final loss → sessions lost;
7. no resurrection after lost;
8. Redis flush → registry/session route rebuild;
9. two API replicas create sessions concurrently;
10. worker capacity race + safe re-placement;
11. crash after create step 4/5;
12. create reconciler closes orphan context;
13. close while registry unavailable;
14. draining worker receives no new session;
15. malicious worker advertises external endpoint → rejected.

---

## 26. Consequences

Плюсы:

- PostgreSQL/Redis responsibilities clear;
- no live session failover illusion;
- partitioned worker self-fences;
- Redis loss recoverable;
- placement simple and worker enforces final capacity;
- API replicas stateless.

Минусы:

- session может быть temporarily unavailable during heartbeat outage;
- worker partition > lease destroys sessions even if browser process technically healthy;
- create crash can create temporary orphan context until reconciliation;
- requires internal registration/heartbeat API.

Эти trade-offs принимаются ради single-owner correctness.

---

## 27. Не определяется

- exact Redis hash serialization;
- exact internal registration endpoint paths;
- exact local cache TTL;
- exact worker_id generation from Kubernetes/Compose;
- detailed reconciler batch SQL;
- operator drain API surface.

Они реализуются v0.4 sequence без изменения ownership protocol.
