---
_fragment: infra
_of_phase: design
_contributes:
  - aws-design.json (services[], clusters[], deferred[], warnings[])
---

# Design — Infrastructure Mapping

> **Fragment unit.** See `design.md` for how it is composed into the phase.

Runs the two-pass mapping engine over the clustered inventory: pass 1 is the
disposition table, pass 2 is the category rubric. It applies the precedence order in
`design.md` and never reorders it.

## What to load

| File                                         | When                                                           |
| -------------------------------------------- | -------------------------------------------------------------- |
| `references/shared/schema-design-aws.md`     | always — the artifact contract, including every REQUIRED field |
| `knowledge/design/fast-path-services.json`   | always — it is pass 1 for every resource                       |
| `references/design-refs/fast-path.md`        | always — the contract for what the table's labels claim        |
| `references/design-refs/specialist-gates.md` | when any resource matches a `specialist_gates` row             |
| `references/design-refs/index.md`            | when any resource matched no row in the table                  |
| the category file `index.md` names           | per category actually present — never speculatively            |
| `preferences.json`                           | always — geography, compliance, availability, compute target   |

## Apply geography and compliance from Clarify

Read these **before** pass 1. They are not mapping-table rows; they constrain which
targets and extra services the rubrics may emit.

**`global.user_geography`** (canonical region question, Q-A1b):

| Value           | Design effect                                                                                                                                                                                                         |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `single-region` | No extra CDN or Route 53 latency/geolocation policy from this row. Map Front Door / CDN only when those Azure resources exist (`networking.md`).                                                                      |
| `multi-region`  | Require CloudFront for public HTTP edges (static assets and API caching) and Route 53 latency-based routing, even when the inventory has no Front Door.                                                               |
| `global`        | Same CloudFront + Route 53 geolocation. **Do not** invent Aurora Global Database from geography alone — that still requires `data.availability == "multi-region"` (Catastrophic + global users, resolved in Clarify). |

If `user_geography` is absent, treat as `single-region` and say so in the rationale
(Clarify default). Do not invent a second AWS region.

**`design_constraints.compliance`:** normalize `[]` and `["none"]` as no frameworks;
`["unknown"]` as unconfirmed (full catalog, report caveat). Named frameworks gate
region and service eligibility the same way Generate's authoring posture does.

## The admission test for Direct Mappings

Stated once, in `fast-path.md` § The admission test. The short form: **is this target
correct regardless of the surrounding architecture?** Architecture-invariant rows are
admissible; everything else is a rubric decision. That is why the table is all
infrastructure primitives with one exception (`managedClusters` → EKS), and why Azure
Functions → Lambda is _not_ a fast-path row: a function inside an otherwise
Fargate-based workload may belong on Fargate, and a durable or long-running function
hits the eliminator anyway.

Note the unit carefully. The rubric row is the **plan**
(`Microsoft.Web/serverfarms`), not the function app — a site never gets its own entry
(see § The App Service Plan cost trap). A hosted site's `kind` narrows the plan's
candidate set to {Lambda, Fargate}; it does not make the site a mapping subject.

## Unknown types: two different unknowns

There are **two** distinct "we have no row for this", they arrive at different phases,
and conflating them is how a cost-bearing resource gets silently dropped.

### 1. Untranslated type (a Discover-level unknown) → always STOP

The Terraform type was absent from `arm-type-canonicalization.md`, so Discover recorded
it in `iac_metadata.untranslated_types` and left it **out of `resources[]` entirely**.
Read that list as a separate input — a resource that is not in `resources[]` cannot be
found by iterating `resources[]`, which is exactly how this case gets missed.

**A non-empty `untranslated_types` STOPs the design, unconditionally.**

The reason it is not run through the cost-bearing test: that test needs a SKU field, a
consumption row, or a provider namespace, and an untranslated resource has **none of the
three** — there is no canonical type, so there is no namespace, and Discover kept no
config. The skill cannot demonstrate the resource is free. Absence of evidence of cost
is not evidence of no cost, and the failure is asymmetric: wrongly stopping costs one
round trip to add a table row, while wrongly skipping understates the estate and the
estimate with nothing to signal it.

### 2. No row anywhere → try the two DERIVED rules before stopping

A type that missed `fast-path-services.json` and has no `index.md` row is not yet an
unknown. Two structural rules resolve most of them, and both are in
`fast-path-services.json` as data:

**2a. `child_type_rule`.** A canonical type with two or more segments after the provider
(`Microsoft.Sql/servers/databases`) is a CHILD of the type formed by dropping its last
segment. If the child has no row of its own and its **parent** resolves to a disposition,
the child is a `config_source` of that parent: emit no target, contribute its attributes to
the parent's `aws_config`, and emit one `skipped_config_source` warning naming what it
contributed.

Twenty-seven of the 33 `config_source` rows in `skip_mappings` are child types, and none of
the 19 `noise` rows are. The disposition was always derivable from the type path; only the
description of what it contributes needed authoring.

**2b. `namespace_routing`.** The provider namespace (`Microsoft.Network`) is a structural,
authoritative segment of an ARM type string. 54 namespace rules route to a category rubric,
a skip, or a gate — covering a provider surface past a thousand types with rules rather
than rows.

> **Why this exists.** `gcp-to-aws` routes an unknown type to a category by
> substring-matching its NAME — `"log" → monitoring`, which also matches
> `google_dia` **`log`** `flow_agent`. Azure has a better signal for free. Before these
> rules, azure went from "no row" straight to the cost-bearing STOP, which made it
> **stricter than gcp on less than half the per-type coverage**: a type we could name, in a
> namespace we understood, still halted the design.

Three constraints on both rules:

1. **An explicit row always wins.** These are consulted only after every table and
   `index.md` have missed.
2. **Record `routing_provenance`** — `table`, `index_md`, `child_type_rule`, or
   `namespace_rule` — on the `services[]` entry. A derived disposition must be visible in
   review, not indistinguishable from a curated one.
3. **A derived route can never produce `confidence: deterministic`.** That tier requires a
   `direct_mappings` row and a `fast_path_row` naming it. Namespace routing yields
   `inferred` at best, because the rubric decided.

If the rule routes to a rubric file that is not on disk, the missing-rubric HALT applies
exactly as it does for an `index.md` row. Deriving the category does not license
improvising the answer.

### 3. Still no disposition → the unknown-type split

The type IS canonical and present in `resources[]`, matched no row, and **neither derived
rule resolved it** — so its namespace is one this skill does not recognise. Halting on
every one of these would once have stopped Design at roughly the third resource of a real
inventory; with the derived rules in front, it is now a genuinely rare case. So:

The type IS canonical and present in `resources[]`, but matched no row in
`fast-path-services.json` and has no row in `index.md`. Halting on every one of these
would stop Azure Design at roughly the third resource of a real inventory — tenants are
dense with diagnostic settings, private endpoints, role assignments, action groups, and
deployment records. So:

- **Benign** — no SKU/tier/capacity property in `config`, **and** no non-zero cost in
  consumption data → record in `warnings[]` and continue.
- **Cost-bearing** — has a SKU/tier/capacity property, **or** appears in RDfA/billing
  consumption with non-zero cost → **choose the best-fit category** from the rubrics on
  disk, load it, and apply its six criteria like any other pass-2 resource. Record
  `routing_provenance: "model_category"`, emit a `routed_by_model_category` warning naming
  the namespace and the category, and take `confidence: inferred`. This is not a STOP.

**Only STOP when you genuinely cannot say what the service does.** Then the resource is
unplaceable rather than unmapped: `halt.kind` is `unmapped_canonical_type` and the message
asks for the type to be filed. That should be rare.

> **Why this is not a STOP any more.** `gcp-to-aws` — whose workflow serves customers today
> — lists 28 `google_*` types, has no namespace gate and no missing-rubric halt, and routes
> an unknown type to one of nine categories where the rubric answers. It handles every case
> not because its mapping knowledge is complete but because **a rubric is always reachable.**
> Azure had double gcp's per-type coverage and stopped more often, which is the wrong trade.
>
> The line that matters is not table-versus-model. It is **facts versus opinions**: fall back
> to the model for facts about Azure (what a service is, what a SKU's vCPU count is) and
> never for this project's positions (Elastic Beanstalk over Fargate for PaaS posture,
> `x86_64` over Graviton, single-AZ plus a finding rather than inferring Aurora from silence).
> A model-chosen _category_ is a fact-shaped judgement; the rubric it lands in still supplies
> the opinion.

The consumption test is mechanical whenever RDfA or billing ran, so a resource that
costs money is never silently skipped. The namespace test is the fallback for an
IaC-only run, where there is no consumption data to consult.

### What a STOP writes

A STOP is not a crash. **Write `aws-design.json` with everything determined so far**,
plus a `halt` object, and then let the phase emit `GATE_FAIL`:

The `halt` shape is in `schema-design-aws.md` § `halt`. Three `kind` values exist —
`untranslated_terraform_type`, `unmapped_canonical_type`, and `missing_rubric_file` —
and **every one of them that applies must be listed.** A halt that names only the first
blocker sends the reader back for a second round trip, and a `pending_rubric[]` with no
matching `missing_rubric_file` entry reads as complete to anything that only inspects
`services[]`, which is most report code.

Discarding the work would make the user re-run everything to learn one missing row, and
it would hide _which_ resources were already fine. Writing the partial artifact is also
what makes the STOP testable by an external asserter. This is **not** the same as
patching an artifact to force a gate to pass — the gate still fails, loudly, and the
`halt` object is the reason.

## Missing rubric file → `pending_rubric[]`, not a guess

`index.md` names a category file per type. **If that file is not on disk, HALT** — same
guard, same reasoning, as `discover-iac.md` Step 2. Record each affected resource in
`pending_rubric[]` per `schema-design-aws.md`, **and add one `missing_rubric_file` entry
to `halt.blocking` per distinct missing file** (not per resource), then emit `GATE_FAIL`.

`index.md`'s right-hand column gives a rubric row an unordered **candidate set**, not an
answer. If you can pick a target from that column alone, you are improvising — the column
exists to tell you which rubric to open.

Do **not** map it from your own knowledge of Azure and AWS. "No rubric is needed" and
"the rubric has not been written yet" are otherwise indistinguishable, and improvising
past the second produces a mapping that satisfies every shape assertion, carries a
`confidence` label it did not earn, and differs between two runs of the same estate.

`pending_rubric[]` is **permanent, not scaffolding.** It empties once step 5 lands, but
it stays in the contract: adding an `index.md` row without its file is a mistake that can
recur, and this is where it surfaces. `design.md`'s accounting postcondition therefore
lists it as a valid way for a resource to be accounted for — a correctly halted design
should fail on the `halt`, not on bookkeeping.

## Warning codes

Design writes its own `warnings[]` on `aws-design.json`, with the same entry shape as
Discover's (`schema-discover-azure.md` § Warnings: `code`, `azure_id` or `identifier`,
`detail`) and a **separate closed vocabulary**. Discover's codes describe what could not
be read; these describe what was decided.

| `code`                               | Emitted when                                                                                                                                                                                                                                    |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `skipped_no_aws_equivalent`          | a `skip_mappings` row with `kind: noise`                                                                                                                                                                                                        |
| `skipped_config_source`              | a `skip_mappings` row with `kind: config_source` — the `detail` MUST name what it contributed                                                                                                                                                   |
| `skipped_observability`              | an `Microsoft.Insights/*` or Log Analytics resource; carries `report_note: "cloudwatch_fallback"`                                                                                                                                               |
| `app_consumed_by_plan`               | one per `Microsoft.Web/sites` folded into its plan, with `plan_azure_id`                                                                                                                                                                        |
| `idle_app_service_plan`              | a plan with zero apps; `severity: "cost_optimization"`                                                                                                                                                                                          |
| `benign_unknown_type`                | an unmapped canonical type that cleared the cost-bearing test                                                                                                                                                                                   |
| `routed_by_model_category`           | the namespace was not in `namespace_routing`, so the category was chosen by judgement. `detail` MUST name the namespace AND the category chosen, so the decision is reviewable rather than invisible                                            |
| `type_derived_uncorroborated`        | Discover derived the ARM type but no second artefact declared its namespace. Carried through from the inventory so it appears in the design's own warnings too                                                                                  |
| `routed_by_namespace_rule`           | a type resolved by `namespace_routing` rather than an authored row. `detail` MUST name the namespace and the rubric it routed to, so the derived decision is auditable                                                                          |
| `routed_by_child_type_rule`          | a child type folded into its parent by `child_type_rule`. `detail` MUST name the parent and what was contributed                                                                                                                                |
| `availability_downgrade_from_source` | the source database is zone-redundant / HA but the target is single-AZ, because no availability answer was recorded. `severity: "review"` — the customer silently loses HA they were paying for unless this is said out loud (`database.md` §1) |
| `cdn_required_by_geography`          | `user_geography` is `multi-region` or `global` and the design added CloudFront that the Azure inventory did not already imply. `detail` MUST name the geography value                                                                           |
| `<hard_blocker key>`                 | a `hard_blockers` row, e.g. `azure_edition_windows_server`; `severity: "blocker"`                                                                                                                                                               |

A cost-bearing unknown and an untranslated type produce a `halt` entry, **not** a
warning. That distinction is the whole point of the split policy: a warning means the
design continued, and these two mean it did not.

## Private endpoints are config sources, not targets

Skipped as standalone output, but their `privateLinkServiceId` /
`private_connection_resource_id` is read to build the app-to-data edge. Each consumed
endpoint gets one `warnings[]` entry naming the edge it produced. Every
`skip_mappings` row whose `kind` is `config_source` behaves this way: read the
contribution first, then skip, and name the contribution in the warning.

## The App Service Plan cost trap

`Microsoft.Web/serverfarms` carries the SKU and instance count — that is the compute
being paid for. `Microsoft.Web/sites` apps run on the plan and **share its capacity**.
Five web apps on one S1 plan cost one S1. Mapping each app to its own Elastic Beanstalk
environment multiplies the estimate by five.

This is the inverse of gcp's App Engine fan-out: GCP fans one parent out to N service
environments; Azure fans N apps **in** to one compute target.

1. Map the **plan** to the compute target, sized from the plan's SKU and instance
   count — never from the app count.
2. Apps become deployments onto that target. Each contributes runtime and app settings
   to `aws_config`; none emits its own compute line item.
3. Emit one mapping per plan, keyed by the plan's ARM ID, with one
   `app_consumed_by_plan` warning per app consumed. The plan's entry MUST carry
   `hosted_app_azure_ids` (every app that folded in) and `sizing_source` (the SKU and
   instance count capacity came from) — both are required by
   `schema-design-aws.md`, in `services[]` and in `pending_rubric[]` alike. Without
   them, "five apps correctly fanned in" and "four fanned in and one silently dropped"
   produce identical artifacts, and the rule cannot be audited at all.
4. Split only on a stated isolation requirement from `preferences.json`, never by
   default — and when splitting, say plainly in the rationale that compute cost rises.
5. A plan with **zero** apps is idle capacity: map it, and flag it as a
   cost-optimization finding.

**Find the apps by the `hosted_on` edge**, which Discover writes from each site's
`service_plan_id` / `serverFarmId`. Do not group by resource group or by name prefix:
the edge is the only reliable link, and it is present for every discovery source.

**A `Microsoft.Web/sites` resource never gets an entry of its own** — not in
`services[]`, not in `deferred[]`, not in `pending_rubric[]`. This includes function
apps: a Y1 or FC1 consumption plan is still the compute unit, and the hosted sites'
`kind` is an INPUT to the plan's target choice rather than a reason to map the site
separately. On a consumption plan the plan carries no worker capacity, so `sizing_source`
records the plan's SKU plus the fact that capacity is per-execution — it never becomes a
reason to size the functions individually.

The fan-in rule is **structural and independent of the target**, so it holds even while
the compute rubric is still pending: the count of compute units is one per plan whether
that plan resolves to Elastic Beanstalk, Fargate, or EKS. A plan sitting in
`pending_rubric[]` still accounts for its apps.

## Status — build step 5 (both passes, partial)

Pass 1 is complete: the disposition table, its contract, the routing index, the gate
table, the split unknown-type policy, and the fan-in rule. Pass 2 covers **compute and
database** (`design-refs/compute.md`, `design-refs/database.md`); the other eight category
files are still to land, and a resource routed to one of them halts per § Missing rubric
file rather than being mapped from model priors.

The behaviours above are externally asserted against a committed fixture: the App Service
Plan fan-in count, the unresolvable-type STOP, the three protocol/API-conditioned fast-path
rows, the pass-2 outcomes, the `x86_64` architecture default, and the source-HA downgrade
finding.

**Everything an asserter checks is stated in this file or another skill file — that is the
contract, not a courtesy.** Do not go looking for an asserter to resolve an ambiguity: if a
rule is only discoverable by reading test code, the rule is missing and the skill file is
the bug. (Reading an asserter also invalidates a capability run, which is how this skill is
tested.)
