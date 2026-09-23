# Fast-Path: pass-1 dispositions

The lookup DATA lives in `knowledge/design/fast-path-services.json`, loaded via the
design phase's `_knowledge`. This file is the CONTRACT: what the table means, what
may go in it, how it is applied, and what the labels are allowed to claim.

Do not restate rows from the JSON here. One canonical copy — see SKILL.md
§ Context Loading Rules, "No duplication".

## The admission test

A row belongs in **Direct Mappings** when, and only when:

> **Is this target correct regardless of the surrounding architecture?**

This is a sharper test than "is it 1:1?", and it follows directly from the invariant
in `design.md`: a pattern may narrow rubric candidates and may never change a
`deterministic` mapping's target. If a pattern could ever want a different target for
a row, the row is not architecture-invariant and does not belong in the table.

Three consequences worth stating, because each one looks like an exception and is not:

1. **A mechanical condition on the resource's OWN config is still invariant.** The
   share row reads `enabled_protocol`; the Event Hubs row reads `kafka_enabled`; the
   Cosmos row reads the API. Each reads a property of the resource itself, not of its
   neighbours, so the target is still fixed once the resource is known. This is the
   same shape as gcp's `google_sql_database_instance` (SQL Server) row, which is
   conditioned on the engine. Owner decisions 11.4 and 11.5 state that protocol is the
   _whole_ rubric for those two, which means there is no rubric left — only a lookup.
2. **Additive company is not a target change.** A static-website storage account still
   maps to S3 even though the pattern layer adds CloudFront; a disk still maps to EBS
   even though an ASG appears around it. The row's `aws_service` is unchanged, so the
   label holds. Only a _substituted_ service would break the invariant.
3. **Post-selection sizing does not compromise an `Always` condition.** gp3-versus-io2
   by IOPS, and instance size from measured utilization, happen after the service is
   chosen. The row picks the service; sizing never revisits it.

**No compute in the table**, with one exception. `Microsoft.Web/serverfarms`,
`Microsoft.Compute/virtualMachines`, and `Microsoft.Web/sites` (`kind=functionapp`)
are all rubric decisions — a function inside an otherwise Fargate-based workload may
belong on Fargate, and a durable or long-running function hits an eliminator anyway.
`Microsoft.ContainerService/managedClusters` → EKS is the exception because a team
already running Kubernetes does not stop running Kubernetes; the target is invariant
in a way the others are not.

### Rows added beyond the plan's original ten, and why

The plan's §7a.3 fixed a 10-row table before the canonical child-type vocabulary
existed. Four rows are additions of necessity rather than scope:

| Added row                                                                             | Why it is not optional                                                                                                                                                                                                           |
| ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Microsoft.Network/virtualNetworks/subnets`                                           | Canonicalization emits subnets as their own child-typed resources. Without a row, every subnet reaches the unknown-type policy, matches "sits in a network provider namespace", and **STOPs the design** — on every real estate. |
| `.../blobServices/containers`, `.../queueServices/queues`, `.../tableServices/tables` | Same reason, and each has an unambiguous target (S3, SQS, DynamoDB). Leaving them out would STOP on any account that declares its containers explicitly.                                                                         |

### The storage-account row and owner decision 11.5

Decision 11.5 was recorded as disturbing the `Microsoft.Storage/storageAccounts → S3
Always` row. It does not, and the reason is worth writing down so it is not
re-litigated: **canonicalization already makes a file share its own resource.**
`azurerm_storage_share` translates to
`Microsoft.Storage/storageAccounts/fileServices/shares` and appears as a separate
`resources[]` entry, so a share is never inside the account's mapping unit and cannot
pull the account's target anywhere.

So the account row keeps `Always → S3` for its blob surface, the share is its own
protocol-conditioned row, and the only condition the account row needs is the case
where the account has no blob surface at all (`account_kind: FileStorage`). Children
never inherit the parent's target.

## Confidence vocabulary

Four tiers. Use them **only** as defined here — they describe _how the mapping was
chosen_, never how obvious the answer feels.

| JSON `confidence`  | Means                                                                                                                                         | Say this to users                   |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| `deterministic`    | The canonical ARM type matched a **Direct Mappings** row, the row's condition held, and the target came from that row. **No rubric was run.** | **Standard pairing**                |
| `measured`         | A rubric outcome backed by _observed utilization_, not declared config — RDfA's rollup or `az monitor metrics list`. Must cite the evidence.  | **Measured from your actual usage** |
| `inferred`         | A rubric outcome from declared configuration only.                                                                                            | **Tailored to your setup**          |
| `billing_inferred` | The billing-only design path — spend line items without infrastructure detail.                                                                | **Estimated from billing only**     |

`measured` is named after the evidence rather than the tool (it was `rdfa_inferred` in
an earlier draft) precisely so the live `az` path can earn it when it supplies the same
metrics.

**Two labels that are not confidence values.** A specialist gate writes
`Deferred — specialist engagement` into `deferred[]` and carries **no** confidence
field — it did not come from a rubric, and writing `inferred` on a deferral would claim
reasoning that did not happen. A Skip Mapping produces no entry at all, only a
`warnings[]` record.

**Canonical reference:** this section. Other phase files point here rather than
restating it.

**The common confusion:** `design-refs/index.md` lists a _typical AWS target_ per ARM
type. That is not the same as `deterministic`. Confidence is `deterministic` only when
the type appears in `fast-path-services.json` → `direct_mappings` and its condition
held; everything else routed through `index.md` is `inferred` (or `measured` when
utilization backed it).

## Applying it

Per resource, in this order. Stop at the first match.

1. **`skip_mappings`** → no target. Write a `warnings[]` entry with the reason. If the
   row's `kind` is `config_source`, read its contribution FIRST and name what it
   contributed in the warning. Never route a skip through the rubric, and never
   through the unknown-type STOP.
2. **`specialist_gates`** → a `deferred[]` entry with `aws_service:
   "Deferred — specialist engagement"` and the row's reason. Check conditional gates
   (the `#sql_on_vm` form) against config, not just the type.
3. **Eliminators** — hard technical blockers, which live in the category rubric file,
   not here. Lambda's 15-minute ceiling is physics, not a preference.
4. **`direct_mappings`** → evaluate `condition`; if it fails, try `alternatives[]` in
   order; if one holds, assign that `aws_service` with `confidence: deterministic`.
   If a row carries `route_to_rubric` and its condition holds, fall through to step 5
   instead. **Run no rubric for a matched row.**
5. **`index.md`** → category rubric file → pattern constraint → six criteria.
6. **No row anywhere** → the unknown-type policy in
   `phases/design/design-infra.md`.

Independently of the above, check every mapped resource against `hard_blockers`. A
blocker does not change the target; it adds a `warnings[]` entry with
`severity: "blocker"`. It is a statement, not a question — presenting it as a choice
would imply one of the answers works.

## Preferred AWS Target Services

Applied after selection, and only to rubric outcomes. **Never** to a `deterministic`
row: substituting a preferred target over a fast-path row is the invariant violation
this whole file exists to prevent.

| Workload category                     | Preferred target                                                           | Rationale                                                                      |
| ------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| PaaS / managed platform (App Service) | **Elastic Beanstalk**, unless `preferences.json` selects containers or EKS | Preserves the managed-platform model the customer already pays for             |
| Containerized workloads               | Fargate (default), Lambda (event-driven), EKS (Kubernetes already in use)  | Deeper VPC / ALB / IAM / scaling integration than lighter-weight alternatives  |
| Third-party auth in use               | Keep the existing provider                                                 | A startup on Entra External ID, Auth0, or Clerk should not be moved to Cognito |

**AWS App Runner is not a candidate anywhere**, at any step, including as a
"forward-look" — it stopped accepting new customers in April 2026. ECS Express Mode
may be mentioned only as a forward-look on the Fargate override path. A `_postcondition`
on the design phase asserts App Runner appears nowhere in `aws-design.json`; that
assert has no mechanical teeth, so the real enforcement is here.
