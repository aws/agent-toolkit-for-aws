---
_fragment: infra
_of_phase: estimate
_contributes:
  - estimation-infra.json
---

# Estimate — Infrastructure Cost Engine

> **Fragment unit.** See `estimate.md` for how it is composed into the phase.
> Prices every service in `aws-design.json`, derives the Azure baseline it is
> compared against, and produces **two** AWS totals. The artifact write, the
> decision gate, and the phase-status update belong to `estimate-assemble.md`.

**Execute ALL parts in order. Do not skip or optimize.**

---

## Step 0: Pricing mode

Execute `references/vendored/estimate/pricing-mode.md` as this step: staleness
check, the region check, the **rate-row** check, the
pricing-mode display, and the per-rate-row hierarchy including `partial`,
`estimated` and `unavailable`. Do not restate or fork that logic here.

Two of its steps fire on nearly every Azure run, so expect them:

- **Region.** The cache is `us-east-1`. Azure source regions map to AWS regions
  through `knowledge/design/azure-region-map.json`, and a European Azure region
  maps to a European AWS region — so the design's `target_region` differs from
  the cache region on most estates.
- **Rate rows.** The `knowledge/design/*-sizing.json` tables emit
  current-generation types chosen to fit the Azure SKU. They were authored
  against Azure SKUs rather than against the rate card, so a design can name a
  type the rate card has no row for. Resolve every rate key **before** computing
  anything, so the holes are known up front instead of discovered per line.

## Step 1: Prerequisites

The entry gate (design completed, inputs present and valid, non-empty
`services[]`) is enforced by this phase's `_preconditions` per `INTERPRETER.md`
§ Gate protocol; it has already passed. Then read:

1. `$MIGRATION_DIR/aws-design.json` — `services[]`, `deferred[]`, `warnings[]`,
   `target_region`, `clusters[]`.
2. `$MIGRATION_DIR/preferences.json` — `baseline`, `design_constraints`, `data`,
   and `licensing` (whose `_fired` flag decides Part 3's delta line).
3. `$MIGRATION_DIR/azure-resource-inventory.json` — the source SKUs the 1:1 lift
   is priced from, plus `iac_metadata`.

---

## Part 1: The Azure baseline

The comparison is the point of this phase, so the baseline's **quality** matters
as much as its value. Use the best available source; first match wins.

| Rung | Source                                                                    | `current_costs.source`     | Reachable today?                             |
| ---- | ------------------------------------------------------------------------- | -------------------------- | -------------------------------------------- |
| 1    | An Azure Cost Management export the customer supplied                     | `"cost_management_export"` | **No** — needs the billing source (deferred) |
| 2    | Consumption data from an RDfA report                                      | `"consumption_data"`       | **No** — needs RDfA (deferred)               |
| 3    | `preferences.baseline.azure_monthly_spend`, when the user stated a figure | `"user_stated"`            | **Yes**                                      |
| 4    | Derived from discovered SKUs against an Azure rate card                   | `"derived_from_skus"`      | **No** — this skill ships no Azure rate card |
| 5    | No baseline                                                               | `"unavailable"`            | —                                            |

**Say plainly which rungs are reachable.** On a Terraform-only estate — every
estate today — rungs 1, 2 and 4 cannot fire: the first two need a discovery
source that is not built, and rung 4 needs Azure rates this skill does not ship.
So the baseline is the user's stated figure, or nothing. Do not report rung 4 as
attempted; there is nothing to attempt it against.

Record the rung on the artifact, and never present a derived figure as an
invoice:

```json
"current_costs": {
  "azure_monthly": "<figure or null>",
  "source": "<one of the rung values above>",
  "accuracy": "<'as stated by the customer' | 'invoice data' | 'unavailable'>",
  "baseline_note": "<REQUIRED for every source except cost_management_export>",
  "currency": "<preferences.baseline.azure_monthly_spend.currency, default USD>"
}
```

For `user_stated`, `baseline_note` is: "This is the figure you gave us, not an
invoice we read. It may include Azure charges from outside this estate (other
subscriptions, support plans, marketplace items) or exclude discounts you hold,
so treat the comparison as directional."

### The reservation `$0` trap

A reserved VM, or capacity under a savings plan, reports **`$0`** in consumption
data. It is not free — it was pre-paid, and the money left the customer's account
earlier. Pricing the baseline from the literal figure understates current Azure
spend, which makes AWS look worse than it is and can invert the recommendation.

So: **a `$0` consumption figure against a resource that exists means RESERVED,
never free.** Price that resource at its pay-as-you-go rate as the baseline
stand-in, and record the substitution:

```json
"reservation_substitutions": [
  {
    "azure_id": "<the resource>",
    "reported_consumption": 0,
    "substituted_basis": "<the rate used, and where it came from>",
    "reason": "A $0 consumption figure on an existing resource indicates a reservation or a savings plan, not zero cost."
  }
]
```

**This rule is unreachable today and must not be presented as exercised.** A `$0`
consumption figure only appears in Cost Management or RDfA data — rungs 1 and 2,
both deferred. A `user_stated` baseline has no per-resource figures at all, so
`reservation_substitutions` is an empty array: the rule is a contract for when
the billing source lands, not something this run tested. Write the empty array
rather than omitting the key, so its emptiness is visible to a reader.

### Metrics lookback affects confidence, not just precision

When a metrics window does exist, read its actual length from the report metadata
rather than assuming 31 days. Below `confidence_rules.min_window_days` in
`knowledge/estimate/rightsizing-thresholds.json`, hold right-sizing confidence at
`inferred` and say why: a P95 over a short window can sit entirely inside a quiet
period, and a workload sized for a trough it will leave is worse than one sized
from its SKU.

---

## Part 2: Price the design TWICE

**Dual output is the shape of this phase, not an option a user asks for.** Both
totals are always produced.

| Total                                           | What it prices                                                         | Why it exists                                                                                    |
| ----------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| **1:1 lift** (`projected_costs.lift`)           | Every mapped service at the capacity the Azure resource runs **today** | It is what a naive migration costs, and what the customer assumes if nobody shows them otherwise |
| **Right-sized** (`projected_costs.right_sized`) | The design as recommended                                              | It is the recommendation, and the delta is the visible evidence of the work                      |

Reporting only the lift overstates the bill. Reporting only the right-sized
figure hides the work that produced the saving and leaves the customer unable to
check it against their own expectations. Report both, always, plus
`cost_comparison` stating the delta between them.

### 2A: The 1:1 lift

For each `services[]` entry, price the AWS service at the capacity implied by the
**source** resource — from the inventory entry's `config`, not from `aws_config`:

- A source VM's SKU gives its like-for-like AWS instance via
  `knowledge/design/vm-ec2-sizing.json`. The row's own vCPU/memory columns for
  both sides are what make "like-for-like" checkable rather than asserted.
- A source App Service Plan's SKU and worker count give the EB instance size and
  count via `knowledge/design/appservice-eb-sizing.json`.
- A source Flexible Server SKU gives the RDS class via
  `knowledge/design/flexible-server-rds-sizing.json`; its `storage_mb` gives
  allocated storage.
- Where the design **dropped or shrank** a resource, the lift keeps it at full
  size. That is the entire point of the lift.

### 2B: The right-sized target

Price `aws_config` as the design states it. Right-sizing arrives from two
distinct places, and conflating them is the mistake to avoid:

| Kind                     | Evidence                                                                                                                        | Needs metrics? |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| **Utilization-based**    | Observed P95 against the bands in `knowledge/estimate/rightsizing-thresholds.json`                                              | **Yes**        |
| **Declared-waste-based** | What the IaC itself declares: a plan with zero apps, an `idle` flag, an unattached disk, a worker count above what any app uses | **No**         |

Utilization-based right-sizing is unreachable without a metrics source, and
`rightsizing-thresholds.json` `_precondition` forbids applying its bands to a
declared SKU — a SKU is what was bought, not what is used. Declared-waste
right-sizing is reachable from Terraform alone.

**So on a Terraform-only estate the delta comes entirely from declared waste, and
it can legitimately be `$0`.** When it is, say so and say why in the delta line
itself: "No utilization data was discovered, so no size was reduced on measured
evidence; this delta reflects declared waste only." A `$0` delta presented
without that sentence reads as a broken calculation — and a reader who assumes
right-sizing was attempted and found nothing has been actively misled.

Right-sizing never revisits the **service choice**. The rubric's six criteria
picked the service; this fragment only picks a size within it. If no size in the
chosen service fits, that is a finding for the report, not a reason to re-run the
rubric.

### Per-service formulas

Rates come from the named keys in
`references/vendored/pricing/aws-infra-pricing.json`. Do not restate a rate here.
`hours_per_month` is `_meta.hours_per_month` (730).

| AWS service                                                     | Formula                                                                                                                                                                                                                                                                                                                                                                                                          | Key inputs from `aws_config`                                                          |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| **Elastic Beanstalk**                                           | `ec2.instances[instance_type]` × 730 × running count + `alb.monthly_fixed` + an LCU estimate (web only) + `ebs.gp3_per_gb_month` × root volume × count. EB's own service fee is `$0`                                                                                                                                                                                                                             | `instance_type`, `instance_count`, `min_instances`, `cpu_architecture`                |
| **EC2**                                                         | `ec2.instances[instance_type]` × 730 × count + root volume via `ebs.gp3_per_gb_month`. **Windows: see the `partial` rule below**                                                                                                                                                                                                                                                                                 | `instance_type`, `instance_count`, `operating_system`, `license_model`, `root_volume` |
| **RDS PostgreSQL**                                              | `rds_postgresql.instances[instance_class]` × 730 + `allocated_storage_gib` × `rds_postgresql.storage_per_gb_month`. That rate is `baked_in` Multi-AZ — do **not** double it for `multi_az`                                                                                                                                                                                                                       | `instance_class`, `allocated_storage_gib`, `multi_az`                                 |
| **ElastiCache Redis**                                           | `elasticache.nodes[node_type]` × 730 × `num_cache_nodes`, ×2 when `multi_az` (`multiplier_x2`)                                                                                                                                                                                                                                                                                                                   | `node_type`, `num_cache_nodes`                                                        |
| **MSK**                                                         | `msk.brokers[broker_instance_type]` × 730 × `number_of_broker_nodes` + storage × `msk.storage_per_gb_month`. `intrinsic` multi-AZ, no multiplier                                                                                                                                                                                                                                                                 | `broker_instance_type`, `number_of_broker_nodes`                                      |
| **EKS**                                                         | `eks.control_plane_monthly` + `eks.node_rates_monthly[type]` × node count. Pods cost `$0` — compute is billed via the nodes. ALB and NAT are their own lines and are not re-added here                                                                                                                                                                                                                           | `node_groups[].instance_types`, `desired_size`                                        |
| **ALB**                                                         | `alb.monthly_fixed` + `alb.per_lcu_hour` × 730 × an LCU estimate                                                                                                                                                                                                                                                                                                                                                 | one per web service with a load balancer                                              |
| **NAT Gateway**                                                 | `nat_gateway.monthly_fixed` + `nat_gateway.per_gb_processed` × GB. **Azure's NAT Gateway is regional and AWS's is zonal**, so one source resource becomes N — price N, not one. When the design is private-subnet (the default posture) and no explicit AZ count is upstream, **N defaults to 2** (the 2-AZ VPC Generate emits); record the assumption. See Part 2C-2 for the estate-wide standing-NAT treatment | subnet / AZ count from the VPC design (default 2)                                     |
| **S3**                                                          | `fast_path_services.s3.storage_per_gb_month` × GB + requests, or `s3.monthly_baseline_est`. **Cross-Region Replication is a NEW line** when the source was GRS or GZRS — Azure bundled that into one SKU and AWS does not                                                                                                                                                                                        | `storage_class`, `source_replication`                                                 |
| **Secrets Manager**                                             | secret count × `fast_path_services.secrets_manager.per_secret_month` + API calls, or `monthly_baseline_est`                                                                                                                                                                                                                                                                                                      | Key Vault secret count from the inventory                                             |
| **Lambda**                                                      | `lambda.per_request` × requests + `lambda.per_gb_second_<arch>_first_6b` × GB-seconds                                                                                                                                                                                                                                                                                                                            | `memory_mb`, `architecture`, invocation volume                                        |
| **CloudWatch**                                                  | Part 2C                                                                                                                                                                                                                                                                                                                                                                                                          | —                                                                                     |
| **VPC, subnets, route tables, Systems Manager Session Manager** | `$0`. Emit the line at zero with a `basis` note rather than omitting it, so the reader can see it was considered rather than forgotten                                                                                                                                                                                                                                                                           | —                                                                                     |

### The breakdown line shape

One entry per designed service, in `projected_costs.breakdown[]`. The field names
are fixed, because both totals and every downstream reader key on them:

```json
{
  "service_id": "<from aws-design.json services[].service_id>",
  "aws_service": "<from the design>",
  "lift_monthly": "<Part 2A figure, or null>",
  "right_sized_monthly": "<Part 2B figure, or null>",
  "pricing_source": "<cached | partial | live | cached_fallback | estimated | unavailable>",
  "basis": "<REQUIRED — the rate keys and arithmetic behind the figure, or why there is none>",
  "components": { "<sub-line>": "<figure or null>" },
  "assumptions": [
    "<any quantity taken from estimate-defaults.json or a rate file's _basis rather than from the estate>"
  ],
  "exclusion_reason": "<no_rate | partial_rate | no_quantity — ABSENT when the line is priced>",
  "excluded_from_total": "<true only alongside an exclusion_reason>",
  "missing_component": "<REQUIRED for partial_rate — names what is unpriced>",
  "is_floor": "<true for a partial_rate line>"
}
```

`basis` is required on **every** line, including the `$0` ones — "a VPC is not
billed" is the answer to a question a reader would otherwise have to assume.
`components` must sum to the line's own figure wherever it is present, or the
breakdown contradicts itself.

**Lambda has rates but no invocation data.** The rates are in the pricing file, so
this is not a missing-rate case: IaC declares no request volume, and a source
consumption plan provisions no worker capacity, so there is no source-side figure
to multiply them by. Emit `monthly: null` with `exclusion_reason: "no_quantity"`
and a stated reason — never a remembered default request count.
`lambda._no_invocation_data_note` says the same thing at the data layer.

### Services with no rate row — do not paper over them

`_absent_services` in the pricing file names the services a design can emit that
have **no** rates there, and none in the `gcp-to-aws` cache either. Today those
are **DocumentDB**, **FSx for Windows File Server**, and the **Windows licence
adder**. Pricing is cache-only, so there is no lookup that can resolve them — for
each:

1. Set that line's `pricing_source` to `"unavailable"` and its
   `exclusion_reason` to `"no_rate"`.
2. **Exclude** it from both totals, with `excluded_from_total: true`, but keep the
   line in the breakdown.
3. Add to `warnings[]`: "Pricing unavailable for `<service_id>`
   (`<aws_service>`) — not in the pricing cache and no formula constant carries
   its rate. This line is excluded from the totals, so both totals are
   **floors**."
4. Add the `service_id` to `pricing_source.services_with_missing_fallback[]`.

**Never substitute a neighbouring rate.** `db.t3.medium` on a DocumentDB line is
not an `rds_postgresql` class: different service, and those rates are baked-in
Multi-AZ, so the wrong table would be wrong twice over. A near-miss rate is
indistinguishable from a correct one in the output, which is what makes it worse
than a hole.

### The Windows line is `partial` — neither silently wrong nor thrown away

When a service carries `license_model: "License Included"` (or the design
otherwise states a Windows or SQL Server target), the `ec2.instances` rate is
**Linux** — `ec2._windows_note` says so — and the file carries no licence adder.
A Windows general-purpose instance costs roughly twice its Linux row.

Do not price it silently at the Linux rate: that understates the estate's most
expensive compute line, in the direction that flatters AWS. Do not mark it
`unavailable` either: the base rate is real, and discarding it loses information
the customer needs. Instead, per `pricing-mode.md` rung 1b:

```json
{
  "service_id": "<id>",
  "monthly": "<the Linux-rate figure>",
  "pricing_source": "partial",
  "exclusion_reason": "partial_rate",
  "excluded_from_total": true,
  "missing_component": "Windows Server licence (License Included)",
  "is_floor": true,
  "note": "Priced at the Linux on-demand rate. Windows Server 'License Included' costs materially more — roughly 2x for a general-purpose size — and no Windows rate or per-vCPU licence adder is in the pricing cache. This line is a FLOOR and is excluded from the decision-grade total."
}
```

and add the `service_id` to `pricing_source.services_by_source.partial[]`.

Note how this meets the architecture choice: the design defaults to `x86_64`
**because** of Windows and .NET prevalence. So the estates where that default is
load-bearing are exactly the estates where this pricing hole bites hardest. Say
that in the report rather than leaving the reader to work it out.

### When the rate exists but describes a different configuration

A distinct failure from a missing rate, and worse, because the arithmetic looks
complete. **`rds_postgresql.instances` rates are Multi-AZ** — that section's
`multi_az_handling` is `baked_in` and its `_note` says the rate already includes
it. There is no single-AZ RDS table anywhere. So a **single-AZ** design priced from
that table is roughly **2× too high**, on what is usually the largest line in the
estate.

Do not silently halve it: a halved Multi-AZ rate is a fabricated rate wearing
arithmetic. Do not exclude the line either — it is the biggest number the customer
needs. Price it from the table that exists, and label the direction of the error:

```json
{
  "rate_configuration_mismatch": {
    "designed": "single-AZ",
    "rate_describes": "Multi-AZ (rds_postgresql.multi_az_handling is baked_in)",
    "direction": "overstates",
    "magnitude": "roughly 2x on this line",
    "why_not_corrected": "No single-AZ RDS rates exist here or in the gcp-to-aws cache, and halving a Multi-AZ rate would invent one."
  },
  "is_ceiling": true
}
```

**This makes the totals wrong in BOTH directions at once, and that must be said
rather than netted off.** Excluded lines push every total down; a Multi-AZ rate on a
single-AZ design pushes the largest line up. A total described as a simple "floor"
while carrying a 2× overstatement on its biggest component is not honest. State
both, and do not offset them — they do not cancel in any knowable amount.

Carry the mismatch into `recommendation.conditions` too. Repricing single-AZ RDS is
one of the highest-value corrections available to this estimate, and it is
completely invisible from the number itself.

### The three reasons a line is excluded, and the one rule that decides

A line leaves the totals for exactly one recorded reason:

| `exclusion_reason` | Meaning                                                                                 | Example on a real estate                                                              |
| ------------------ | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `no_rate`          | The rate row does not exist, here or in the `gcp-to-aws` cache, and no formula constant carries it | DocumentDB, FSx for Windows                                                 |
| `partial_rate`     | The base rate resolved but a required rate COMPONENT did not                            | A Windows instance with no licence adder                                              |
| `no_quantity`      | Every rate resolved, but the design and the IaC supply no quantity to multiply          | Lambda, whose cost is invocation-driven and whose invocation count IaC never declares |

**The rule: price what is quantified, and exclude a line only when its PRIMARY
cost driver is unpriced or unquantified.** A missing minor component does not
remove a line — it is priced on what is known and the omission is named in
`assumptions[]`. MSK is the worked example: brokers are the primary driver and
they are quantified, so the line is priced, while per-broker storage is not sized
by the design and appears as an assumption rather than deleting the line. A
Windows instance goes the other way — its licence is roughly half the line, so
what is left is a floor, not an estimate.

This is a materiality judgement, stated so it can be argued with rather than
discovered. When in doubt, price the line and name the assumption: an
under-stated line the reader can see beats a missing line they cannot.

---

## Part 2C: Observability (CloudWatch)

Azure bundles a Log Analytics allowance, so many customers have never seen a
separate line for it. CloudWatch bills from the first GB. Surface it here so it
is not a surprise after cutover.

Every quantity below comes from
[`knowledge/estimate/estimate-defaults.json`](../../../knowledge/estimate/estimate-defaults.json).
Read them from there; do not supply a remembered figure.

1. **Log volume** — `log_volume_gb_per_service`, keyed by service kind and counted
   per instance, node, broker or environment (not per cluster). Sum across the
   design. This is a **heuristic** and it is the coarsest input in the estimate.
2. **Custom metrics** — `cloudwatch_defaults.custom_metrics_per_service` × service
   count, floored at `custom_metrics_floor`.
3. **Alarms** — `max(alarms_floor, alarms_per_service × service count)`.
4. Cost = `log_gb × cloudwatch.log_ingestion_per_gb`
   - `log_gb × cloudwatch.log_storage_per_gb_month × retention_months`
   - `metrics × cloudwatch.custom_metric_month`
   - `alarms × cloudwatch.standard_alarm_month`,
     with `retention_months` from `cloudwatch_defaults`. Add X-Ray
     (`cloudwatch.xray_per_million_traces`) **only** when tracing is actually
     detected in the source; otherwise it contributes a cost that traces back to no
     evidence.

Emit as a **single** breakdown line, `service_id: "observability-cloudwatch"`,
carrying `volume_source: "heuristic"`, `band_percent: 35`, and the resulting
`low` and `high` alongside its `right_sized_monthly`, with `components` broken out
as `log_ingestion`, `log_storage`, `custom_metrics`, `alarms` and `tracing`. Label
it: "Azure Monitor includes a Log Analytics allowance; CloudWatch charges from the
first GB. Actual cost depends on log verbosity and retention."

It is the one line that is **not** a designed service, so it has no entry in
`aws-design.json services[]` and must not be counted as one. It is also
estate-wide, so its `per_cluster` attribution is `cluster_id: null` rather than a
cluster picked arbitrarily.

This entry REPLACES any CloudWatch row a supporting-services line would otherwise
add — never double-count.

The ALB line's LCU count comes from the same file
(`alb_lcu_estimate.default_lcus`), for the same reason.

---

## Part 2C-2: Standing network charges (NAT Gateway + load balancer)

<!-- Precedent: gcp-to-aws references/phases/estimate/estimate-infra.md:170-171 prices the
     NAT line "From VPC design" and the ALB line "From compute service count" — i.e. from
     the DESIGN, not from a services[] row. Mirror that here as estate-wide STANDING lines,
     in the same spirit as Part 2C's estate-wide observability line. -->

Two network charges are structural to the target architecture and are billed whether or
not any `services[]` entry names them. So, exactly like the Part 2C observability line,
they are emitted from the **design**, not from a `services[]` row:

1. **Standing NAT Gateway line** — derived from the VPC/AZ design, priced whenever a NAT
   **will be emitted**. Generate's default posture puts compute/database in **private
   subnets** across a **2-AZ** VPC (shared posture:
   `skills/tf-best-practices/references/security-posture-rules.md` — VPC spans
   ≥2 AZ, public+private subnets, NAT for private egress), and Azure's NAT Gateway is
   regional while AWS's is zonal, so one source resource becomes one per AZ. When the AZ
   count is not explicit upstream, **default N to 2** (the 2-AZ private-subnet VPC Generate
   emits) and price `nat_gateway.monthly_fixed × 2` (+ `nat_gateway.per_gb_processed × GB`
   when a data volume is known; otherwise state the per-GB component as unquantified in
   `assumptions[]`). Record the assumption in `assumptions[]`: "default 2-AZ private-subnet
   VPC per generate posture; AZ count not explicit upstream." Emit this line even when no
   `services[]` entry maps to a NAT Gateway — a private-subnet design still pays it.
   `service_id: "standing-nat-gateway"`, `cluster_id: null`.

2. **Standing ALB/NLB line** — derived from the edge/compute design. A public edge
   (Application Gateway / Front Door / public L7 LB → **ALB**) prices from
   `alb.monthly_fixed + alb.per_lcu_hour × 730 × LCU`; an L4 edge (→ **NLB**) prices from
   `nlb.monthly_fixed + nlb.per_lcu_hour × 730 × LCU` using the new `nlb` rate row. The LCU
   count is `alb_lcu_estimate.default_lcus`. Emit it even when no `services[]` entry names a
   load balancer — **except** where a LoadBalanced Elastic Beanstalk environment already
   provisions its balancer (that ALB is priced inside the EB line; do not re-add it — the
   double-balancer trap). `service_id: "standing-load-balancer"`, `cluster_id: null`.

The standing NAT line is `$0` **strictly** for a design that emits NO NAT at all — a
fully-public design, or a SingleInstance Elastic-Beanstalk-only estate, with no private
subnets. Reserve the zero-with-`basis` note for that genuine no-NAT case (say so in the
`basis`); a private-subnet design is NOT a $0 case — it prices the 2-AZ standing NAT above.
The standing balancer line stays `$0`-safe as before: a design whose only balancer is
already inside an EB line emits it at`$0`with its own note. Emitting a genuine no-NAT /
no-standalone-balancer line zero-with-`basis` rather than omitting it matches the Part 2
convention that a considered line stays visible.

---

## Part 2D: Totals

```
lift_total        = sum(per-service lift costs)        — excluding every line with an exclusion_reason
right_sized_total = sum(per-service right-sized costs) — excluding every line with an exclusion_reason
```

Each total must equal the arithmetic sum of its own per-service lines. A total
that does not reconcile is a gate failure, not a rounding note. When any line was
excluded, **both totals are floors**, and every presentation of them says so.

Excluded lines still appear in the breakdown, carrying their `exclusion_reason`,
whatever partial figure is known, and `excluded_from_total: true`. Dropping them
from the breakdown entirely would make the estate look smaller than it is, which
is the failure this whole section exists to prevent.

---

## Part 2E: The three pricing scenarios the shared schema requires

**The dual output does NOT replace the three scenarios, and this is the easiest
thing in the phase to get wrong.** They are different axes:

| Axis                | Varies                                                 | Keys                                                                   |
| ------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------- |
| Dual output (azure) | **sizing** — source capacity vs the recommended design | `projected_costs.lift`, `projected_costs.right_sized`                  |
| Scenarios (shared)  | **resilience and pricing model** for one design        | `aws_monthly_premium`, `aws_monthly_balanced`, `aws_monthly_optimized` |

`references/vendored/estimate/estimation-infra.schema.json` lists all three
scenario keys under `projected_costs.required`. It has no
`additionalProperties: false`, so the azure `lift` / `right_sized` keys are legal
additions — but "no `additionalProperties: false`" permits ADDING, it does not
permit OMITTING a required key. An artifact carrying only the dual output fails
the schema this phase declares.

**The anchor: `aws_monthly_balanced` IS the right-sized total.** They are the same
number by definition — the recommended design at on-demand rates — so emit them
equal rather than computing a second figure that could drift from it.

Derive the other two as **stated adjustments off Balanced**, never as fresh rate
lookups:

| Scenario      | Derivation                                                                                                                                                                                                                                                                                                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Premium**   | Balanced plus the multi-AZ uplift for every line whose `multi_az_handling` is `multiplier_x2` and which is not already multi-AZ. Lines that are `baked_in` (RDS) or `intrinsic` (MSK, Aurora) get **no** uplift — that is what `_multi_az_convention` in the rate file is for, and applying a blanket multiplier here reintroduces exactly the error it prevents                                  |
| **Optimized** | Balanced with a commitment discount applied **only to the RI/SP-eligible subtotal**, per `references/vendored/estimate/ri-sp-eligibility.md`, plus the ineligible subtotal unchanged. Use the mid-point of the applicable range from `estimate-defaults.json`. A blanket percentage across the whole total silently discounts S3, ALB, EBS and CloudWatch, none of which has a commitment product |

State the discount rate and the two subtotals, so the arithmetic is checkable
without trusting the author. And note the eligibility carefully on an Azure
estate: **MSK has no RI or Savings Plan product**, so it belongs in the ineligible
subtotal even though it looks like the kind of thing that would be covered.

**Every scenario figure inherits the floor.** If any line was excluded, all three
scenarios are floors, and Optimized is the most misleading of them — a discounted
floor reads as the cheapest credible number in the artifact when it is the least
complete.

### Two shape constraints the schema imposes

- **`projected_costs.breakdown` is an OBJECT, not an array** — keyed by
  `service_id`, values being the line shape above, plus a `total` key holding the
  Balanced total. This matches what the other skills emit; an array here is a
  schema violation that `_validate_json` will not catch, because it checks
  parseability rather than conformance.
- **`accuracy_confidence` is a STRING**, e.g. `"floor — five lines unpriced;
  ±5-10% on the rest"`. Any structured detail belongs in
  `pricing_source.message` or its own key, not here.

---

## Part 3: Comparison, and the licensing delta

### Azure vs AWS

When Part 1 produced a baseline from any rung except `unavailable`, present:

- The Azure monthly baseline, **labeled with its rung and accuracy**, repeating
  `baseline_note` next to the number whenever it is not invoice data.
- Both AWS totals — lift and right-sized — each marked a floor when any line was
  excluded.
- The difference against each, monthly and annual.
- A per-cluster breakdown of the right-sized total, using `clusters[]` from the
  design, so the customer can see which part of the estate drives the bill.

```json
"cost_comparison": {
  "azure_monthly_baseline": "<Part 1 figure or null>",
  "baseline_source": "<rung>",
  "lift": { "aws_monthly": "<lift_total>", "is_floor": true, "monthly_difference": "<lift - azure>", "annual_difference": "<x12>", "percent_change": "<+/-X%>" },
  "right_sized": { "aws_monthly": "<right_sized_total>", "is_floor": true, "monthly_difference": "<right_sized - azure>", "annual_difference": "<x12>", "percent_change": "<+/-X%>" },
  "rightsizing_delta": {
    "monthly": "<lift_total - right_sized_total>",
    "annual": "<x12>",
    "basis": "<'declared_waste' | 'utilization' | 'both' | 'none'>",
    "explanation": "<REQUIRED — and REQUIRED to say WHY whenever monthly is 0>",
    "declared_waste_found": ["<REQUIRED whenever the IaC declares waste, even when it moves no dollars>"],
    "what_would_change_this": "<what evidence would make the delta non-zero>"
  },
  "per_cluster": [
    {
      "cluster_id": "<a cluster_id from aws-design.json clusters[], or null for an estate-wide line>",
      "right_sized_monthly": "<sum of this cluster's priced lines>",
      "is_floor": "<true when any of this cluster's lines was excluded>",
      "lines": ["<service_id, ...>"],
      "note": "<REQUIRED when the figure is 0 and the cluster is not actually free>"
    }
  ]
}
```

`declared_waste_found` is not optional decoration. The idle-capacity finding is
often the estate's clearest cost problem, and it can be real while moving no
dollars — because the design flagged it rather than removing it, or because its
line was excluded. Losing it on the grounds that the delta is zero drops the
finding a customer would most want.

**Every `per_cluster` figure of `$0.00` needs its `note`.** A cluster whose every
line was excluded reads as free, and it is not — it is unpriced. The per-cluster
figures plus any `cluster_id: null` estate-wide line must sum to the right-sized
total.

Also emit `financial_summary`, which restates the headline in the opposite sign
convention because report readers expect "savings" to be positive:

```json
"financial_summary": {
  "azure_monthly": "<baseline or null>",
  "aws_monthly_right_sized": "<right_sized_total>",
  "aws_monthly_is_floor": "<true when any line was excluded>",
  "monthly_savings_right_sized": "<azure - aws; the NEGATION of cost_comparison.right_sized.monthly_difference>"
}
```

The two sign conventions are the trap: `cost_comparison` and `roi_analysis` use
`difference = AWS − Azure` (negative means AWS cheaper), and
`financial_summary` uses `savings = Azure − AWS` (positive means AWS cheaper).
They are the same fact and must be exact negations of each other. Never print
either as a bare signed value.

**Sign convention:** `difference = AWS − Azure`, so a negative number means AWS
is cheaper. Never print a bare signed value; always label it, e.g. "AWS is $X/mo
cheaper".

When `current_costs.source == "unavailable"`, set `azure_monthly_baseline` to
null and present the AWS totals alone: "No Azure baseline was established, so
these are AWS costs without a comparison. Tell us your approximate Azure monthly
spend and we will produce the side-by-side."

### The licensing delta line

**Render this line if and only if `preferences.licensing._fired` is true.** When
Clarify's licensing category did not fire, no licensing line appears anywhere —
not as a zero, not as "not applicable".

It is **one delta row, not a cost model**. What it says depends on
`licensing.windows_model`:

| `windows_model`    | The delta line                                                                                                                                                                                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `license_included` | AWS bills the Windows licence inside the instance rate. State the count of Windows workloads and their vCPU total, note that the AWS-side licence cost is **not in the estimate** (see the `partial` rule above), and that this is the line most likely to move the total |
| `byol`             | The customer brings licences. State the Dedicated Host or tenancy requirement BYOL implies, because it changes the instance line rather than adding to it                                                                                                                 |
| unanswered         | Render no figure. State that the licensing basis is unresolved and that the Windows compute line cannot be finalised without it                                                                                                                                           |

Two facts to carry across from `preferences.licensing`:

- **`ahub_in_use: false`** means the Azure baseline carries an unreduced Windows
  rate, so the Azure side is not understated on licence grounds. When it is
  `true`, the Azure baseline already benefits from Hybrid Benefit and the
  comparison is not like-for-like — say so rather than comparing anyway.
- Anything in `licensing.blockers[]` is a **prerequisite, not a cost**. An
  Azure-Edition Windows image that AWS Application Migration Service refuses is
  work that must happen before replication starts; it is not a line item.
  Reference it, and do not price it.

```json
"licensing_delta": {
  "fired": true,
  "windows_model": "<from preferences>",
  "windows_workload_count": "<N>",
  "windows_vcpu_total": "<N>",
  "ahub_in_use": false,
  "monthly_delta": null,
  "delta_basis": "<the rate and where it came from, or why this is null>",
  "note": "<per the table above>",
  "blockers_are_not_costs": ["<one entry per licensing.blockers[] entry, naming it and why it is a prerequisite>"]
}
```

`blockers_are_not_costs` entries must carry **no dollar figure**. Putting one
there converts a scheduling fact into a fabricated cost, which is exactly the
confusion the key exists to prevent.

`monthly_delta` is `null` whenever the Windows rate is unavailable. A null with a
stated reason is honest. A remembered per-vCPU figure is not, however plausible
it looks.

---

## Part 4: Migration cost considerations

**Azure charges egress and Heroku does not**, so do not carry a "no egress fees"
framing across from another skill. Categories — none of them priced without a
data volume:

| Category                               | Basis                                                                                                                                                                                              |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Azure egress during transfer**       | Per-GB outbound from Azure. Needs a data volume: database size, blob storage size, VM disk footprint. Name the sources from the inventory and state the volume as unknown rather than assuming one |
| **Parallel operation**                 | Both clouds run during cutover: `~<Azure baseline>/month` for the cutover window, when a baseline exists                                                                                           |
| **Migration service cost**             | DMS instance hours when `data.db_cutover` is `dms`; MGN replication-server hours when `design_constraints.vm_cutover` is `mgn`. Both are real AWS charges and both are duration-driven             |
| **Unexpired Azure commitments**        | A reservation or savings plan that outlives cutover keeps costing after the workload has left. A genuine migration cost, and invisible unless named                                                |
| **Dual-write or replication overhead** | Only when the chosen cutover approach implies it                                                                                                                                                   |

**No human labor.** No professional-services figure, no people-time, no day
rate, no "N engineer-weeks × $X". Effort belongs to the timeline band, never to a
dollar column. This holds across every part of this fragment.

---

## Part 5: ROI

Present the monthly and annual difference between the Azure baseline and each AWS
total. If AWS is cheaper, state the saving against each. If AWS is more
expensive, state that plainly and justify it with operational benefits rather
than burying it below the fold.

Qualitative factors only — **assign no dollar value** to any of these:
infrastructure control, autoscaling granularity, service breadth, reduced
dependence on the cloud being left, compliance posture, and access to commitment
products Azure priced differently.

Repeat the sign convention beside any signed number, and repeat the floor caveat
wherever a total that excludes lines appears in an ROI sentence.

---

## Part 6: Optimization opportunities

Eligibility, the three-state rendering model, and the required caveats are
defined in `references/vendored/estimate/ri-sp-eligibility.md`. Execute that
file's matrix as this step — it is the source of truth on eligibility. Only the
azure-specific shaping lives here.

**Always render this section**, even when nothing qualifies: state which of the
three states the design landed in rather than omitting the section.

- **The customer may already hold Azure reservations or a savings plan.** If
  `reservation_substitutions` is non-empty, or the user mentioned reservations, a
  commitment product is not a new idea to them — it is what they already do, and
  migrating resets its clock. Frame it as continuity. An unexpired Azure
  commitment is a **sunk cost that survives cutover**, and it belongs in Part 4.
- **Graviton is not offered by default.** The design chose `x86_64` deliberately,
  for Windows and .NET. Raise an arm64 opportunity only for a workload whose
  stack is known to be portable, and raise it in the `workshop` sidebar where the
  customer sees both prices — not as an assumed saving here. A withdrawn
  recommendation costs more trust than one never made.
- **Declared waste is not an "opportunity"** — it is already inside the
  right-sized total. Listing it here double-counts the saving.

---

## Part 7: Complexity tier

Load the thresholds from `references/vendored/estimate/complexity-tiers.json` and
classify from the largest tier down, first match wins. Inputs:

| Input         | Source                                                                                                 |
| ------------- | ------------------------------------------------------------------------------------------------------ |
| Service count | `aws-design.json` `services[]` length                                                                  |
| Cluster count | `aws-design.json` `clusters[]` length                                                                  |
| Monthly spend | the right-sized total                                                                                  |
| Has databases | any `aws_service` in {RDS PostgreSQL, DocumentDB, ElastiCache Redis, MSK, FSx for Windows File Server} |
| Availability  | `preferences.data.availability`                                                                        |
| Compliance    | `preferences.design_constraints.compliance` (array; see below)                                         |
| Multi-region  | more than one distinct `aws_config.region`                                                             |
| Licensing     | `preferences.licensing._fired`                                                                         |

Three azure-specific notes. A `deferred[]` entry raises complexity even though it
carries no cost — deferred work is still work. A **floor** total must not pull the
tier down: when lines were excluded, classify on the evidence that those services
exist, not on a total that omits them. And:

**Read `preferences.design_constraints.compliance`.** Clarify now always asks this
(Q-A1c, ESSENTIAL). Normalize the array before classifying:

- **No frameworks (explicit none):** `[]` (canonical) or `["none"]` (accepted
  alias from the AI-only path). Record `complexity_inputs.compliance` as `[]`.
  `compliance_present` is false. Do **not** emit `compliance_never_asked`.
- **Unconfirmed:** `["unknown"]`, or a still-null ESSENTIAL row that somehow
  reached Estimate. Record the raw value, treat the catalog like "none" (no
  speculative BAA-only stack), emit `compliance_unconfirmed`, and let Part 8
  hard-trigger 1 evaluate its **second** clause (regulated signals) rather than
  treating unknown as permanently true.
- **Named frameworks:** `["soc2"]`, `["pci"]`, … — `compliance_present` is true
  when any entry is a named framework (not `none`/`unknown`).

Never invent `"none"` as a string scalar. Never write `compliance: null` on a run
whose Clarify artifact already has a compliance row.

`compliance_never_asked` remains in the closed vocabulary only for **pre-question
frozen artifacts** (the `after-estimate/` capability-run snapshot). Live Estimate
must not emit it once Q-A1c exists.

**The tier here is driven by a row count, not by money.** `service_count_gte: 9`
fires on the literal `services[]` length, which includes `$0` networking
primitives, while `monthly_spend_gt: 10000` can be missed by an order of magnitude.
A $465/month estate can therefore classify `large`. That is the shared table's
behaviour and it is followed literally — `complexity-tiers.json` says
`metadata.total_services` and nothing distinguishes billable from free — but the
artifact should say which condition fired, so a reader is not left inferring that
the estate is expensive.

```json
"complexity_tier": "small|medium|large",
"complexity_inputs": {
  "service_count": "<N>", "cluster_count": "<N>",
  "monthly_spend": "<right-sized>", "monthly_spend_is_floor": true,
  "has_databases": true, "availability": "<...>", "compliance": "<...>",
  "multi_region": false, "licensing_fired": true, "deferred_count": "<N>"
}
```

---

## Part 8: Recommendation

`path` says how a migration would run; `outcome` says whether to run it now.

**Hard triggers — any one forces `outcome: "defer_for_evidence"`:**

| # | Trigger                                                                                                                                                                                                                                          | Evidence to name                                            |
| - | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| 1 | Compliance is `["unknown"]` or unanswered **and** signals suggest a government or heavily regulated requirement — the region set, service catalog and pricing all change together. An explicit `[]` / `["none"]` does **not** fire this trigger. | Confirmation from the customer's compliance owner           |
| 2 | The customer's **only** stated motivation is cost saving **and** no baseline exists at all (`current_costs.source == "unavailable"`)                                                                                                             | An Azure Cost Management export, or a stated monthly figure |

`defer_for_evidence` is expected to be **rare**: AWS almost always has the
services, and the AWS-side estimate can almost always be produced. Prefer
`conditional_go` with named conditions when in doubt.

**Soft triggers — never force a defer. Each becomes an entry in `conditions[]`
(so `outcome` becomes `conditional_go`) and in `would_flip_if[]`:**

| # | Trigger                                                                | Condition wording                                                                                         |
| - | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 3 | `data.availability` was defaulted rather than confirmed                | "Confirm the availability requirement — Multi-AZ roughly doubles the database line"                       |
| 4 | Any line is `unavailable` or `partial`, so a total is a floor          | "Price `<services>` before treating the total as decision-grade — today it is a floor"                    |
| 5 | `target_region` differs from the pricing cache region                  | "Reprice in `<target_region>` — these are `<cache region>` rates"                                         |
| 6 | The pricing cache is past its own staleness window                     | "Refresh pricing before treating the delta as decision-grade"                                             |
| 7 | `licensing._fired` and the Windows licence cost is not in the estimate | "Confirm the Windows licensing basis — it is the line most likely to move the total"                      |
| 8 | The right-sizing delta is `$0` for want of utilization data            | "Supply utilization data to see what right-sizing is worth; today the delta reflects declared waste only" |

**Derivation:**

```
IF any hard trigger fired      -> "defer_for_evidence"
ELSE IF path == "stay"         -> "stay"
ELSE IF any soft trigger fired -> "conditional_go"   (conditions[] = the fired triggers)
ELSE                           -> "go"
```

Complexity alone selects `path: "migrate_phased"`; it never moves `outcome` away
from go or conditional_go.

Populate `decision_basis` from provenance — inventory-extracted or invoice values
are `measured`, defaulted inputs are `assumed`, declined or unknown ones are
`unknown` — and `would_flip_if[]` with the 1–3 changes most likely to alter the
outcome, each with its direction.

**Presenting a defer:** lead with what IS established ("AWS can host this estate;
the AWS-side floor is $X/mo") before naming the one missing piece of evidence and
how to obtain it. Never present a defer as "no answer".

```json
"recommendation": {
  "path": "migrate_optimized|migrate_phased|stay",
  "path_label": "<label>",
  "outcome": "go|conditional_go|defer_for_evidence|stay",
  "outcome_label": "<label>",
  "roi_justification": "<one sentence>",
  "confidence": "high|medium|low",
  "migrate_if": ["<specific to THIS estate>"],
  "stay_if": ["<specific to THIS estate>"],
  "conditions": ["<non-empty when outcome is conditional_go>"],
  "decision_basis": { "measured": [], "assumed": [], "unknown": [] },
  "would_flip_if": [],
  "next_steps": []
}
```

`outcome: "stay"` only ever accompanies `path: "stay"`.

**Cost labeling.** Every dollar figure presented anywhere — chat, report, metric
box — is labeled as an estimate ("Est." or "estimated monthly"). Never present a
computed figure as exact.

---

## The Estimate warning vocabulary — CLOSED

Discover and Design each declare a closed warning vocabulary, on the grounds that
an invented code makes the report's grouping unstable. Estimate had none, which
left every code in this phase improvised. **This vocabulary is closed on the same
terms: add a row here first, then use it.**

| Code                                | Fires when                                                                                                                          |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `pricing_unavailable`               | A line's rate row does not exist and no formula constant carries it — `exclusion_reason: no_rate`                                   |
| `pricing_partial`                   | A base rate resolved but a required component did not — `exclusion_reason: partial_rate`                                            |
| `quantity_unavailable`              | Every rate resolved but no quantity exists to multiply — `exclusion_reason: no_quantity`                                            |
| `rate_configuration_mismatch`       | The rate describes a different configuration than the design (single-AZ priced from a Multi-AZ table)                               |
| `region_rate_mismatch`              | `target_region` differs from the pricing cache's `_meta.region`                                                                     |
| `pricing_cache_stale`               | The cache is past its own `staleness_days` window                                                                                   |
| `baseline_not_invoiced`             | The Azure baseline came from any rung other than a Cost Management export                                                           |
| `baseline_unavailable`              | No Azure baseline could be established at all                                                                                       |
| `quantity_from_stated_baseline`     | A line was priced from a rate file's own `monthly_baseline_est` rather than an estate quantity                                      |
| `component_not_sized`               | A priced line's sub-component has a rate but no quantity (MSK per-broker storage)                                                   |
| `rightsizing_delta_zero_no_metrics` | The delta is `$0` because no utilization data exists                                                                                |
| `declared_waste_found`              | The IaC declares waste (an idle plan, an unattached disk)                                                                           |
| `licensing_cost_absent`             | `licensing._fired` and the Windows rate is unavailable                                                                              |
| `deferred_bears_azure_cost`         | A `deferred[]` entry is cost-bearing on Azure, so the baseline includes it and the AWS side does not                                |
| `compliance_unconfirmed`            | Clarify asked compliance and the recorded value is `["unknown"]` (or still null); catalog treated like none, report caveat required |
| `compliance_never_asked`            | **Legacy.** Pre-Q-A1c frozen artifacts only. Do not emit on a live run after Clarify records a compliance row                       |

Each warning carries `code`, a human `message`, and the `service_id` it concerns
where it concerns one. **If a situation needs a code that is not here, add the row
in this file before emitting it** — an improvised code is indistinguishable from a
typo to whatever groups the report.

When Parts 1–8 are complete, control passes to `estimate-assemble.md`.
