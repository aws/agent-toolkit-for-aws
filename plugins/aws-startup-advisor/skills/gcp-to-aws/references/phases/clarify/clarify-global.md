# Category A — Global/Strategic (Always Fires)

These foundational constraints gate everything downstream — region selection, service catalog, data residency, credits eligibility, compute platform, availability topology, and migration strategy.

Present questions with a conversational tone and brief context explaining why each matters.

---

## Q1 — Where are your users located?

**Auto-extract signal:** When `gcp-resource-inventory.json` shows a **single** GCP region among PRIMARY compute/database resources, map to the closest AWS region and **skip Q1** with `target_region` `chosen_by: "extracted"`. When multiple regions are present, suggest the closest AWS region as default but still ask Q1.

**Rationale:** Geography drives AWS region selection and CDN strategy.

> I need to understand your user base to recommend the right AWS region and CDN strategy.
> (This question is about where your **users** are — latency and placement. If you have **data residency** obligations, GDPR or similar, that's handled by the compliance question, not this one.)
>
> 1. Single region (e.g., US-only, EU-only)
> 2. Multi-region (2–3 regions, e.g., US + EU)
> 3. Global (users worldwide, latency critical)
> 4. I don't know

| Answer        | Recommendation Impact                                                                                                                                                                                                                     |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Single region | Deploy in closest AWS region to users; standard Route 53 routing                                                                                                                                                                          |
| Multi-region  | Primary region closest to majority; CloudFront for static assets and API caching; Route 53 latency-based routing — multi-region infrastructure deferred to Q6                                                                             |
| Global        | Primary region by largest user concentration; CloudFront globally distributed; Route 53 geolocation routing — Aurora Global Database and multi-region compute only if Q6 = Catastrophic AND write latency is a confirmed hard requirement |

Interpret:

```
1 -> target_region: "<closest AWS region to GCP region in inventory>"
2 -> target_region: "<closest AWS region>", replication: "cross-region"
3 -> target_region: "<closest AWS region>", replication: "cross-region", cdn: "required"
4 -> same as default (1)
```

Default: 1 — single region, closest AWS region to GCP region in inventory.

---

## Q2 — Do you have any compliance or regulatory requirements?

**Rationale:** Compliance requirements gate entire service categories and regions. A HIPAA customer cannot use the same architecture as an unconstrained startup.

> Compliance requirements determine which AWS services, regions, and configurations are available to you. This gates the entire architecture.
>
> 1. None — No specific compliance requirements
> 2. SOC 2 / ISO 27001 — Security and availability standards
> 3. PCI DSS — Payment card data handling
> 4. HIPAA — Healthcare data
> 5. FedRAMP / Government — Federal compliance
> 6. GDPR / Data residency — EU data sovereignty requirements
> 7. CCPA / CPRA — California Consumer Privacy Act / California Privacy Rights Act
> 8. I don't know
>
> _(Multiple selections allowed)_

| Answer            | Recommendation Impact                                                                                                                                                                                                                                                                                                                                          |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| None              | Full service catalog available, any region                                                                                                                                                                                                                                                                                                                     |
| SOC 2 / ISO 27001 | CloudTrail, Config, Security Hub enabled by default; encryption at rest required                                                                                                                                                                                                                                                                               |
| PCI DSS           | CloudTrail, Config, Security Hub + PCI DSS standard enabled by default; dedicated VPC with strict segmentation; WAF required; no shared tenancy for cardholder data; specific RDS encryption config                                                                                                                                                            |
| HIPAA             | CloudTrail, Config, Security Hub (FSBP only — Security Hub does not provide a HIPAA-specific standard) enabled by default; BAA-eligible services only; encryption in transit and at rest mandatory; specific logging requirements; us-east-1/us-west-2 preferred; engage a qualified HIPAA auditor for end-to-end posture validation                           |
| FedRAMP           | CloudTrail, Config, Security Hub (FSBP only — NIST 800-53 is the target control set but is not directly subscribable in Security Hub the way PCI DSS is; engage your AWS account team for agency-level attestation) enabled by default; GovCloud regions required (us-gov-east-1, us-gov-west-1); GovCloud-specific service endpoints; limited service catalog |
| GDPR              | EU regions required (eu-west-1, eu-central-1), data residency constraints, no cross-region replication outside EU without explicit consent                                                                                                                                                                                                                     |
| CCPA / CPRA       | Consumer privacy posture: data inventory, access/deletion workflows, opt-out of sale/sharing where applicable, retention minimization, encryption and audit logging (CloudTrail); prefer documenting data flows and subprocessors — confirm target regions with legal/compliance (often US)                                                                    |

Interpret:

```
1 -> (no constraint written — user explicitly confirmed no requirements; full service catalog, any region)
2 -> compliance: ["soc2"] — CloudTrail, Config, Security Hub enabled; encryption at rest required
3 -> compliance: ["pci"] — Dedicated VPC, WAF required, strict segmentation
4 -> compliance: ["hipaa"] — BAA-eligible services only, encryption mandatory, us-east-1/us-west-2 preferred
5 -> compliance: ["fedramp"] — GovCloud regions required (us-gov-east-1, us-gov-west-1)
6 -> compliance: ["gdpr"] — EU regions required (eu-west-1, eu-central-1), data residency constraints
7 -> compliance: ["ccpa"] — CCPA/CPRA: logging, retention, consumer-request readiness; document data flows; align region/subprocessor choices with legal review
8 -> compliance: ["unknown"] — not confirmed; verify with compliance team before production
```

**Defaulted / "I don't know" semantics:** When Q2 resolves without an explicit user selection — answer 8, or "use defaults for the rest" — write `compliance: ["unknown"]` (`chosen_by: "user"` for 8, `"default"` with `source: "default:Q2"` for defaults). Never silently record "no requirements". Downstream, `["unknown"]` behaves exactly like "none" for architecture and service selection (no speculative BAA-only stack), but it triggers the report's compliance caveat and counts as unverified in decision confidence.

Default: `compliance: ["unknown"]` — unconfirmed, with report caveat (only reachable via "use defaults for the rest"; Q2 is otherwise always asked).

---

## Q3 — Approximately how much are you spending on GCP per month in total?

**Auto-extract signal:** If `billing-profile.json` exists, map `summary.total_monthly_spend` to the spend band below and **skip Q3** when unambiguous (`chosen_by: "extracted"`). If billing is absent or ambiguous, ask Q3.

| Monthly USD   | `gcp_monthly_spend` |
| ------------- | ------------------- |
| < 1,000       | `"<$1K"`            |
| 1,000–4,999   | `"$1K-$5K"`         |
| 5,000–19,999  | `"$5K-$20K"`        |
| 20,000–99,999 | `"$20K-$100K"`      |
| ≥ 100,000     | `">$100K"`          |

**Rationale:** Total GCP spend is the primary input for ARR estimation, which determines credits eligibility tier. Also provides a sanity check for cost estimates when billing data is not uploaded.

> Total GCP spend helps me estimate AWS credits eligibility and provides a cost baseline for the migration plan.
>
> 1. < $1,000/month
> 2. $1,000–$5,000/month
> 3. $5,000–$20,000/month
> 4. $20,000–$100,000/month
> 5. $100,000/month
> 6. I don't know

**Billing enrichment (when Q3 is not skipped):** If `billing-profile.json` exists but extraction was skipped due to ambiguity, show:

> Your billing data shows ~$[total_monthly_spend]/month. Does this match your expectation?

| Answer                 | Recommendation Impact                                                                              |
| ---------------------- | -------------------------------------------------------------------------------------------------- |
| < $1,000/month         | Entry-tier migration funding programs may apply; cost estimates use conservative ranges            |
| $1,000–$5,000/month    | Migration funding review may apply; cost estimates use mid-range assumptions                       |
| $5,000–$20,000/month   | Migration funding review may apply; reserved pricing options are evaluated in cost recommendations |
| $20,000–$100,000/month | Migration funding and support program review may apply; savings commitment options are evaluated   |
| > $100,000/month       | Enterprise migration program review may apply; dedicated migration support path may be recommended |

Interpret:

```
1 -> gcp_monthly_spend: "<$1K" — entry-tier funding review; conservative cost assumptions
2 -> gcp_monthly_spend: "$1K-$5K" — funding review; mid-range cost assumptions
3 -> gcp_monthly_spend: "$5K-$20K" — funding review; reserved pricing recommendations
4 -> gcp_monthly_spend: "$20K-$100K" — funding/support review; savings commitment analysis
5 -> gcp_monthly_spend: ">$100K" — enterprise program/support review
6 -> same as default (2)
```

Default: 2 — `gcp_monthly_spend: "$1K-$5K"`.

---

## Q3.5 — Do you have active GCP Committed Use Discounts (CUDs)?

**Rationale:** Active CUDs affect migration timing and cost comparison accuracy. If a customer has unexpired CUDs, they'll continue paying commitment fees even after migrating — this is a sunk cost that affects the migration ROI timeline. Also determines whether to compare against GCP list price or committed rate.

**Conditional:** Only ask if `billing-profile.json` exists AND `commitments.has_active_cuds == true`. If billing data shows active CUDs, present the detected information and ask for confirmation/details.

> Your billing data shows active Committed Use Discounts (~[effective_discount_percent]% effective discount). CUD timing affects migration ROI — commitment fees continue regardless of usage until the term expires.
>
> 1. Yes, and they expire within 6 months
> 2. Yes, and they expire in 6–12 months
> 3. Yes, and they have more than 12 months remaining
> 4. Yes, but I'm not sure when they expire
> 5. No active CUDs / I don't know
> 6. I plan to let them expire and not renew

| Answer                        | Recommendation Impact                                                                                                 |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Expire within 6 months        | Migration timing favorable — plan migration to coincide with CUD expiration for clean cost transition                 |
| Expire in 6–12 months         | Consider phased migration starting now; some overlap cost is acceptable for operational benefits                      |
| More than 12 months remaining | Factor CUD overlap cost into ROI analysis; migration still viable if operational benefits justify dual-payment period |
| Not sure when they expire     | Recommend customer check GCP console (Billing → Commitments) before finalizing migration timeline                     |
| No active CUDs                | No commitment overlap concern; migrate on any timeline                                                                |
| Plan to let them expire       | Align migration completion with CUD expiration date for optimal cost transition                                       |

Interpret:

```
1 -> cud_status: "expiring_soon" — Align migration with CUD expiration
2 -> cud_status: "expiring_medium" — Phased migration acceptable; some overlap cost
3 -> cud_status: "long_remaining" — Factor overlap into ROI; justify with operational benefits
4 -> cud_status: "unknown_expiry" — Recommend checking GCP console
5 -> cud_status: "none" — No constraint
6 -> cud_status: "not_renewing" — Align migration completion with expiration
```

Default: 5 — `cud_status: "none"` (no constraint on migration timing).

If `billing-profile.json` does not exist or `commitments.has_active_cuds == false`, **skip this question entirely**.

---

## Q4 — _(Skipped in wizard mode)_

**Do not infer funding stage or AWS Activate tier from GCP spend (Q3) or AI spend (Q15).** Self-funded and VC-backed startups can have identical monthly bills.

Activate package selection is owned by **Q27** (`startup_program_status`) when Category H fires. In full Clarify flow, Q4 may be asked explicitly if product adds a standalone funding-stage question; until then, `funding_stage` is not set.

---

## Q5 — Do you need to run workloads across multiple cloud providers?

**Rationale:** Multi-cloud portability is an early exit condition that immediately determines the compute recommendation without needing further questions. If multi-cloud is required, Kubernetes (EKS) is the only portable abstraction layer.

> Multi-cloud portability is an immediate decision point — if required, Kubernetes (EKS) is the only portable abstraction, and we can skip several compute questions.
>
> 1. Yes, multi-cloud required
> 2. No, AWS-only is acceptable
> 3. I don't know

| Answer                    | Recommendation Impact                                                                                                |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Yes, multi-cloud required | **Immediate EKS recommendation** — Kubernetes is the only portable abstraction layer. Skip Q8. ECS Fargate excluded. |
| No, AWS-only acceptable   | Full compute decision tree continues — EKS vs ECS Fargate evaluated based on K8s sentiment (Q8)                      |

Interpret:

```
1 -> compute: "eks" — Immediate EKS recommendation. EARLY EXIT: skip Q8.
2 -> (no constraint written — full compute decision tree continues)
3 -> same as default (2) — assume AWS-only
```

Default: 2 — no constraint, evaluate full compute options.

---

## Q6 — If your application went down unexpectedly right now, what would happen?

**Auto-extract signal (Cloud SQL PostgreSQL/MySQL only):** Read `availability_type` from `google_sql_database_instance` (`config.availability_type` or top-level). When unambiguous:

| GCP value  | `availability` extracted | Skip Q6?                       |
| ---------- | ------------------------ | ------------------------------ |
| `ZONAL`    | `"single-az"`            | Yes — `chosen_by: "extracted"` |
| `REGIONAL` | `"multi-az"`             | Yes — `chosen_by: "extracted"` |

**Never auto-extract:** `multi-az-ha` and `multi-region` require Q6 user answers (Mission-Critical / Catastrophic) — IaC cannot infer these. Cloud SQL `REGIONAL` is RDS Multi-AZ (`multi-az`), not Aurora (`multi-az-ha`). Skip Q6 only when **all** instances agree. When instances disagree or `availability_type` is missing on any instance, ask Q6.

**Rationale:** Availability requirements drive database engine selection, deployment topology, and whether multi-AZ is mandatory. Aurora Global Database and multi-region compute are only recommended when Catastrophic is selected AND Q1 confirms global users — both signals are required.

**Cloud SQL PostgreSQL / MySQL → RDS vs Aurora (decision order):** For customers on Cloud SQL (PostgreSQL or MySQL), **Q6 is the only question that selects the AWS product family** — **RDS** (PostgreSQL or MySQL, matching the Cloud SQL engine) vs **Aurora** (Aurora PostgreSQL or Aurora MySQL). **Q12–Q13 never override Q6**; they tune sizing, replicas, storage/I/O billing, and Aurora variants **after** Q6 has chosen RDS or Aurora. When Cloud SQL is detected, you may add: _"For dev/staging or workloads where brief outage is tolerable, RDS PostgreSQL is usually simpler and cheaper; Aurora is for mission-critical HA needs."_

**Context for user:** When asking, include these descriptions so the user can self-select accurately:

- **Inconvenient** — users can wait, no revenue impact (e.g., internal tool, dev/staging environment, hobby project)
- **Significant Issue** — users notice and complain, some revenue impact, but workarounds exist (e.g., B2B SaaS with email support SLA)
- **Mission-Critical** — direct revenue loss per minute of downtime, SLA obligations to customers, needs fast recovery (e.g., e-commerce checkout, paid API)
- **Catastrophic** — regulatory, safety, or major financial consequences; every minute of downtime is measurable loss (e.g., financial transactions, healthcare systems, real-time trading)

> Availability requirements drive database engine selection, deployment topology, and whether multi-AZ is mandatory.
>
> 1. INCONVENIENT — Users can wait, brief outages tolerable (5–30 min)
> 2. SIGNIFICANT ISSUE — Customers frustrated, revenue loss
> 3. MISSION-CRITICAL — Cannot tolerate outages, SLA violations
> 4. CATASTROPHIC — Regulatory, safety, or major financial consequences per minute of downtime
> 5. I don't know

| Answer            | Recommendation Impact                                                                                                                                                                                                                                  |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Inconvenient      | Single-AZ RDS acceptable, standard ECS/EKS deployment, no special HA requirements                                                                                                                                                                      |
| Significant Issue | Multi-AZ RDS required, ALB with health checks, auto-scaling groups                                                                                                                                                                                     |
| Mission-Critical  | Aurora Multi-AZ (higher availability than RDS), multi-AZ mandatory, Route 53 health checks; single-region with fast failover is sufficient for most mission-critical workloads                                                                         |
| Catastrophic      | If Q1 = Global: Aurora Global Database + active-active multi-region + Route 53 failover routing; If Q1 = Single/Multi-region: Aurora Multi-AZ with aggressive RTO/RPO targets is sufficient — global infrastructure not warranted without global users |

Interpret:

```
1 -> availability: "single-az" — Single-AZ RDS acceptable, standard deployment
2 -> availability: "multi-az" — Multi-AZ RDS required, ALB with health checks, auto-scaling
3 -> availability: "multi-az-ha" — Aurora Multi-AZ, multi-AZ mandatory, Route 53 health checks
4 -> IF Q1 = 3 (Global): availability: "multi-region" — Aurora Global Database + active-active multi-region + Route 53 failover
     IF Q1 = 1 or 2: availability: "multi-az-ha" — Aurora Multi-AZ with aggressive RTO/RPO (global infra not warranted without global users)
5 -> same as default (2) — assume multi-AZ for safety
```

Default: 2 — `availability: "multi-az"`.

---

## Q7 — Do you have a scheduled maintenance window where downtime is acceptable?

**Rationale:** Determines cutover strategy and which database migration tooling is recommended. Zero-downtime migrations require significantly more complex infrastructure (blue/green, traffic shifting). With a maintenance window, databases can be taken offline briefly and migrated with native tools — without one, live replication via DMS is required.

**Database migration tooling notes:**

- Use the **in-flight resolved Q13b value** (`db_size` from Step 2 extraction, the confirmed Assumption Sheet, or `preferences-draft.json` — Q13b is defined in `clarify-database.md`) to select the right tool. Do NOT read `preferences.json` here: mid-Clarify it does not exist yet (it is written at Step 5), and on a re-run any file present is a prior run's stale answers. If Q13b is not yet resolved, fall back to the size thresholds below.
- For PostgreSQL databases `db_size: "<10GB"` or unknown-small: **pg_dump/pg_restore** is sufficient.
- For PostgreSQL databases `db_size: "10-100GB"` or `"100-500GB"`: **pgcopydb** offers parallel table copying and index rebuilding, significantly reducing migration time within the same maintenance window.
- For PostgreSQL databases `db_size: ">500GB"`: **AWS DMS strongly recommended** regardless of maintenance window — single-pass export/import at this scale is high-risk.
- pgcopydb's CDC mode requires `wal_level=logical` on Cloud SQL, which must be enabled explicitly.

> The maintenance window determines your migration cutover strategy and which database migration tooling we recommend. Zero-downtime migrations require significantly more complex infrastructure.
>
> 1. Yes — weekly maintenance window (e.g., Sunday 2–4am)
> 2. Yes — monthly maintenance window only
> 3. No — zero downtime required, must use blue/green or rolling deployment
> 4. Flexible — we can schedule one if needed
> 5. I don't know

| Answer         | Recommendation Impact                                                                                                                                                                                                                                       |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Weekly window  | Standard cutover with DNS switchover during window; **pg_dump/pg_restore** for PostgreSQL <10GB; **pgcopydb** for larger databases — parallel copying cuts migration time significantly; no DMS licensing, no replication lag risk                          |
| Monthly window | Cutover timed to monthly window; pg_dump/pg_restore or **pgcopydb** depending on DB size; blue/green for application layer                                                                                                                                  |
| Zero downtime  | **AWS DMS required** for live database replication; blue/green deployment for application layer; **RDS blue/green deployments** (RDS path per Q6) or **Aurora blue/green deployments** (Aurora path per Q6); Route 53 weighted routing for traffic shifting |
| Flexible       | Recommend scheduling a weekly window to enable pg_dump/pgcopydb approach; falls back to DMS if window cannot be arranged                                                                                                                                    |

Interpret:

```
1 -> cutover_strategy: "maintenance-window-weekly" — pg_dump/pg_restore or pgcopydb recommended; standard cutover with DNS switchover
2 -> cutover_strategy: "maintenance-window-monthly" — pg_dump/pg_restore or pgcopydb recommended; blue/green for app layer
3 -> cutover_strategy: "zero-downtime" — AWS DMS required for live DB replication; blue/green deployment; Route 53 weighted routing
4 -> cutover_strategy: "flexible" — Recommend scheduling weekly window for pg_dump approach; DMS fallback
5 -> same as default (4) — assume flexible
```

Default: 4 — `cutover_strategy: "flexible"`.
