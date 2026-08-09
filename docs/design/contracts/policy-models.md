# Exact dynamic policy models

## Статус

Каноническая public/application-facing модель **dynamic non-secret policy** Web Access v1.

Семантика принадлежит:

- `../policy-and-operations.md`;
- ADR-0019;
- ADR-0020.

Этот документ фиксирует exact typed sections, bounds, defaults/overrides и composition semantics, чтобы v0.7 implementation и REST admin contract не изобретали policy schema самостоятельно.

Secrets, endpoints, DSN, bearer/API keys, internal worker credentials и software hard safety configuration сюда не входят.

---

# 1. Главная модель

Effective policy строится как:

```text
Authenticated PrincipalContext
+
GlobalPolicyDocument
+
optional exact PrincipalPolicyOverride
+
static software/deployment hard ceilings
+
resource ownership/state
→ EffectivePolicy
```

Auth scopes — абсолютная верхняя граница authority.

Dynamic policy может **ограничить**, но не создать отсутствующий scope.

---

# 2. Почему global policy и principal override разделены в REST

Persistent ADR-0019 snapshot может materialize полный immutable revision любым выбранным storage representation.

Но public admin API не требует пересылать все principal overrides при каждом global update.

REST работает с двумя typed views:

```text
GlobalPolicyDocument
PrincipalPolicyOverride
```

Любая mutation всё равно создаёт новую **общую monotonic policy revision** в PostgreSQL и required AuditEvent в той же transaction.

То есть:

```text
update одного principal override
→ revision N+1 всей logical policy state
```

Replica cache инвалидируется top-level revision как и требует ADR-0019.

---

# 3. Общие serialization rules

- unknown fields rejected;
- `schema_version` integer, baseline `1`;
- principal IDs: string `1..128`;
- provider IDs: regex `^[a-z0-9][a-z0-9-]{0,63}$`;
- capability lists unique;
- all integer limits are non-negative/positive exactly as stated;
- omission in `PrincipalPolicyOverride` means inherit global default;
- `null` is not used as synonym for omission unless explicitly stated;
- every override value is validated against the corresponding global maximum and static software hard ceiling.

---

# 4. CapabilityCode

Exact v1 enum:

```text
search
retrieval
content.read
content.parse
browser.read
browser.interact
jobs.read
jobs.create
admin
```

Global policy declares which of these capabilities are operationally enabled.

Principal override may only add extra disables.

Effective capability:

```text
principal auth scope exists
AND global capability enabled
AND capability not disabled by principal override
AND resource/policy check passes
```

No dynamic policy field means «grant scope».

---

# 5. IntegerLimitPolicy

Reusable typed structure for a per-principal quota/rate where operator wants a normal default and a policy maximum:

```json
{
  "default": 10,
  "maximum": 100
}
```

Invariant:

```text
0 <= default <= maximum <= field-specific software ceiling
```

A principal override sets one effective value, which must be:

```text
0 <= override <= global.maximum
```

`0` has field-specific meaning and is allowed only where the field explicitly states that zero disables admission/usage.

---

# 6. GlobalPolicyDocument

```text
schema_version: integer = 1
capabilities: GlobalCapabilityPolicy
search: GlobalSearchPolicy
retrieval: GlobalRetrievalPolicy
content: GlobalContentPolicy
browser: GlobalBrowserPolicy
jobs: GlobalJobsPolicy
audit: GlobalAuditPolicy
```

All fields required in a persisted/current global policy document.

No arbitrary extension dictionary.

---

# 7. GlobalCapabilityPolicy

```text
enabled: array[CapabilityCode] required, unique, 0..9
```

Production bootstrap should explicitly list intended enabled capabilities.

Absence from list means globally disabled.

`admin` can be omitted from ordinary task-service principals while still existing for dedicated admin credentials; the dynamic global flag remains an additional operational gate.

---

# 8. GlobalSearchPolicy

```text
enabled_providers: array[ProviderId] required, 0..32, unique
default_provider: ProviderId required
cache_scope: principal | shared | disabled
requests_per_minute: IntegerLimitPolicy
concurrent_queries: IntegerLimitPolicy
provider_budgets: array[ProviderBudgetPolicy] required, 0..32
```

Cross-field:

- `default_provider` must be in `enabled_providers`;
- every `provider_budgets[].provider_id` unique;
- budget entry for unknown/non-billable provider rejected by runtime registry validation;
- disabling all providers is legal only if `search` capability is globally disabled; otherwise policy invalid.

Software ceilings:

```text
requests_per_minute.maximum <= 1_000_000
concurrent_queries.maximum <= 10_000
```

`default=0` is allowed and means ordinary principals have no Search admission unless overridden, but override still cannot exceed maximum and auth/global capability must permit Search.

---

# 9. ProviderBudgetPolicy

```text
provider_id: ProviderId
period: day | month
default_units: integer 0..1_000_000_000
maximum_units: integer 0..1_000_000_000
```

Invariant:

```text
default_units <= maximum_units
```

Units are provider-defined stable accounting units, not currency.

Period boundaries use UTC.

`0` means no billable upstream unit may be admitted for that scope/period.

Unknown response/send evidence uses conservative accounting according ADR-0020.

---

# 10. GlobalRetrievalPolicy

```text
requests_per_minute: IntegerLimitPolicy
concurrent_items: IntegerLimitPolicy
```

Software ceilings:

```text
requests_per_minute.maximum <= 1_000_000
concurrent_items.maximum <= 10_000
```

These are per-principal admission values. Global deployment/network concurrency ceilings remain static/runtime limits and can be lower.

---

# 11. GlobalContentPolicy

```text
retained_bytes: IntegerLimitPolicy
retained_objects: IntegerLimitPolicy
transient_ttl_seconds: integer 300..31_536_000
job_result_ttl_seconds: integer 300..31_536_000
```

Software ceilings:

```text
retained_bytes.maximum <= 10_995_116_277_760   # 10 TiB logical quota/principal
retained_objects.maximum <= 10_000_000
```

Quota counts **logical owner-visible available ContentObjects**, not physical deduplicated blob bytes.

`retained_bytes.default=0` or `retained_objects.default=0` means new retained Content admission is disabled for ordinary principal unless an override grants a non-zero value within global maximum.

TTL fields are global defaults, not client authority to request infinite retention.

---

# 12. GlobalBrowserPolicy

```text
active_sessions: IntegerLimitPolicy
create_requests_per_minute: IntegerLimitPolicy
idle_ttl_seconds: IntegerLimitPolicy
max_lifetime_seconds: IntegerLimitPolicy
```

Software ceilings:

```text
active_sessions.maximum <= 128
create_requests_per_minute.maximum <= 600
idle_ttl_seconds.default/maximum: 60..900
max_lifetime_seconds.default/maximum: 300..3600
```

Additional invariant:

```text
idle_ttl_seconds.default <= max_lifetime_seconds.default
idle_ttl_seconds.maximum <= max_lifetime_seconds.maximum
```

Worker physical capacity remains independent and may be lower.

Browser create needs both durable DB quota slot and worker capacity.

---

# 13. GlobalJobsPolicy

```text
nonterminal_jobs: IntegerLimitPolicy
active_attempts: IntegerLimitPolicy
create_requests_per_minute: IntegerLimitPolicy
max_global_backlog: integer 0..1_000_000
job_type_attempt_limits: array[JobTypeAttemptLimit] required, 0..32
```

Software ceilings:

```text
nonterminal_jobs.maximum <= 100_000
active_attempts.maximum <= 1_024
create_requests_per_minute.maximum <= 100_000
```

`max_global_backlog=0` rejects new Jobs globally.

`JobTypeAttemptLimit`:

```text
job_type: stable registered job type string 1..64
max_active_attempts_global: integer 0..10_000
```

Unique `job_type`.

Unknown job type rejected against registry at policy validation.

Baseline public types:

```text
retrieval_batch
content_parse_batch
```

---

# 14. GlobalAuditPolicy

```text
browser_mutations: off | metadata
```

`metadata` means durable audit may retain trusted action code, actor/resource IDs, timing/outcome and bounded non-secret metadata, but never form values/page content/passwords/raw headers.

Admin policy mutations/maintenance remain audited regardless of this browser-specific setting.

---

# 15. PrincipalPolicyOverride

```text
principal_id: string 1..128
disabled_capabilities: array[CapabilityCode] unique, 0..9
search: PrincipalSearchOverride | omitted
retrieval: PrincipalRetrievalOverride | omitted
content: PrincipalContentOverride | omitted
browser: PrincipalBrowserOverride | omitted
jobs: PrincipalJobsOverride | omitted
```

No `enabled_capabilities` field.

No arbitrary metadata/dict.

The exact same principal must appear at most once in one logical policy state.

Implementation may impose a bounded override-count safety limit for one policy snapshot; baseline software ceiling:

```text
10_000 explicit principal overrides
```

This is not a limit on principals using global defaults; only on exceptions stored in dynamic policy v1.

---

# 16. PrincipalSearchOverride

All fields optional:

```text
requests_per_minute: integer 0..global.requests_per_minute.maximum
concurrent_queries: integer 0..global.concurrent_queries.maximum
allowed_providers: array[ProviderId] 0..32 unique
provider_budgets: array[PrincipalProviderBudget] 0..32
```

Semantics:

- omitted scalar → global default;
- `allowed_providers` omitted → global enabled providers;
- provided list is intersected with global enabled providers;
- empty list disables provider admission for this principal without changing auth scope;
- provider budget override must be <= matching global `maximum_units`;
- provider not globally enabled cannot be re-enabled by override.

`PrincipalProviderBudget`:

```text
provider_id
units_limit: integer 0..1_000_000_000
```

Provider IDs unique.

---

# 17. PrincipalRetrievalOverride

Optional:

```text
requests_per_minute: integer 0..global maximum
concurrent_items: integer 0..global maximum
```

Omitted → global default.

---

# 18. PrincipalContentOverride

Optional:

```text
retained_bytes: integer 0..global maximum
retained_objects: integer 0..global maximum
```

No principal-specific TTL override in v1 baseline. Retention duration remains global policy class semantics to prevent uncontrolled retention complexity.

---

# 19. PrincipalBrowserOverride

Optional:

```text
active_sessions: integer 0..global maximum
create_requests_per_minute: integer 0..global maximum
idle_ttl_seconds: integer 60..global maximum
max_lifetime_seconds: integer 300..global maximum
```

Cross-field effective values still require:

```text
idle_ttl_seconds <= max_lifetime_seconds
```

Omitted → global defaults.

---

# 20. PrincipalJobsOverride

Optional:

```text
nonterminal_jobs: integer 0..global maximum
active_attempts: integer 0..global maximum
create_requests_per_minute: integer 0..global maximum
```

Per-job-type global capacity is not raised by a principal override.

---

# 21. EffectivePolicy

Internal/application derived immutable model stores at least:

```text
policy_revision
policy_schema_version
principal_id
effective capabilities
effective Search limits/provider set/budgets
effective Retrieval limits
effective Content quotas/retention
effective Browser quotas/TTLs
effective Job quotas
audit policy
loaded_at
```

It is **not** a public writable DTO.

Operation records revision where correctness/audit requires it.

---

# 22. PolicySnapshot public metadata

Admin read response:

```text
revision: integer >=1
schema_version: integer =1
created_at: timestamp
created_by: string 1..128
reason: string 1..2048
global_policy: GlobalPolicyDocument
principal_override_count: integer >=0
```

Normal `GET /admin/policy` does not inline all principal overrides by default.

---

# 23. Principal override public metadata

```text
policy_revision
principal_id
override: PrincipalPolicyOverride
updated_at
updated_by
```

Removing override means future EffectivePolicy uses global defaults after new policy revision.

---

# 24. Revision history summary

```text
revision
schema_version
created_at
created_by
reason
changed_sections: array[string] 1..32
principal_ids_changed: array[string] 0..100, truncated flag if more
```

History endpoint returns summaries/cursors, not all snapshot bodies inline.

A separate authorized revision detail endpoint may return `GlobalPolicyDocument` and bounded override metadata; bulk export/backup remains an operator/offline function rather than giant ordinary API response.

---

# 25. Validation against runtime registries

Pure JSON Schema cannot prove:

- provider exists/is billable;
- job type registered;
- policy values are below current static deployment ceiling if deployment is stricter than software ceiling.

Therefore admin update runs two layers:

```text
JSON/Pydantic structural validation
→ runtime registry/static ceiling validation
```

Failure returns structured field/code details.

Never silently drop unsupported provider/job/capability entry.

---

# 26. Bootstrap policy rule

Production must provide an explicit valid bootstrap global policy.

Local/dev may use compiled conservative sample.

Bootstrap sample must not accidentally enable billable provider with unlimited budget.

Recommended local sample direction:

```text
SearXNG enabled/default
Yandex disabled or budget 0 unless explicitly configured
small Browser/Job/Content defaults
admin available only dedicated admin principal
```

---

# 27. Compatibility

Policy `schema_version=1` is part of rolling compatibility.

Additive optional fields require software compatibility review.

Changing meaning/default/bounds of existing field is compatibility-sensitive.

A new schema version cannot become current until all required active software revisions can read it according ADR-0019.
