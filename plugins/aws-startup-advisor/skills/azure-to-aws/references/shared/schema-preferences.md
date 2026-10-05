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
  "metadata": {
    "clarify_mode": "wizard", // "fast_path" | "wizard" — which Clarify flow produced this file
    "fast_path_eligible": false, // copied from azure-resource-inventory.json metadata.clarify_fast_path.eligible
    "questions_defaulted": [], // dotted row keys that took their documented default without being asked, e.g. "design_constraints.compute_target"; array rows use index notation — "app_service_plans[0].isolation_split", "clusters[1].pattern_id"
    "deferred_to_generate": ["data.db_cutover"] // execution-only rows carrying a default here and asked for real at the Decision gate's [C] (estimate-assemble.md § Step 3b); Generate must not run while any of these is still unconfirmed. DISJOINT from questions_defaulted — a row is in exactly one list
  },
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
    "db_cutover": {
      "disposition": "PROPOSED",
      "value": "dump_restore",
      "default": "dump_restore",
      "deferred_to_generate": true, // asked for real at estimate-assemble.md § Step 3b when the user chooses [C] Generate; Step 3b sets it to false
      "default_basis": "largest relational DB 64 GiB <= 100 GiB",
      "largest_relational_db_gib": 64, // what Discover measured; null when no relational server carried storage_mb
      "size_coverage": "complete" // "complete" | "partial" | "unknown" — whether every relational server had a measured size
    },
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
| `metadata`                                                   | the assembler (`clarify-assemble.md` § Assembly rule 0)                          |
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

**Correction provenance.** A PROPOSED row the user later corrects — directly at the Decision
gate's assumptions block (`estimate-assemble.md` § Step 2) or through the workshop sidebar
(`workshop-refresh.md` § 3) — keeps `disposition: PROPOSED`, takes the user's `value`, gains
`"source": "user_corrected"`, and its key **leaves `metadata.questions_defaulted[]`**. Both
routes write the same three things, so the assumptions block never re-lists an explicit
choice as an assumption and a scenario snapshot carries the corrected provenance. An entry
in `questions_defaulted[]` therefore always resolves to a PROPOSED row whose `value` equals
its `default` and which carries no `source`. The one exception is a row carrying
`deferred_to_generate: true`: correcting it at the Decision gate is its confirmation, so it
takes the Step 3b write (`"source": "user_confirmed_at_generate"`, `deferred_to_generate:
false`, key removed from both `metadata` lists — see the `db_cutover` bullet below) rather
than `user_corrected`.

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
- **`vm_cutover` has no default at all** (ESSENTIAL): MGN versus rebuild selects an entirely
  different runbook, and no inventory fact makes one of them defensible.
- **`db_cutover` has a size-derived default and is deferred, not asked, in Clarify:**
  `dump_restore` when the largest **measured** relational database is ≤ 100 GiB, `dms`
  above that. When no relational server carries a measured size (live enrichment skipped,
  or `storage_mb` unset in Terraform) the default is still `dump_restore` — the runbook with
  no AWS charge, so an unknown size never invents cost — and the row records the
  uncertainty: `largest_relational_db_gib: null`, `size_coverage: "unknown"`, and a
  `default_basis` that says the size was not measured. When only some servers are measured
  the rule applies to the measured maximum with `size_coverage: "partial"` and the basis
  names the unmeasured server(s). A size is never invented. The row is recorded PROPOSED
  with `deferred_to_generate: true`, `default_basis`, `largest_relational_db_gib`, and
  `size_coverage`, and is asked for real at `estimate-assemble.md` § Step 3b when the user
  chooses [C] Generate — the two answers also select different runbooks, which is exactly
  why the question is asked where the runbook is written rather than before the user has a
  number. Step 3b carries the uncertainty into its prompt and asks for the size when
  `size_coverage` is not `"complete"`. **After Step 3b** (or a correction of the row from
  the Step 2 assumptions block, which applies the same write) the row carries the confirmed
  `value`, `"source": "user_confirmed_at_generate"`, `deferred_to_generate: false`
  (explicit, not deleted), and its key is removed from **both** `metadata` lists;
  `default`, `default_basis`, `largest_relational_db_gib`, and `size_coverage` stay for the
  audit trail.
- **`global.user_geography` defaults to `single-region`** when Q-A1 maps one Azure region
  (PROPOSED, correctable). Design reads it for CloudFront / Route 53 (`networking.md` §2.3)
  and Q-D1's Catastrophic branch uses it before writing `data.availability: "multi-region"`.
- **`design_constraints.compliance` is always ESSENTIAL.** Canonical encoding:
  `[]` = explicit none (alias `["none"]` accepted from the AI-only path); `["unknown"]` =
  unconfirmed; named frameworks are strings like `"soc2"`. Never a scalar `"none"`. Never
  `null` once the row has been answered. Design, Estimate, and Generate all read this array.

## Status — build step 5 (infra categories)

The shape above is the real contract and Design is written against it. The AI route
is implemented in `clarify-ai.md` and `design-ai.md`; this schema does not yet list
those AI keys. `clusters[]` pattern confirmation waits on `patterns.md`, which is
not on disk.
