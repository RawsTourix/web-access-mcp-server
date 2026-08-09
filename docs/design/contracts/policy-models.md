# Exact dynamic policy models

## Статус

Каноническая public/application-facing модель **dynamic non-secret task/resource policy** Web Access v1.

Семантика принадлежит:

- `../policy-and-operations.md`;
- ADR-0019;
- ADR-0020;
- ADR-0023.

Этот документ фиксирует exact typed sections, bounds, defaults/overrides и composition semantics для v0.7 implementation и Admin REST.

Secrets, endpoints, DSN, bearer/API keys, internal worker credentials и static software hard safety configuration сюда не входят.

**Admin control-plane authority не является dynamic task capability:** `admin:read/admin:write` принадлежат trusted AuthProvider/deployment boundary согласно ADR-0023.

---

# 1. Effective policy

```text
Authenticated PrincipalContext task scopes
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

Dynamic policy может ограничить task/resource admission, но не создать отсутствующий scope.

Admin REST authorization вычисляется отдельно по ADR-0023 и не может быть self-disabled этим document.

---

# 2. Global policy и principal overrides

Persistent ADR-0019 state остаётся одной logical monotonic policy revision.

Public Admin REST использует два typed views:

```text
GlobalPolicyDocument
PrincipalPolicyOverride
```

Это позволяет менять одного principal без гигантского request со всеми overrides.

Любая mutation всё равно создаёт новую общую revision:

```text
update global defaults
→ revision N+1

update/delete one principal override
→ revision N+1
```

Replica cache invalidates by top-level revision.

---

# 3. Serialization rules

- unknown fields rejected;
- `schema_version` integer, baseline `1`;
- principal IDs: string `1..128`;
- provider IDs: regex `^[a-z0-9][a-z0-9-]{0,63}$`;
- task capability lists unique;
- integer limits exact as stated;
- omission in `PrincipalPolicyOverride` means inherit global default;
- `null` is not synonym for omission unless explicitly stated;
- every override validated against corresponding global maximum and static software hard ceiling.

---

# 4. TaskCapabilityCode

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
```

`admin` намеренно отсутствует.

Global policy declares operationally enabled **task capabilities**.

Principal override may only add extra disables.

Effective task capability:

```text
authenticated task scope exists
AND global capability enabled
AND capability not disabled by principal override
AND resource/policy check passes
```

No dynamic field means «grant scope».

---

# 5. IntegerLimitPolicy

Reusable structure:

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

Principal override effective value:

```text
0 <= override <= global.maximum
```

`0` disables corresponding admission/usage only where field semantics below permit zero.

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

All fields required in current persisted global policy view.

No arbitrary extension dictionary.

---

# 7. GlobalCapabilityPolicy

```text
enabled: array[TaskCapabilityCode] required, unique, 0..8
```

Production bootstrap explicitly lists intended task capabilities.

Absence means dynamically disabled for task principals even if AuthProvider scope exists.

Admin API availability is not controlled here.

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

- `default_provider` must be in `enabled_providers` when Search task capability enabled;
- if Search globally disabled, empty provider list is allowed and `default_provider` may use reserved value `none`;
- if Search enabled, `default_provider="none"` is invalid;
- `provider_budgets[].provider_id` unique;
- unknown/non-billable budget entry rejected by runtime provider registry validation.

Software ceilings:

```text
requests_per_minute.maximum <= 1_000_000
concurrent_queries.maximum <= 10_000
```

`default=0` means global default admission is zero until principal override chooses value <= maximum.

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

`0` means no billable upstream unit admission for that scope/period.

Unknown send/response evidence follows conservative accounting ADR-0020.

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

These are per-principal policy limits; deployment/global network ceilings remain independent and may be lower.

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

Quota counts logical owner-visible available ContentObjects, not physical deduplicated blob bytes.

`default=0` on retained quota disables new retained Content admission for default principal policy.

TTL fields are global policy defaults; no client infinite-retention authority.

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

Cross-field:

```text
idle_ttl_seconds.default <= max_lifetime_seconds.default
idle_ttl_seconds.maximum <= max_lifetime_seconds.maximum
```

Worker physical capacity remains independent and may be lower.

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

`job_type` unique and runtime-registry validated.

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

`metadata` permits durable audit of trusted action code, actor/resource IDs, timing/outcome and bounded non-secret metadata only.

Admin policy/maintenance mutations remain audited independently of this Browser setting.

---

# 15. PrincipalPolicyOverride

```text
principal_id: string 1..128
disabled_capabilities: array[TaskCapabilityCode] unique, 0..8
search: PrincipalSearchOverride | omitted
retrieval: PrincipalRetrievalOverride | omitted
content: PrincipalContentOverride | omitted
browser: PrincipalBrowserOverride | omitted
jobs: PrincipalJobsOverride | omitted
```

No enabled-capabilities field, no admin control field, no arbitrary dict.

Same principal appears at most once in one logical policy state.

Software ceiling:

```text
10_000 explicit principal overrides / logical policy state
```

This is not a limit on principals using global defaults.

---

# 16. PrincipalSearchOverride

Optional fields:

```text
requests_per_minute: integer 0..global maximum
concurrent_queries: integer 0..global maximum
allowed_providers: array[ProviderId] 0..32 unique
provider_budgets: array[PrincipalProviderBudget] 0..32
```

Semantics:

- omitted scalar → global default;
- `allowed_providers` omitted → global enabled providers;
- provided list intersected with global enabled providers;
- empty list disables provider admission for this principal;
- provider not globally enabled cannot be re-enabled;
- budget override <= global `maximum_units`.

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

No principal-specific retention TTL in v1 baseline.

---

# 19. PrincipalBrowserOverride

Optional:

```text
active_sessions: integer 0..global maximum
create_requests_per_minute: integer 0..global maximum
idle_ttl_seconds: integer 60..global maximum
max_lifetime_seconds: integer 300..global maximum
```

Effective cross-field:

```text
idle_ttl_seconds <= max_lifetime_seconds
```

Omitted → global default.

---

# 20. PrincipalJobsOverride

Optional:

```text
nonterminal_jobs: integer 0..global maximum
active_attempts: integer 0..global maximum
create_requests_per_minute: integer 0..global maximum
```

Per-job-type global capacity cannot be raised by principal override.

---

# 21. EffectivePolicy

Internal/application immutable derived model contains at least:

```text
policy_revision
policy_schema_version
principal_id
effective task capabilities
effective Search provider set/limits/budgets
effective Retrieval limits
effective Content quotas/retention
effective Browser quotas/TTLs
effective Job quotas
audit policy
loaded_at
```

It is not public writable DTO.

Admin control-plane authorization data is not sourced from this model.

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
principal_override_count: integer 0..10_000
```

Normal current-policy read does not inline all overrides.

---

# 23. Principal override public metadata

```text
policy_revision
principal_id
override: PrincipalPolicyOverride
updated_at
updated_by
```

Removing override means future task EffectivePolicy inherits global defaults after new revision.

---

# 24. Revision history summary

```text
revision
schema_version
created_at
created_by
reason
changed_sections: array[string] 1..32
principal_ids_changed: array[string] 0..100
principal_ids_truncated: bool
```

History endpoints return summaries/cursors, not giant full snapshot bundles.

---

# 25. Runtime validation

JSON Schema cannot prove:

- provider exists/is billable;
- job type registered;
- deployment hard ceiling stricter than software ceiling.

Admin mutation therefore performs:

```text
structural JSON/Pydantic validation
→ provider/job registry validation
→ static hard-ceiling validation
→ cross-section policy validation
```

Failure returns structured repairable fields/codes.

No silent ignoring.

---

# 26. Admin authority invariant

Policy schema must reject task capability value:

```text
admin
```

Admin REST remains protected by:

```text
AuthProvider admin:read/admin:write
+
deployment/network boundary
```

Dynamic task policy cannot make authorized policy read/update/rollback unreachable.

Production runbook must define admin credential/network recovery independent of dynamic task policy.

---

# 27. Bootstrap policy

Production requires explicit valid bootstrap global policy.

Local/dev may use conservative compiled sample.

Safe sample direction:

```text
SearXNG enabled/default
Yandex disabled or budget 0 unless explicitly configured
small Browser/Job/Content defaults
admin credentials managed separately by AuthProvider/deployment
```

Bootstrap must not accidentally enable billable provider with unlimited budget.

---

# 28. Compatibility

`schema_version=1` participates in rolling compatibility.

Additive optional fields require review.

Changing meaning/default/bounds is compatibility-sensitive.

New schema version cannot become current until required active software revisions can read it according ADR-0019.
