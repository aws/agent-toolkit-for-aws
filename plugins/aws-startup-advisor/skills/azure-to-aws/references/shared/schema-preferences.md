# Schema — `preferences.json`

Contract for the Clarify artifact. `clarify-assemble.md` is its single creator.

## The justification key is `source`, and it is REQUIRED on `DETECTED`

A row's shape is `disposition`, `value`, `default`, plus **exactly one** justification key.
Which key depends on the disposition:

| Disposition                   | Required key                           | Holds                                                                                                                   |
| ----------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `DETECTED`                    | **`source`**                           | _What in the estate was read._ "every resource is westeurope", "source is `Microsoft.Cache/Redis`, not redisEnterprise" |
| `PROPOSED`                    | none required                          | the value came from the documented default, and `default` already says so                                               |
| `ESSENTIAL`                   | `context` when there is useful framing | what the user needs in order to answer. `unanswered: true` + `blocks_phase: true` when left null                        |
| `N/A`                         | **`reason`**                           | why the category or row does not apply                                                                                  |
| any, when a blocker forced it | **`forced_by`**                        | the `hard_blockers` key that removed the choice                                                                         |

**`DETECTED` means READ FROM THE ESTATE, so it must say what it read.** A `DETECTED` row
whose `value` equals its `default` and which carries no `source` is indistinguishable from a
**promoted default**, and that distinction is the whole point of decision 13.5c: Design's
rationale prints "you chose Elastic Beanstalk" differently from "we assumed Elastic
Beanstalk", and the report prints the difference — but only if this file recorded which
happened.

**Use these key names and no others.** Not `note`, not `mapped_from`, not `detail`, not
`why`. Capability run 5 used `note` and `mapped_from` for nine rows whose content was
entirely correct, and the assertion failed on the key name rather than the substance —
because nothing here said which name to use. Between that run and the committed golden there
were **nine different justification key names in play**. A field a fixture keys on has to be
named by a rule, exactly as `service_id` does in `schema-design-aws.md`.

Extra keys are allowed alongside the required one when they carry genuinely different
information — `residency_warning`, `source_ha_context`, `conflict` — but they never
substitute for it.

## Disposition vocabulary

Every row carries one of four dispositions, and the distinction is load-bearing:

| Disposition | Meaning                                                               |
| ----------- | --------------------------------------------------------------------- |
| `DETECTED`  | read from the estate; shown for confirmation, not asked               |
| `PROPOSED`  | the skill's recommendation with a default the user may change         |
| `ESSENTIAL` | cannot be defaulted; the phase does not complete until it is answered |
| `N/A`       | considered and does not apply to this estate                          |

`N/A` is written explicitly, never omitted. An absent key and a considered `N/A` are
different facts, and the report distinguishes them — "we checked your estate for SQL
licensing exposure and found none" is a different statement from silence.

## Shape

```jsonc
{
  "phase": "clarify",
  "global": {
    "target_region": { "disposition": "DETECTED", "value": "eu-west-1", "default": "eu-west-1" },
    "user_geography": {
      "disposition": "PROPOSED",
      "value": "single-region",
      "default": "single-region"
    },
    "environment_scope": { "disposition": "DETECTED", "value": ["prod"], "default": ["prod"] },
    "migration_window": { "disposition": "PROPOSED", "value": null, "default": null }
  },
  "design_constraints": {
    "compliance": { "disposition": "ESSENTIAL", "value": [], "default": null },
    "cpu_architecture": { "disposition": "PROPOSED", "value": "x86_64", "default": "x86_64" },
    "compute_target": { "disposition": "PROPOSED", "value": null, "default": "elastic_beanstalk" },
    "cost_optimization": { "disposition": "PROPOSED", "value": null, "default": "balanced" },
    "traffic_pattern": { "disposition": "PROPOSED", "value": null, "default": "steady" },
    "long_lived_connections": { "disposition": "PROPOSED", "value": null, "default": false },
    "vm_cutover": { "disposition": "ESSENTIAL", "value": "mgn", "default": null }
  },
  "data": {
    "availability": {
      "disposition": "ESSENTIAL",
      "value": "single-az",
      "default": null,
      "source_ha_context": "pg-contoso-store: ZoneRedundant, standby zone 2"
    },
    "db_cutover": { "disposition": "ESSENTIAL", "value": "dms", "default": null },
    "traffic_pattern": { "disposition": "PROPOSED", "value": null, "default": "steady" },
    "storage_io": { "disposition": "PROPOSED", "value": null, "default": "medium" },
    "cosmos_rw_split": { "disposition": "N/A", "value": null, "default": null },
    "redis_modules": { "disposition": "DETECTED", "value": false, "default": false }
  },
  "baseline": {
    "azure_monthly_spend": { "disposition": "ESSENTIAL", "value": null, "default": null }
  },
  "identity": {
    "disposition": "PROPOSED",
    "value": "identity_center_reinvite",
    "default": "identity_center_reinvite"
  },
  "licensing": {
    "windows_model": {
      "disposition": "ESSENTIAL",
      "value": "license_included",
      "default": null,
      "context": "4 Windows VMs, 14 vCPUs total"
    },
    "sql_model": { "disposition": "N/A", "value": null, "default": null },
    "ahub_in_use": { "disposition": "DETECTED", "value": false, "default": false },
    "blockers": [{ "azure_id": "<azure_id>", "code": "azure_edition_windows_server" }]
  },
  "app_service_plans": [
    {
      "plan_azure_id": "<azure_id>",
      "hosted_app_count": 5,
      "isolation_split": { "disposition": "PROPOSED", "value": false, "default": false }
    }
  ],
  "clusters": [
    {
      "cluster_id": "<slug>",
      "pattern_id": {
        "disposition": "DETECTED",
        "value": "unclassified",
        "default": "unclassified"
      }
    }
  ],
  "workshop": {}
}
```

Which fragment owns which section:

| Section                                                      | Fragment                                                                         |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `global`, `design_constraints.cost_optimization`, `baseline` | `clarify-global.md`                                                              |
| the rest of `design_constraints`, `app_service_plans[]`      | `clarify-compute.md`                                                             |
| `data`                                                       | `clarify-database.md`                                                            |
| `licensing`                                                  | `clarify-licensing.md` (or an N/A stub from the assembler when it does not fire) |
| `identity`                                                   | `clarify-identity.md`                                                            |
| `clusters[]`                                                 | the assembler, from `azure-resource-clusters.json`                               |

## The two rules that carry the most weight

**`ESSENTIAL` + `value: null` is the completion gate.** An essential row has no default _on
purpose_, and the phase must not complete while one is unanswered. This is the only place
the contract can express "shown and not answered", and the assembler's checklist asserts it.

**A value taken from its default stays `PROPOSED`.** Never promote it to `DETECTED`, which
means _read from the estate_, and never to a user decision. Design's rationale prints "you
chose Elastic Beanstalk" differently from "we assumed Elastic Beanstalk", and the report
distinguishes them — but only if this file recorded which happened.

## Non-obvious defaults

- **`cpu_architecture` defaults to `x86_64`**, diverging from the repo-wide Graviton default
  on purpose. See SKILL.md § Philosophy. When Windows is present the row is DETECTED rather
  than proposed, because it is not a choice.
- **`data.availability` defaults to `single-az`, explicitly not Aurora** — and becomes
  ESSENTIAL when the source is zone-redundant, because silently downgrading resilience
  someone pays for today is the expensive mistake in both directions.
- **`identity` defaults to a fresh IAM Identity Center re-invite**, not Entra ID federation:
  defaulting to federation would leave the migration depending on the cloud being left.
- **`isolation_split` defaults to `false`**, because splitting multiplies compute cost.
- **`vm_cutover` and `db_cutover` have no defaults at all.** They select entirely different
  runbooks, not different numbers.
- **`global.user_geography` defaults to `single-region`** when Q-A1 maps one Azure region
  (PROPOSED, correctable). Design reads it for CloudFront / Route 53 (`networking.md` §2.3)
  and Q-D1's Catastrophic branch uses it before writing `data.availability: "multi-region"`.
- **`design_constraints.compliance` is always ESSENTIAL.** Canonical encoding:
  `[]` = explicit none (alias `["none"]` accepted from the AI-only path); `["unknown"]` =
  unconfirmed; named frameworks are strings like `"soc2"`. Never a scalar `"none"`. Never
  `null` once the row has been answered. Design, Estimate, and Generate all read this array.

## Status — build step 5 (infra categories)

The shape above is the real contract and Design is written against it. The AI keys land with
the AI route in step 6; the `clusters[]` pattern confirmation fills in when `patterns.md`
lands.
