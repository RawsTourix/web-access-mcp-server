# ADR-0002 — Authentication baseline: Bearer AuthProvider + principal scopes

**Статус:** accepted

## 1. Контекст

Web Access должен:

- защищать REST и MCP endpoints;
- создавать owner-scoped Content/Browser/Job resources;
- поддерживать service-to-service использование собственным ИИ-агентом;
- не привязывать application layer к одному auth protocol;
- оставаться готовым к будущему multi-user/delegated identity.

На раннем этапе собственный агент ещё не обязан иметь полноценную user/OIDC infrastructure, поэтому требование полноценного identity provider с первого коммита создало бы лишнюю внешнюю зависимость.

---

## 2. Требования

Authentication design должен:

1. использовать стандартный HTTP authentication channel, а не MCP tool arguments;
2. возвращать trusted `PrincipalContext` application layer;
3. поддерживать несколько service principals;
4. поддерживать capability/scopes;
5. не хранить raw tokens в logs/database;
6. позволять rotation;
7. использовать constant-time secret comparison;
8. отделять public client auth от Browser Worker internal auth;
9. не доверять произвольному `user_id` header как end-user identity;
10. позволять позднее добавить signed JWT/OIDC/delegation без смены Resource ownership contracts.

---

## 3. Рассмотренные варианты

### A. Один global API key в custom header

Просто, но плохо выражает principals/scopes и усложняет стандартные clients.

### B. Static/configured Bearer tokens через `Authorization`

Несколько service principals, стандартный HTTP header, простой local/production secret management.

### C. Сразу обязательный OAuth2/OIDC/JWT issuer

Сильная production identity model, но требует отдельного identity provider и преждевременно связывает foundation deployment с ещё не существующей account architecture собственного агента.

### D. Доверять `X-User-ID`/`owner_id`, переданному клиентом

Неприемлемо без подписанной/delegated identity: client мог бы выбрать чужого owner.

---

## 4. Решение

Принимается **AuthProvider abstraction** с baseline реализацией **configured Bearer service tokens**.

HTTP transport:

```text
Authorization: Bearer <secret>
```

Transport auth adapter:

```text
credential
→ AuthProvider.authenticate(...)
→ PrincipalContext
→ Application ExecutionContext
```

Application layer не знает, был ли principal получен из static token, JWT, OIDC или другого provider.

---

## 5. PrincipalContext

Минимальная trusted модель:

```text
PrincipalContext
├── principal_id
├── principal_type
├── scopes/capabilities
├── actor metadata/revision
└── optional delegated subject (future)
```

Baseline static provider создаёт service principal.

Например:

```text
principal_id = builtin-agent
principal_type = service
```

Exact Python model определяется v0.1 implementation.

---

## 6. Resource owner baseline

Если отдельный delegated subject отсутствует:

```text
resource owner = authenticated principal
```

Следовательно ContentObject/BrowserSession/Job принадлежат service principal.

Это безопаснее, чем принимать untrusted caller-supplied owner ID.

---

## 7. Future delegated user identity

Multi-user собственный агент позднее может передавать signed/delegated identity.

Целевая conceptual model:

```text
authenticated actor = agent-service
subject/owner = end-user principal
```

Но subject должен быть:

- криптографически подтверждён;
- разрешён actor-у delegation policy;
- не управляться LLM/tool arguments.

Варианты реализации позднее:

- JWT, подписанный/выданный trusted issuer;
- OAuth/OIDC access token;
- workload identity + signed delegation assertion.

Это отдельное ADR/auth extension.

---

## 8. Почему не `X-User-ID`

Header вида:

```text
X-User-ID: alice
```

не считается identity proof сам по себе.

Даже если private service network уменьшает риск, architecture не должна строить owner isolation на строке, которую любой authenticated service caller может подменить.

Если подобный header используется как transport carrier, его значение должно быть связано с signed/delegated credential и проверено AuthProvider.

---

## 9. Bearer token storage

Raw token является secret.

Production source:

- environment secret;
- Docker/Kubernetes secret file;
- future secret manager.

Repository хранит только example placeholders.

Application config может содержать token references/principal descriptors, но raw token не попадает в logs/status/API.

---

## 10. Token comparison

Baseline static provider сравнивает credential constant-time.

Для нескольких configured tokens implementation может использовать server-side derived fingerprint/hash lookup, но нельзя хранить/логировать raw token как identifier.

Точная KDF/hash structure определяется implementation/security review; simple non-password random high-entropy bearer token не требует password-style slow hashing для online authentication correctness, но storage exposure risk должен учитываться.

---

## 11. Token entropy

Configured bearer token должен быть high-entropy random secret, а не human password.

Docs/scripts должны предоставлять безопасный generation method.

Нельзя использовать predictable default token вроде:

```text
changeme
admin
secret
```

в production profile.

---

## 12. Rotation

AuthProvider/config должен позволять временно иметь несколько active token credentials/principal bindings для rotation.

Canonical principal_id при rotation не обязан меняться.

После rotation old credential удаляется/disable через configuration revision.

---

## 13. Scopes/capabilities

Principal descriptor должен позволять allowlist capabilities.

Предварительные semantic scopes:

```text
search
retrieval
content.read
content.write
browser.read
browser.interact
jobs.read
jobs.write
admin
```

Exact scope taxonomy проектируется REST/MCP implementation и может быть более компактной.

Scope не заменяет owner/resource policy.

---

## 14. MCP authentication

Streamable HTTP MCP использует тот же внешне authenticated principal model.

Credential передаётся MCP HTTP transport, **не** tool argument.

LLM никогда не видит/генерирует Bearer secret.

Tool call ExecutionContext уже содержит PrincipalContext.

---

## 15. REST authentication

REST использует тот же AuthProvider.

FastAPI dependency:

```text
Authorization header
→ auth adapter
→ PrincipalContext
```

Routers не сравнивают токены самостоятельно.

---

## 16. Public health

Минимальный `/health/live` может быть unauthenticated для orchestrator, если deployment network policy это допускает.

Detailed `/health/status`, admin/provider/worker diagnostics требуют authorization или отдельной internal network policy.

Readiness access policy deployment-specific.

---

## 17. Browser Worker internal auth — отдельный principal

Internal Browser Worker RPC **не использует тот же bearer token**, что внешний Agent/REST client.

Используется отдельный service identity/credential namespace.

Например:

```text
principal_type = internal_service
principal_id = browser-worker/<identity>
```

или Control Plane credential для action calls.

Compromise внешнего client token не должен автоматически давать право вызывать internal worker API напрямую.

---

## 18. Internal Browser registration auth

Worker registration/heartbeat в Control Plane использует отдельный internal credential.

Control Plane проверяет:

- credential scope;
- worker identity/generation;
- allowed endpoint/network metadata.

Worker не может зарегистрироваться как admin/client principal.

---

## 19. Job Worker internal identity

Job Worker также может иметь service principal для internal operations/diagnostics, если transport требует.

Он не должен использовать внешний user/agent bearer token.

Job owner берётся из durable Job metadata, а не из worker identity.

---

## 20. Authorization location

Authentication transport-specific.

Authorization/resource ownership — application/resource boundary.

Нельзя считать route dependency единственной protection:

```text
GET /content/{id}
```

должен проверять owner/policy через ContentApplicationService/authorization port.

---

## 21. AuthProvider port

Core direction:

```text
AuthProvider
└── authenticate(AuthCredential, RequestContext) -> PrincipalContext
```

Concrete adapters:

```text
StaticBearerAuthProvider        baseline
Jwt/OidcAuthProvider            future
CompositeAuthProvider           future, если оправдан
```

Application modules зависят от PrincipalContext/policy ports, а не concrete AuthProvider.

---

## 22. Authentication errors

Различаются:

```text
missing_credentials
invalid_credentials
expired_credentials
credential_disabled
insufficient_scope
owner_access_denied
```

Первые относятся к authentication/transport mapping; scope/owner denial — authorization/application policy.

Public error не сообщает, какой именно configured token почти совпал/существует.

---

## 23. Rate limiting by principal

После authentication service может использовать `principal_id` как key для rate/quota enforcement.

Raw token не используется как long-term resource owner ID и не должен попадать в metrics labels.

---

## 24. Audit

Security-sensitive events могут фиксировать:

- principal_id;
- authentication method/provider;
- scope/policy result;
- operation/resource ref;

но не raw credential.

Exact durable audit policy определяется позже.

---

## 25. Consequences — плюсы

- минимальная external dependency v0.1;
- стандартный `Authorization: Bearer`;
- несколько service principals/scopes;
- owner model появляется сразу;
- MCP/REST используют один auth layer;
- LLM не видит secrets;
- легко использовать собственным агентом;
- future OIDC/JWT не требует смены application/resource contracts.

---

## 26. Consequences — ограничения

- static bearer token сам по себе не выражает end-user identity собственного multi-user агента;
- rotation/configuration требует operator process;
- без future delegation все users одного Agent service principal принадлежат одному service ownership domain на стороне Web Access;
- для public end-user REST потребуется более сильная identity integration.

Эти ограничения принимаются для foundation, но multi-user launch собственного агента должен закрыть delegated identity до использования Web Access user-owned browser/content sessions.

---

## 27. Не определяется этим ADR

- конкретный token config file/environment schema;
- exact random token length/encoding;
- exact scope names final set;
- JWT/OIDC issuer;
- future delegated subject token format;
- admin role model;
- mTLS deployment;
- session-based Web UI authentication.

---

## 28. Acceptance

Baseline auth считается реализованным, если:

1. REST/MCP требуют valid Bearer credential кроме explicitly public health endpoints.
2. LLM schemas не содержат auth secret fields.
3. Несколько configured principals работают независимо.
4. Resources owner-scoped authenticated principal.
5. Cross-principal handle access rejected.
6. Token comparison constant-time.
7. Raw tokens отсутствуют в logs/status/errors.
8. Token rotation поддерживает overlap credentials.
9. Scopes enforce capability access.
10. Browser Worker internal credential отделён от external client credential.
11. AuthProvider можно заменить future JWT/OIDC adapter без изменения Application Services.

---

## 29. Затронутые документы

ADR конкретизирует:

- `../security.md`;
- `../resource-model.md`;
- `../application-contracts.md`;
- `../rest-api.md`;
- `../mcp.md`;
- `../deployment.md`;
- `../roadmap.md`.
