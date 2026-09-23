# Estimate — Reserved Instance / Savings Plan Eligibility (canonical)

> Canonical AWS commitment-discount eligibility reference for estimate cost
> engines, vendored into each skill that emits `optimization_opportunities[]`
> (`references/vendored/estimate/ri-sp-eligibility.md`) and kept byte-identical
> by `shared:sync`. This file answers ONE question: **which AWS commitment
> product (if any) applies to a given AWS target service, under what
> conditions, and what are its actual term options.** It is deliberately
> source-cloud-agnostic — nothing here depends on whether the workload came
> from GCP, Heroku, Azure, or anywhere else. Source-cloud billing quirks (e.g.
> a source platform showing `$0` for a pre-paid reserved resource) belong in
> that skill's own discovery phase, not here.

## Why this file exists

Before this file, `gcp-to-aws` and `heroku-to-aws` each carried their own,
independently-drifting list of "which services get a Savings Plan/RI callout."
Both lists had real gaps: Database Savings Plan coverage was gated on
"RDS/Aurora in design" only, missing DynamoDB/ElastiCache entirely; neither
skill distinguished DynamoDB on-demand from provisioned (only provisioned
supports DynamoDB reserved capacity); neither distinguished ElastiCache engine
(Database Savings Plans cover ElastiCache for Valkey only — Redis OSS and
Memcached still require Reserved Nodes); and Bedrock Provisioned Throughput
was implicitly lumped in with "1-year or 3-year" language it does not have
(its commitment terms are no-commit / 1-month / 6-month, billed hourly). This
file is the single source of truth so those distinctions get made once and
stay correct everywhere they're consumed.

## Eligibility matrix

| AWS service / usage mode                                           | RI-eligible                                                                                                                                                                                                                                       | SP-eligible                        | Which SP              | Notes                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| EC2, Fargate, Lambda                                               | EC2 only (EC2 Reserved Instances or EC2 Instance Savings Plans)                                                                                                                                                                                   | Yes                                | Compute Savings Plan  | Compute SP applies automatically across EC2 (any family/size/OS/region/tenancy), Fargate, and Lambda. Do not gate SP eligibility on "serverless vs provisioned" — gate strictly on this product list.                                                                                                                                                                                                 |
| RDS / Aurora — **provisioned**                                     | Yes (RDS/Aurora Reserved DB Instances)                                                                                                                                                                                                            | Yes                                | Database Savings Plan | RI and Database SP are **mutually exclusive on the same instance** — pick one per workload; a workload may use RIs while another workload on the same account uses Database SP.                                                                                                                                                                                                                       |
| Aurora Serverless v2                                               | No                                                                                                                                                                                                                                                | Yes                                | Database Savings Plan | No RI product exists for serverless database capacity.                                                                                                                                                                                                                                                                                                                                                |
| DynamoDB — **provisioned**, Standard table class                   | Yes (DynamoDB reserved capacity: 1-year or 3-year term, up to 54%/77% savings)                                                                                                                                                                    | Yes                                | Database Savings Plan | RI and Database SP are mutually exclusive on the same capacity, same rule as RDS. Reserved capacity is purchased in 100 WCU/RCU allocations.                                                                                                                                                                                                                                                          |
| DynamoDB — **on-demand**, or Standard-IA table class               | **No** — AWS explicitly excludes on-demand and Standard-IA from reserved capacity                                                                                                                                                                 | Yes                                | Database Savings Plan | Database Savings Plan is the only commitment lever for on-demand DynamoDB. Never present a DynamoDB on-demand design with an RI-style callout.                                                                                                                                                                                                                                                        |
| ElastiCache — **Valkey, provisioned (node-based)**                 | Yes (ElastiCache Reserved Nodes)                                                                                                                                                                                                                  | Yes                                | Database Savings Plan | Database SP coverage for ElastiCache is **Valkey-only**. Both RI and SP apply here — Database SP is generally preferable post-migration for flexibility (see gcp-to-aws's RDS-parallel guidance); Reserved Nodes remain an option for a stable, long-lived node footprint.                                                                                                                            |
| ElastiCache — **Valkey, serverless**                               | **No** — ElastiCache Serverless has no node concept (billed in ECPUs + GB-hours); Reserved Nodes require a node-based cluster and do not apply                                                                                                    | Yes                                | Database Savings Plan | Database SP is the only lever for serverless ElastiCache, regardless of engine.                                                                                                                                                                                                                                                                                                                       |
| ElastiCache — **Redis OSS or Memcached, provisioned (node-based)** | Yes (ElastiCache Reserved Nodes)                                                                                                                                                                                                                  | **No**                             | —                     | Not Database-SP-eligible. **This matters directly for any skill whose default target engine is Redis OSS** — check the Design phase's actual selected engine before emitting a Database SP opportunity for ElastiCache; fall back to "Reserved Nodes only" language for Redis OSS/Memcached targets.                                                                                                  |
| ElastiCache — **Redis OSS or Memcached, serverless**               | **No** — same Serverless/Reserved-Nodes incompatibility as above                                                                                                                                                                                  | **No**                             | —                     | No commitment product of any kind applies — not Database SP (wrong engine) and not Reserved Nodes (serverless, no nodes to reserve). State this plainly rather than defaulting to the Reserved Nodes language used for the provisioned case.                                                                                                                                                          |
| DocumentDB, Neptune, Keyspaces, DMS                                | Some have their own RI-equivalents (verify per-service before claiming one exists)                                                                                                                                                                | Yes                                | Database Savings Plan | Lower priority — surface only when present in the design.                                                                                                                                                                                                                                                                                                                                             |
| OpenSearch Service                                                 | Yes (OpenSearch Reserved Instances)                                                                                                                                                                                                               | Yes                                | Database Savings Plan | —                                                                                                                                                                                                                                                                                                                                                                                                     |
| Timestream                                                         | Unconfirmed whether Database SP coverage is restricted to a specific sub-product (e.g. InfluxDB) — verify against current AWS documentation before shipping copy more specific than "Timestream is on AWS's Database Savings Plan coverage list." | Yes (generic Timestream is listed) | Database Savings Plan | Flagged as needing verification; do not assert a sub-product restriction without confirming it.                                                                                                                                                                                                                                                                                                       |
| Bedrock (on-demand inference)                                      | No                                                                                                                                                                                                                                                | No                                 | —                     | The only commitment lever is **Provisioned Throughput** (`type: provisioned_throughput` in `optimization_opportunities[]`) — a distinct product, not a Savings Plan or RI variant. Terms: no-commit, 1-month, or 6-month, billed hourly. **Never describe Provisioned Throughput as having 1-year or 3-year terms.** Gate on sustained, predictable high-volume usage, not on cost-sensitivity alone. |
| AgentCore                                                          | No                                                                                                                                                                                                                                                | No                                 | —                     | Pure consumption-based pricing. No commitment product of any kind exists. State this plainly rather than omitting AgentCore from the section silently.                                                                                                                                                                                                                                                |
| S3                                                                 | No                                                                                                                                                                                                                                                | No                                 | —                     | Intelligent-Tiering is the available lever, not a commitment plan.                                                                                                                                                                                                                                                                                                                                    |

**Generation restriction (applies to Database Savings Plans generally):** AWS's
own documentation states Database Savings Plans apply to "the latest
provisioned instance generations" — older-generation instances are excluded.
Ship the qualitative "latest generation only" caveat; do not assert a specific
generation-number cutoff unless it has been confirmed against current AWS
documentation.

## Rendering: three states, not one fallback

Do not collapse eligibility into a single "does this design qualify, yes or
no" fallback message. A design's services will typically split across states,
and each state needs distinct handling:

| State                       | Example                                                                                | What to say                                                                                                                                                                                                                                                  |
| --------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| RI and/or SP eligible       | Fargate, RDS provisioned, DynamoDB provisioned, EC2                                    | Emit real `optimization_opportunities[]` entries (Compute SP, Database SP, RDS RI / DynamoDB reserved capacity as applicable).                                                                                                                               |
| SP-eligible, no RI product  | Lambda + DynamoDB on-demand, or Aurora Serverless v2, or ElastiCache Valkey serverless | State explicitly: "No Reserved Instance product applies to this usage mode, but it still qualifies for a Compute/Database Savings Plan once usage is stable."                                                                                                |
| Truly no commitment product | AgentCore + S3 + Bedrock on-demand only                                                | State explicitly: "No 1-year/3-year commitment product exists for this stack. Bedrock inference has its own separate mechanism (Provisioned Throughput, 1- or 6-month commitment) — worth evaluating only above sustained high-volume, predictable traffic." |

**Never merge per-service product attribution into one sentence.** Write "Lambda
qualifies for a Compute Savings Plan." as its own sentence, and "DynamoDB
on-demand qualifies for a Database Savings Plan." as a separate one — these
are two separate facts about two separate products; Lambda has no Database-SP
path and DynamoDB has no Compute-SP path. State each service's eligible
product by name, in its own sentence.

**Always render the Cost Optimization Opportunities section**, even when the
design lands entirely in the "truly no commitment product" state. Silent
omission reads as an analysis gap, not as "nothing applies" — say so
explicitly instead.

## Required caveats (attach wherever this file's content is rendered)

1. **Baseline-before-committing (carry over unchanged from existing practice):**
   Never size a Compute Savings Plan commitment from source-cloud billing data
   alone. Recommend 30-90 days of AWS On-Demand usage post-migration, then use
   AWS Cost Explorer Savings Plan recommendations, committing to the usage
   floor rather than the average. Database Savings Plans / RDS RIs / DynamoDB
   reserved capacity may include a preliminary dollar sizing when the target
   instance class is confirmed and projected on-demand cost clears the
   surfacing threshold (currently $50/month); Compute Savings Plans stay
   percent-only until a real AWS baseline exists.
2. **AWS credits do not cover upfront commitment costs.** Promotional or
   Activate credits cannot be applied to the upfront cost of Reserved
   Instances or Savings Plans (Partial Upfront or All Upfront) — they only
   apply to the ongoing discounted hourly rate. State this once wherever the
   Cost Optimization section renders, so "up to 66% off" is never read as free
   against credits.
3. **Mutual exclusion.** Where a workload is eligible for both an RI-equivalent
   and a Database/Compute Savings Plan (RDS RI vs Database SP; DynamoDB
   reserved capacity vs Database SP), state plainly that the two are mutually
   exclusive per workload — never imply they stack.

## Consumers

This file is read by each skill's Estimate-phase cost engine when constructing
`optimization_opportunities[]`. It replaces each skill's previously
independent, partially-divergent lists. See the skill-specific cost engine
(`estimate-infra.md` for gcp-to-aws infra, `estimate-cost-engine.md` for
heroku-to-aws, `estimate-ai.md` for gcp-to-aws's AI/Bedrock track) for the JSON
entry shapes and per-skill gating thresholds — this file defines eligibility
and required caveats, not the JSON schema or dollar formulas.

**AI-track note (`estimate-ai.md`):** this file's Bedrock row is the source of
truth for the Provisioned Throughput `type` value and commitment vocabulary.
The other six AI-side optimizations (prompt caching, model tiering, batch API,
input token reduction, multi-model routing, intelligent prompt routing) are
not AWS commitment products — they carry `commitment: "none"` and are outside
this file's eligibility matrix, which covers only RI/SP-style commitment
products. Do not add them to the matrix above; this file's scope is
commitment-product eligibility, not a general catalog of every Bedrock cost
lever.
