# Schema — `aws-design.json`

Contract for the artifact the design phase produces. `design-assemble.md` is its single
creator and owns the validation checklist at the bottom.

> **Why this file exists.** It did not, for one build step, and every other artifact had
> a schema. A fresh-context run reverse-engineered the shape from twelve postconditions
> and scattered prose, and invented reasonable-but-different key names — while the
> committed golden tree used a third set. Five separate oracle failures traced to that
> one absence: the ref never required fields the golden asserted, so the oracle was
> testing the golden against itself. A hand-authored golden and a prose-only contract
> drift by construction; this file is the thing they both have to agree with.

## Shape

```jsonc
{
  "phase": "design",
  "timestamp": "<ISO 8601>",
  "source_inventory": "azure-resource-inventory.json",
  "clusters": [], // one per input cluster — see § clusters
  "services": [], // mapped resources — see § services
  "deferred": [], // specialist gates — see § deferred
  "pending_rubric": [], // a named rubric file is not on disk — see § pending_rubric
  "warnings": [], // ALWAYS present, `[]` when clean — see § warnings
  "halt": {} // present ONLY when the phase is failing its gate — see § halt
}
```

Every inventory resource appears in exactly one of `services`, `deferred`,
`pending_rubric`, or `warnings`. That is the accounting invariant, and it is the only
thing that makes a silently dropped resource detectable — a dropped resource still
parses, still satisfies every other assertion, and simply produces no cost line.

## `services[]`

A resource with an AWS target.

```jsonc
{
  "service_id": "<derived slug — see § service_id; unique within the artifact>",
  "azure_id": "<ARM resource ID from the inventory>",
  "azure_type": "Microsoft.Cache/Redis",
  "aws_service": "ElastiCache Redis",
  "aws_config": {}, // target-shaped config; also where a consumed child's contribution lands
  "confidence": "deterministic", // deterministic | measured | inferred | billing_inferred
  "fast_path_row": "Microsoft.Cache/Redis", // REQUIRED when confidence is deterministic
  "rubric_applied": "compute.md", // REQUIRED when pass 2 ran
  "rationale": "<one or two sentences a customer can read>"
}
```

- **`fast_path_row` is mandatory on every `deterministic` entry** and must be a key in
  `knowledge/design/fast-path-services.json` → `direct_mappings`. It is what makes the
  label auditable: without it, "this came from a table" is an unverifiable claim, and an
  improvised target labelled `deterministic` is indistinguishable from a real one.
- **`rationale` is customer-facing.** State why this target, not what the table says.
- A `measured` entry must cite the utilization evidence inside `rationale` or
  `aws_config`.

## `clusters[]`

One entry per cluster in `azure-resource-clusters.json`. Cluster-level fields come
FIRST in the artifact and first in the report, because that is the holistic payoff — a
40-row per-resource table is an appendix.

```jsonc
{
  "cluster_id": "rg-app",
  "pattern_id": "unclassified",
  "pattern_status": "catalog_absent", // recognized | unclassified | catalog_absent
  "target_architecture": null, // null iff pattern_status is not "recognized"
  "rationale": "<why these resources are one workload, and what the target shape is>",
  "constraints_imposed": [] // the candidate-set restriction the pattern applied
}
```

**`pattern_status` exists so that "no pattern could be recognized" has a defined home.**
Three states, and they are not the same fact:

| `pattern_status` | Meaning                                                                                                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `recognized`     | a pattern matched; `pattern_id` names it and `target_architecture` is a real string                                                                                             |
| `unclassified`   | the catalog was consulted and nothing matched. A required fallback, not a failure — but it MUST be flagged in the report so the output does not overclaim architectural insight |
| `catalog_absent` | `design-refs/patterns.md` is not on disk (it lands in build step 4), so no recognition was attempted at all                                                                     |

Without this field, the phase's postcondition demanding `target_architecture` is
unsatisfiable while `patterns.md` is absent, and the honest response — leaving it
undetermined — looks identical to a defect. The dangerous alternative is what an agent
optimising for a green gate does instead: write a plausible architecture string. Nothing
downstream could catch that, which is exactly why the honest state needs to be
expressible.

`target_architecture` MUST be `null` when `pattern_status` is not `recognized`. A
non-null value with `catalog_absent` is a contradiction and must fail validation.

## `deferred[]`

A specialist gate fired. See `design-refs/specialist-gates.md`.

```jsonc
{
  "azure_id": "...",
  "azure_type": "Microsoft.Sql/managedInstances",
  "aws_service": "Deferred — specialist engagement",
  "reason": "<the gate row's reason, verbatim — it is the customer-facing explanation>",
  "recommendation": "Engage your AWS account team; this workload needs a migration assessment."
}
```

**No `confidence` field.** A deferral did not come from a rubric, so labelling it
`inferred` would claim reasoning that did not happen. This is the one entry shape that
carries no confidence value.

A gate is not a failure and not a `halt`: design continues, the rest of the estate maps
normally, and the estimate carries no line item for the deferred workload. Say that in
the report, so a missing cost does not read as a free service.

## `pending_rubric[]`

A resource whose category file, named by `design-refs/index.md`, is **not on disk**. The
halt guard's record. Never a place to put a resource you could have mapped.

```jsonc
{
  "azure_id": "...",
  "azure_type": "Microsoft.Web/serverfarms",
  "ref_file": "references/design-refs/compute.md", // REQUIRED — which rubric is missing
  "candidates": ["Elastic Beanstalk", "Fargate", "EKS"],
  "is_compute_unit": true,
  "sizing_source": {}, // REQUIRED when is_compute_unit — see below
  "sizing_provenance": "table", // REQUIRED whenever aws_config carries a size — see below
  "routing_provenance": "table", // REQUIRED — table | index_md | child_type_rule | namespace_rule | model_category
  "hosted_app_azure_ids": [], // REQUIRED on a Microsoft.Web/serverfarms entry
  "note": "<what a reader needs to know before the rubric lands>"
}
```

**`sizing_source` and `hosted_app_azure_ids` are required, not optional, and they are
required on a `services[]` compute entry too once the rubric exists.** They are the
audit trail for the App Service Plan fan-in: `hosted_app_azure_ids` records WHICH apps
folded into this plan, and `sizing_source` records that capacity came from the plan's
SKU rather than from the app count. Without them, "five apps correctly fanned in to one
plan" and "four apps fanned in and one silently dropped" produce identical artifacts.

Every `azure_id` in `hosted_app_azure_ids` must exist in the inventory.

## `service_id`

**Derived, not invented.** `<aws-service-slug>-<azure-resource-local-name>`:

- `aws-service-slug` — the `aws_service` value lowercased, non-alphanumerics collapsed to a
  single `-`, leading `aws-` / `amazon-` dropped. **Never abbreviate**, because an
  abbreviation is a choice and choices are what made this unreproducible:
  `Elastic Beanstalk` → `elastic-beanstalk` (not `eb`), `RDS PostgreSQL` → `rds-postgresql`,
  `FSx for Windows File Server` → `fsx-for-windows-file-server`,
  `Systems Manager Session Manager` → `systems-manager-session-manager`.
- `azure-resource-local-name` — the source resource's `config.tf_resource_name`, or the last
  segment of `azure_id` when there is no Terraform provenance. Strip any `tf:` prefix.
- Collision → append `-2`, `-3`. Collisions should be rare, because one Azure resource
  produces at most one entry.

**Why a rule and not "any stable slug".** The previous wording was `<stable slug, unique
within the artifact>`, which let two runs of the same estate produce entirely different ids —
capability run 4 produced 8 different ids out of 14, every one of them a valid stable slug.
An identifier nobody can reproduce cannot be referenced from a report, cross-checked between
artifacts, or asserted by a fixture, and its instability is invisible because each run is
internally consistent.

**Nothing may key on `service_id` across artifacts.** Use `azure_id` for that — it is
constructed by a stated rule, it is unique, and it is the same string in every artifact that
mentions the resource. `service_id` is for human reference within one artifact only.

## `routing_provenance`

**REQUIRED on every `services[]` entry.** How this resource's disposition was reached:

| Value             | Means                                                                                                                                                                                                            |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `table`           | An authored row in `fast-path-services.json` — `direct_mappings`, `skip_mappings` or `specialist_gates`                                                                                                          |
| `index_md`        | A Reference row in `design-refs/index.md` routed it to a category rubric                                                                                                                                         |
| `child_type_rule` | Derived: a child type folded into its parent, per `fast-path-services.json` → `child_type_rule`                                                                                                                  |
| `namespace_rule`  | Derived: routed by provider namespace, per `fast-path-services.json` → `namespace_routing`                                                                                                                       |
| `model_category`  | The namespace is not in that list, so the best-fit category was chosen from the rubrics on disk and its six criteria applied. Carries a `routed_by_model_category` warning naming the namespace and the category |

**`confidence: "deterministic"` requires `routing_provenance: "table"`.** No derived route —
`child_type_rule`, `namespace_rule` or `model_category` — can ever earn that tier — it has no `fast_path_row` to name, and the rubric made the
decision. An entry claiming `deterministic` with a derived provenance is the specific
failure this field detects.

The two derived values exist so coverage can grow without an authored row per type, while
staying **visible**: a reviewer can see at a glance which mappings came from curated
judgement and which from a structural rule. Without the field they are indistinguishable
in the artifact, which is how 53 orphans and a confidently-wrong category both hide.

## `sizing_provenance`

**REQUIRED on every `services[]` entry whose `aws_config` carries a size** — an instance
type, instance class, node count, shard count, capacity unit, or volume type. One of:

| Value         | Means                                                                                                                                                             |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `table`       | Looked up in a `knowledge/design/*.json` or `knowledge/estimate/*.json` table. The row exists and its two sides justify each other                                |
| `measured`    | Derived from observed utilization via `knowledge/estimate/rightsizing-thresholds.json`. Requires the evidence cited on the entry, per `design.md`'s postcondition |
| `user_stated` | The customer gave the size in Clarify or a workshop                                                                                                               |
| `model_prior` | **No table row covered it.** The number came from the model's own knowledge                                                                                       |

**`model_prior` is a legal value and must be used honestly.** It exists because the
alternative is what this skill did until 2026-09-07: every size in the committed golden
was a pretrained association, `sizing_source` recorded only the Azure _input_ so the
output looked sourced, and the oracle pinned no sizes, so two runs could disagree on every
number and both stay green. Writing `table` when no row was consulted is the failure this
field is here to prevent — and it is the one failure a reviewer cannot detect from the
artifact alone.

Two corollaries:

- `sizing_source` records the Azure **input** (`{"sku_name": "S1", "worker_count": 2}`).
  `sizing_provenance` records where the **output** came from. They are different claims
  and neither substitutes for the other.
- A `model_prior` entry SHOULD carry a `warnings[]` entry naming the type that has no
  sizing row, so the gap is visible in the report and fixable in one place.

## `warnings[]`

Same entry shape as Discover's (`schema-discover-azure.md` § Warnings: `code`, an
`azure_id` or `identifier`, and a `detail` naming the consequence), with a **separate
closed vocabulary** — Discover's codes say what could not be READ, Design's say what was
DECIDED. The vocabulary is in `phases/design/design-infra.md` § Warning codes.

Optional extra keys: `severity` (`blocker` | `cost_optimization`), `report_note`
(e.g. `cloudwatch_fallback`), `plan_azure_id` (on `app_consumed_by_plan`).

## `halt`

Present **only** when the phase is failing its gate. Absent on a clean design.

```jsonc
"halt": {
  "reason": "unknown_type, missing_rubric_file",   // the kinds present, comma-joined
  "blocking": [
    {
      "kind": "untranslated_terraform_type",   // see the table below
      "identifier": "azurerm_dev_test_lab (local name: sandbox)",
      "why": "<why this blocks rather than warns>",
      "action": "<what the reader does to unblock it>"
    }
  ]
}
```

| `kind`                        | Raised by                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------- |
| `untranslated_terraform_type` | a non-empty `iac_metadata.untranslated_types` — treated as cost-bearing by default    |
| `unmapped_canonical_type`     | a canonical type in no table and no `index.md` row, that failed the cost-bearing test |
| `missing_rubric_file`         | **one entry per distinct missing ref file**, not per affected resource                |

**Every `pending_rubric[]` entry's `ref_file` must have a matching
`missing_rubric_file` entry in `halt.blocking`.** `pending_rubric[]` records which
resources are affected; `halt` records that the phase is not finished. A design carrying
`pending_rubric[]` and no `halt` reads as complete to anything that only looks at
`services[]`, which is most report code.

**Write the artifact even when halting.** Everything determined stays in, and the gate
fails on its own merits. Discarding the work makes the user re-run the phase to learn
one missing table row and hides which resources were already fine — and it makes the
halt untestable by an external asserter.

## Validation Checklist

- [ ] Every inventory resource appears in exactly one of `services`, `deferred`, `pending_rubric`, or `warnings`.
- [ ] Every `services[]` entry has `service_id`, `azure_id`, `azure_type`, `aws_service`, `aws_config`, `confidence`, `rationale`.
- [ ] Every `deterministic` entry has a `fast_path_row` that is a key in `fast-path-services.json` → `direct_mappings`, and an `aws_service` that row allows.
- [ ] No `deferred[]` entry has a `confidence` field; every one has `aws_service: "Deferred — specialist engagement"` and a `reason`.
- [ ] No `Microsoft.Web/sites` resource has an entry in `services[]`, `deferred[]`, or `pending_rubric[]` — it is always folded into its plan.
- [ ] Every `Microsoft.Web/serverfarms` entry has `hosted_app_azure_ids` and `sizing_source`, and every id in the former exists in the inventory.
- [ ] Every cluster has `pattern_status`, and `target_architecture` is `null` unless `pattern_status` is `recognized`.
- [ ] Every `pending_rubric[]` entry has a `ref_file`, and every distinct `ref_file` has a `missing_rubric_file` entry in `halt.blocking`.
- [ ] `warnings[]` is present, and every entry has a `code` from the design vocabulary, a `detail`, and an `azure_id` or `identifier`.
- [ ] `halt` is present iff the phase is failing its gate.
- [ ] Every `services[]` entry has `routing_provenance` from {`table`, `index_md`, `child_type_rule`, `namespace_rule`}, and no entry with a derived provenance claims `confidence: "deterministic"`.
- [ ] Every `services[]` entry whose `aws_config` carries a size has `sizing_provenance` set to one of `table`, `measured`, `user_stated`, `model_prior` — and `table` only when a `knowledge/` row actually covered it.
- [ ] "App Runner" appears nowhere in the artifact.

## Status — build step 3

`services[]`, `pending_rubric[]`, `warnings[]`, and `halt` are exercised by the
`azure-iac-terraform` fixture's Design asserter. `deferred[]` is shape-bound but
untested — the corpus fires no specialist gate. `clusters[]` carries
`pattern_status: "catalog_absent"` until build step 4 lands `patterns.md`.
