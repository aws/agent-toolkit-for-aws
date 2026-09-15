# Assessment — Sizing

Sizing is delegated to the managing-amazon-msk Skill's pricing logic. This skill
implements no sizing math and packages no sizing script of its own. Derive the
workload inputs from the discovery contract, then use that skill's pricing logic
to produce the recommended instance type, broker count, and monthly cost.

> **Response format**: the assessment response template that covers both
> compatibility AND sizing artifacts lives in
> [`assessment-compatibility.md`](./assessment-compatibility.md) under
> "Response Template". Do not invent a separate sizing-only response shape;
> the user gets one combined response with both artifact paths.

## Using managing-amazon-msk Skill's pricing logic (agent flow)

1. **Load the managing-amazon-msk Skill.** How you reach its sizing script depends
   on how skills are available in this environment — the same MCP-vs-local split
   described in the guardrail section of
   [assessment-compatibility.md](./assessment-compatibility.md), applied to the
   other skill:
   - **AWS MCP available.** Call `retrieve_skill` for the `managing-amazon-msk`
     skill, then fetch `scripts/msk_sizing.py` through the same tool by passing
     `file="scripts/msk_sizing.py"`, and run the content it returns.
   - **Skills installed locally.** Run the script from the local
     `managing-amazon-msk` skill directory, for example
     `uv run <path to skills>/managing-amazon-msk/scripts/msk_sizing.py ...`. Sibling
     skill directories live alongside this one (`.claude/skills/`,
     `~/.claude/skills/`, `.kiro/skills/`, etc.).
2. **Read `target.rack_affined_consumers` and `target.pricing_discount_pct` from the
   discovery contract.** Ask the user only for the ones that are `null` or absent.
   Both are covered in the next two sections.
3. **Derive the workload inputs** from `cluster-config.json` per "Deriving the
   sizing inputs" below. Two of the conversions are not one-to-one; getting them
   wrong produces a silently incorrect broker count.
4. **Run sizing with `--broker-classes express`** to understand the options, sizing constraints, and cost explanations. `--broker-classes express` keeps Standard instance types out of the output entirely. Verify the script's "Sizing inputs" block matches the values you intended to pass before reading any broker count. Add `standard` to the flag only in the comparison cases listed below. Add `--discount-pct` and `--no-rack-affined-consumers` per the answers from step 2.
5. **Read the recommendations.** Create an `msk_sizing_pricing.md` summary explaining the recommendation, inputs, sizing scenario, constraints, and cost-optimization tradeoffs for the workload. Record which pricing basis and rack-affinity assumption produced the figures.

## Deriving the sizing inputs

`cluster-config.json` records throughput **per broker** and partitions as **leader
counts**. `msk_sizing.py` expects **total cluster** throughput and **total partition
replicas**. Apply these conversions — do not pass the contract values through
unchanged.

| `msk_sizing.py` flag | Derivation from `cluster-config.json` |
|---|---|
| `--peak-data-in-mbs` | `metrics.peak_bytes_in_per_broker_mbps` **× `topology.num_brokers`** |
| `--peak-data-out-mbs` | `metrics.peak_bytes_out_per_broker_mbps` **× `topology.num_brokers`** |
| `--avg-data-in-mbs` | `metrics.avg_bytes_in_per_broker_mbps` **× `topology.num_brokers`**. When the field is `null`, use `peak_in / 2` and say so in `msk_sizing_pricing.md`. |
| `--avg-data-out-mbs` | `metrics.avg_bytes_out_per_broker_mbps` **× `topology.num_brokers`**. When the field is `null`, use `peak_out / 2` and say so in `msk_sizing_pricing.md`. |
| `--num-partitions` | `sum(topics[].num_partitions)` **× 3**. The contract stores leader counts; the flag wants total replicas, and Express always uses RF=3. Never use the source cluster's own replication factor here. |
| `--retention-hours` | `ceil(max(topics[].configs["retention.ms"]) ÷ 3_600_000)` — the flag takes an integer hour count, so round up so retention is never under-estimated. Default to 24 when no topic declares it. |
| `--primary-retention-hours` | Same value as `--retention-hours` — equal values disable Tiered Storage, which is correct for an Express target. If customer asks to compare Standard, and uses Tiered Storage today, pass the customer's Tiered Storage configuration. Only relevant for when customer asks for Standard comparison. |
| `--replication-factor` | Omit. The default of 3 matches Express. |
| `--broker-classes` | `express` (see "Present Express only"). |
| `--discount-pct` | `target.pricing_discount_pct` (see "Negotiated pricing"). |
| `--no-rack-affined-consumers` | Pass when `target.rack_affined_consumers` is `false` (see "Consumer rack affinity"). |

Record the derived values — not the raw contract values — in
`msk-sizing-inputs.<cluster_name>.json`, so the sizing run is reproducible.

If `metrics` is absent entirely or `topology.num_brokers` is `null`, you cannot
derive total throughput. Report that sizing could not be produced and surface the
compatibility `METRICS_MISSING` advisory. Do not substitute guessed throughput
figures, and do not pivot back into discovery to collect them.

## Negotiated pricing

Read `target.pricing_discount_pct` from `cluster-config.json`. A number is the
percentage the customer stated (`0` means they confirmed no discount). When the field
is `null` or absent, ask — alongside the rack affinity question if that one is also
missing:

> Does your organization have a Private Pricing Agreement (PPA), Enterprise Discount
> Program (EDP), or other negotiated AWS pricing? If so, what discount percentage
> should I apply? Without one I will report public on-demand pricing.

Pass it as `--discount-pct N`, which applies the discount uniformly to brokers,
storage, Express data-in, and cross-AZ transfer. Broker counts do not change.

Do not guess a percentage and do not apply one the customer did not state. When they
do not have a discount or do not know it, run at public pricing and include this note
in `msk_sizing_pricing.md`:

> **Note on pricing:** All cost estimates are based on AWS public on-demand pricing. If your organization has a Private Pricing Agreement (PPA), Enterprise Discount Program (EDP), or other negotiated pricing, your actual costs will differ. Contact your AWS account team for pricing that reflects your agreements.

When a discount was applied, state the percentage in `msk_sizing_pricing.md` and tell
the customer to confirm it with their AWS account team before using the figures for
budgeting.

## Consumer rack affinity

Cross-AZ consumer fetch is often one of the largest line items in the estimate. Read
`target.rack_affined_consumers` from `cluster-config.json`. When it is `null` or
absent, ask before you run sizing — this and negotiated pricing are the only inputs
Assessment may request (see "Assessment scope — forbidden behavior" in
[assessment-compatibility.md](./assessment-compatibility.md)):

> Will your consumers fetch from local-AZ replicas on the Express target — rack-aware
> fetching, with `client.rack` set on each consumer and
> `replica.selector.class=RackAwareReplicaSelector` on the cluster — or will they fetch
> from partition leaders in any AZ?

Map the contract value (or the answer) to the sizing flags:

| `target.rack_affined_consumers` | Answer | Flag |
|---|---|---|
| `true` | Rack-aware / local-AZ fetching | Omit the flag — rack affinity is the script default |
| `false` | Fetch from leaders in any AZ, or no rack configuration planned | `--no-rack-affined-consumers` |
| `null` | Unknown | Run both ways |

For a self-managed source there may be no AZ topology to carry over, so treat this as
a decision about the target rather than a fact about the source. Ask whether they
intend to configure rack-aware fetching on the Express cluster.

When the answer is unknown, run sizing both ways, report the rack-affined figure as
the recommendation, and present the difference as avoidable cost. Recommend enabling
rack-aware fetching on the target either way — see
`references/configure-clients.md` in the `managing-amazon-msk` skill for
the `client.rack` and `replica.selector.class` settings.

This flag changes cost only, never broker count. State which assumption you used in
`msk_sizing_pricing.md`.

## Present Express only

This skill migrates workloads to Express. Report the Express pick; do not put Standard instance types, broker counts, or costs in `msk_sizing_pricing.md` or in your response.

Run with `--broker-classes standard,express` only when the customer explicitly asks to compare classes, asks why not Standard, or hits a Standard-only condition. Refer to `references/size-and-choose-cluster.md` in the managing-amazon-msk skill, lead with the Express pick and present Standard as the alternative, giving the context from the decision framework on why Express is better than Standard even with cost differences.

Do not volunteer Standard as a cost-optimization path, including Tiered Storage. Express storage is billed per GB-hour on data actually retained, which is the cost-effective option for nearly all workloads.

If the workload exceeds the broker quota at every Express size, recommend a quota increase, not Standard (which would also exceed broker quotas).

## Compare the recommendation against the source footprint

Source clusters are frequently over-provisioned — sized for peak plus a safety margin, then never scaled back. Recommend the smaller, lower-cost target when the workload supports it, and show the delta.

1. Pull the source footprint from `cluster-config.json`: `topology.num_brokers`, `topology.num_azs`, `topology.broker_instance_type`.
2. Compare it against the Express recommendation. Recommend the Express pick even when it is materially smaller than the source. The script already models peak throughput, 1-AZ-down headroom, and partition limits, so a smaller broker count is not a reduction in resilience.
3. Explain why the target is smaller in terms the customer can verify: up to 3x ingress per broker, storage billed on retained data instead of provisioned EBS, and capacity for replication and rebalancing reserved by the service rather than bought as spare nodes.
4. State what you could not verify. Node-for-node comparison needs `topology.broker_instance_type`, which is optional in the discovery contract. Without it, compare broker counts only and say so.

Do not inflate the recommendation to match the source footprint. If the customer wants headroom beyond what the script models, name the recommended pick first and the larger option second, with the cost difference.

## Caveats

1. **Average throughput is optional in the discovery contract.** The sizing script
   uses average throughput for storage volume and cost projection (e.g. cross-AZ
   data transfer). When `metrics.avg_bytes_*_per_broker_mbps` is `null`, the
   `peak / 2` fallback from the derivation table applies and the cost figures are
   correspondingly rough. Real average values give more accurate cost projections;
   broker count is driven by peak either way.

2. **Retention is per-topic in the discovery contract; the skill takes one
   number.** The skill emits the max over topics as an upper-bound storage
   estimate. Override by passing a smaller `--retention-hours` (derived per the
   table above) if the source has a small set of low-retention topics dominating
   the storage picture, and say so in `msk_sizing_pricing.md`. Express storage is billed
   per GB-hour on retained data, so right-sizing per-topic retention is the
   storage cost lever — not a change of broker class.

3. **Pricing is us-east-1 and public on-demand by default.** Cost figures do not
   reflect other AWS Regions. Apply a customer-stated Private Pricing Agreement
   (PPA) or Enterprise Discount Program (EDP) discount with `--discount-pct` — see
   "Negotiated pricing" above.

## Key recommendations

- **Express recommendations**: Broker instance size (express.m7g.large through
  express.m7g.16xlarge) and count
- **Bottleneck breakdown**: per instance, which
  constraint (ingress / egress / partitions / storage) drives the broker
  count.

## Refresh procedure

When new skill updates are released, pricing logic can be re-run with the managing-amazon-msk Skill's pricing logic.

## Security considerations

- **Discovery input may contain credentials.** The sizing inputs are derived from
  `cluster-config.json`, whose `security` block may carry credential material
  (SASL passwords, API keys, TLS private keys) if discovery captured more than the
  authentication mechanism. Verify the input has none before deriving inputs or
  sharing the file; redact anything resembling a credential.
- **Sizing inputs reveal capacity and topology details.** The
  `msk-sizing-inputs.<cluster_name>.json` and `msk_sizing_pricing.md` artifacts
  contain peak throughput, partition count, retention, and the recommended
  broker count and instance type for the workload. Treat them as sensitive —
  these details are useful inputs for targeted attacks. Do not share via
  unencrypted email, public channels, or public ticketing systems without
  redaction.
- **Store with restrictive permissions.** Keep the artifact inside
  `migrate-to-msk-skill-artifacts/<cluster_name>/` and apply restrictive
  permissions (e.g., `chmod 600`) appropriate for your environment.
