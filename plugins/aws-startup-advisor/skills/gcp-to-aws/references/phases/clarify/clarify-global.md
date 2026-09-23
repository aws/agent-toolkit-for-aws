---
_fragment: global
_of_phase: clarify
_contributes:
  - preferences.json (global section, design_constraints section; created here, finalized by the assembler)
---

# Category A — Global/Strategic (Always Fires)

> **Fragment unit.** See `clarify.md` for how it is composed into the phase.
>
> **This fragment asks nothing.** It reads discovery, resolves what it can, assigns a
> disposition per row, and returns rows. `clarify-assemble.md` presents them.

These foundational constraints gate everything downstream — region selection, service
catalog, data residency, credits eligibility, compute platform, availability topology, and
migration strategy.

**Five of these questions are canonical, shared with `azure-to-aws`** — see
`references/vendored/clarify/`. Read the linked file for the question text, options, and
interpretation rule; this fragment supplies only GCP's auto-extraction signal, default, and
disposition escalation. Q3 (GCP spend) and Q3.5 (CUDs) are GCP-specific — no shared file, no
Azure equivalent (Azure's commitment story is Reservations/Savings Plans, framed as a finding
in Estimate rather than a Clarify question — see `estimate-infra.md`).

## Step 1: Extract before proposing

Resolve from discovery first — a DETECTED row costs the user nothing to confirm, and a
question discovery could have answered is a question that should not have been asked.

| Read from discovery                                                                                                | Resolves                                                                              |
| ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| GCP regions across all PRIMARY compute/database resources in `gcp-resource-inventory.json`                         | single-region vs multi-region — the input to Q1 / Q1b                                 |
| `billing-profile.json → summary.total_monthly_spend`                                                               | GCP spend band (Q3)                                                                   |
| `billing-profile.json → commitments.has_active_cuds`                                                               | whether Q3.5 fires at all                                                             |
| each `google_sql_database_instance`'s `availability_type` / `config.availability_type`                             | context for the availability question (Q6) — **never the answer**, same rule as Azure |
| Cloud Run `min_instance_count` / `min_instances` (context only, not extracted here — see `clarify-compute.md` Q10) | whether Category C's traffic question can auto-resolve                                |

## Step 2: The rows

### Q1 — Target AWS region + user geography

Canonical question: `references/vendored/clarify/clarify-region.md`.

**Disposition:** DETECTED when the inventory has a **single** GCP region among PRIMARY
compute/database resources — map to the closest AWS region and record
`chosen_by: "extracted"`. **ESSENTIAL** when multiple regions are present, or when there is
no infrastructure inventory at all (billing-only or AI-only mode reaching this fragment).

**GCP's auto-extraction shortcut:** unlike Azure (which asks a separate user-geography
question whenever the map alone can't decide a CDN strategy), GCP treats a single detected
GCP region as sufficient to resolve BOTH the region mapping AND `user_geography:
"single-region"` in one extraction — this is a documented shortcut, not a claim that GCP has
independently verified where end users are. State this on the sheet row's source field
(`"terraform:single-region-assumed-single-geography"`) rather than a bare `"extracted"`, so a
reader can tell the assumption apart from a genuine multi-signal confirmation.

**Default when ESSENTIAL and skipped:** answer 1 (single region, closest AWS region to the
GCP region present in the inventory).

### Q2 — Compliance and regulatory requirements — **ESSENTIAL, always**

Canonical question: `references/vendored/clarify/clarify-compliance.md`. No GCP-specific
auto-extraction signal exists (compliance status is never inferable from Terraform), so this
fragment supplies no override to the canonical file's disposition, options, or default. Ask
it exactly as written there — always ESSENTIAL, never skipped, never silently defaulted to
"none."

### Q3 — Approximately how much are you spending on GCP per month in total? — GCP-specific

**Auto-extract signal:** If `billing-profile.json` exists, map `summary.total_monthly_spend`
to the spend band below and **skip Q3** when unambiguous (`chosen_by: "extracted"`). If
billing is absent or ambiguous, ask Q3.

| Monthly USD   | `gcp_monthly_spend` |
| ------------- | ------------------- |
| < 1,000       | `"<$1K"`            |
| 1,000–4,999   | `"$1K-$5K"`         |
| 5,000–19,999  | `"$5K-$20K"`        |
| 20,000–99,999 | `"$20K-$100K"`      |
| ≥ 100,000     | `">$100K"`          |

**Rationale:** Total GCP spend is the primary input for ARR estimation, which determines
credits eligibility tier. Also provides a sanity check for cost estimates when billing data is
not uploaded.

> Total GCP spend helps me estimate AWS credits eligibility and provides a cost baseline for
> the migration plan.
>
> 1. < $1,000/month
> 2. $1,000–$5,000/month
> 3. $5,000–$20,000/month
> 4. $20,000–$100,000/month
> 5. $100,000/month
> 6. I don't know

**Billing enrichment (when Q3 is not skipped):** If `billing-profile.json` exists but
extraction was skipped due to ambiguity, show:

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

**Default:** 2 — `gcp_monthly_spend: "$1K-$5K"`.

### Q3.5 — Do you have active GCP Committed Use Discounts (CUDs)? — GCP-specific

**Conditional:** Only fires if `billing-profile.json` exists AND
`commitments.has_active_cuds == true`. N/A otherwise. GCP's CUD product has no Azure
analogue in Clarify — Azure's Reservations/Savings Plan continuity is surfaced as a finding
in `estimate-infra.md` Part 6, not a question here, because AHUB/Reservations are
architecturally different from GCP CUDs (see that file for why).

**Rationale:** Active CUDs affect migration timing and cost comparison accuracy. If a
customer has unexpired CUDs, they'll continue paying commitment fees even after migrating —
this is a sunk cost that affects the migration ROI timeline. Also determines whether to
compare against GCP list price or committed rate.

> Your billing data shows active Committed Use Discounts (~[effective_discount_percent]%
> effective discount). CUD timing affects migration ROI — commitment fees continue regardless
> of usage until the term expires.
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

**Default:** 5 — `cud_status: "none"`.

### Q5 — Multi-cloud portability

Canonical question: `references/vendored/clarify/clarify-multicloud.md`. **Disposition:**
PROPOSED when compute resources are present; N/A otherwise. **Default:** per the canonical
file — no constraint, full compute decision tree.

GCP's early exit skips `clarify-compute.md`'s **Q8** (Kubernetes sentiment) and **Q7b**
(App Engine compute-operational-model) — App Engine routes to EKS instead of its normal
Elastic Beanstalk default, overriding the Q7b default the same way it overrides Q8's.

### Q6 — Availability / downtime tolerance

Canonical question: `references/vendored/clarify/clarify-availability.md`.

**Disposition:** DETECTED when all Cloud SQL PostgreSQL/MySQL instances agree on the mapped
`availability_type`; **ESSENTIAL** on conflict or when `availability_type` is missing on any
instance; PROPOSED when no Cloud SQL signal exists but a database resource is present some
other way.

**GCP's auto-extraction signal** (per the canonical file's "what a consuming skill supplies"
§1): read each `google_sql_database_instance`'s `availability_type` (or
`config.availability_type`):

| GCP value  | `availability` extracted |
| ---------- | ------------------------ |
| `ZONAL`    | `"single-az"`            |
| `REGIONAL` | `"multi-az"`             |

Resolve this question only when **all** Cloud SQL PostgreSQL/MySQL instances agree on the
same mapped value. `multi-az-ha` and `multi-region` are **never** auto-extracted — those
require this question's Mission-Critical / Catastrophic answers. Cloud SQL `REGIONAL` maps to
`multi-az` (RDS Multi-AZ), not `multi-az-ha` (Aurora) — GCP's `REGIONAL` HA is not the same
tier as Aurora's HA.

**GCP's default (per the canonical file's §2 — a deliberate, documented choice, not
convergence with Azure's Single-AZ default):** **Multi-AZ** (answer 2) when unanswered. This
is a conservative middle ground: GCP customers arriving with no HA signal at all (billing-only
mode, or Cloud SQL absent) are defaulted to a safer tier than Azure's Single-AZ default,
because GCP's typical inbound estate (Cloud Run / Cloud Functions-heavy) carries less
already-provisioned HA context to escalate against than Azure's VM/Flexible-Server-heavy
estates do.

**GCP's escalation rule (per the canonical file's §3):** when Cloud SQL instances disagree, or
when `availability_type` is missing on any instance, escalate to ESSENTIAL rather than
defaulting — the multi-instance conflict handling in `clarify-assemble.md` covers the
per-instance breakdown presentation.

### Q7 — Maintenance window / cutover strategy — **ESSENTIAL, always**

**No GCP↔Azure canonical file** — GCP asks this as one unified question (a single cutover
decision governs both compute and database cutover); Azure splits it into two ESSENTIAL
questions (VM cutover in `clarify-compute.md` Q-C6, DB cutover in `clarify-database.md` Q-D2)
because Azure's VM-replication runbook (MGN) and its database-replication runbook (DMS) are
different tools answering different questions. GCP's compute targets (Cloud Run, GKE, Cloud
Functions) do not have an Azure-VM-style "replicate the guest" option, so one cutover question
suffices here. This divergence is intentional, not drift — do not unify these into a shared
file; the underlying decision shapes are different.

**Rationale:** Determines cutover strategy and which database migration tooling is
recommended. Zero-downtime migrations require significantly more complex infrastructure
(blue/green, traffic shifting). With a maintenance window, databases can be taken offline
briefly and migrated with native tools — without one, live replication via DMS is required.

**Database migration tooling notes:**

- Use the **in-flight resolved Q13b value** (`db_size` — resolved in `clarify-database.md`)
  to select the right tool. Do NOT read `preferences.json` here: mid-Clarify it does not exist
  yet, and on a re-run any file present is a prior run's stale answers. If Q13b is not yet
  resolved, fall back to the size thresholds below.
- For PostgreSQL databases `db_size: "<10GB"` or unknown-small: **pg_dump/pg_restore** is
  sufficient.
- For PostgreSQL databases `db_size: "10-100GB"` or `"100-500GB"`: **pgcopydb** offers parallel
  table copying and index rebuilding, significantly reducing migration time within the same
  maintenance window.
- For PostgreSQL databases `db_size: ">500GB"`: **AWS DMS strongly recommended** regardless of
  maintenance window — single-pass export/import at this scale is high-risk.
- pgcopydb's CDC mode requires `wal_level=logical` on Cloud SQL, which must be enabled
  explicitly.

> The maintenance window determines your migration cutover strategy and which database
> migration tooling we recommend. Zero-downtime migrations require significantly more complex
> infrastructure.
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

**Default:** 4 — `cutover_strategy: "flexible"`.

## Step 3: Rows returned

```jsonc
"global": {
  "target_region":     { "disposition": "DETECTED", "value": "us-west-2", "default": "us-west-2",
                         "source": "terraform:single-region-assumed-single-geography" },
  "user_geography":    { "disposition": "DETECTED", "value": "single-region", "default": "single-region",
                         "source": "terraform:single-region-assumed-single-geography" }
},
"design_constraints": {
  "compliance":        { "disposition": "ESSENTIAL", "value": null, "default": null },
  "availability":      { "disposition": "DETECTED", "value": "single-az", "default": "multi-az",
                         "source": "terraform:availability_type=ZONAL" },
  "compute":           { "disposition": "PROPOSED", "value": null, "default": null,
                         "reason": "no multi-cloud requirement stated" },
  "cutover_strategy":  { "disposition": "ESSENTIAL", "value": null, "default": "flexible" }
},
"baseline": {
  "gcp_monthly_spend": { "disposition": "DETECTED", "value": "$1K-$5K", "default": "$1K-$5K",
                         "source": "billing:summary.total_monthly_spend" },
  "cud_status":        { "disposition": "N/A", "value": null, "default": null,
                         "reason": "no active CUDs in billing-profile.json" }
}
```

`cpu_architecture` is **not** here — it belongs to `clarify-compute.md`, same reasoning as
Azure's fragment: whether it is a question at all depends on which compute is present.

## Who consumes these

| Row                 | Consumer                                                                              |
| ------------------- | ------------------------------------------------------------------------------------- |
| `target_region`     | Design's region selection; every downstream cost figure                               |
| `user_geography`    | Design's CDN / Route 53 strategy, and the availability question's Catastrophic branch |
| `compliance`        | Design's service catalog, region gate, and security-baseline defaults                 |
| `availability`      | `clarify-database.md`'s RDS-vs-Aurora family selection (post-rubric override)         |
| `compute`           | `clarify-compute.md`'s Q7b/Q8 early-exit check                                        |
| `cutover_strategy`  | Generate's migration runbook shape, and the DMS-versus-pg_dump tooling choice         |
| `gcp_monthly_spend` | Estimate's migrate-vs-stay comparison and Activate credits tier                       |
| `cud_status`        | Estimate's commitment-overlap ROI framing                                             |

## Status — build step 5 (restructure)

Implemented. Restructured from the pre-fragment monolithic `clarify.md` into the
fragment-returns-rows / assembler-owns-conversation pattern shared with `azure-to-aws`. Five
of these seven questions (region, compliance, availability, multi-cloud, cost-appetite — the
last lives in Category E below, not in this fragment, per
`references/vendored/clarify/clarify-cost-appetite.md` § "What a consuming skill supplies")
now read their question text and options from the canonical `references/vendored/clarify/`
files instead of carrying an independent copy. Q3/Q3.5/Q7 remain GCP-owned with no shared
file, because they have no Azure equivalent or a genuinely different decision shape.
