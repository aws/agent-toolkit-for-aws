# Clarify — Availability / Downtime Tolerance (canonical)

> Canonical availability question for Clarify's database/global category,
> vendored into each skill that runs a full-migration Clarify phase
> (`references/vendored/clarify/clarify-availability.md`) and kept
> byte-identical by `shared:sync`. This file owns the **question text, the
> four-tier answer scale (Inconvenient / Significant Issue / Mission-Critical /
> Catastrophic), and the RDS-vs-Aurora family-selection semantics** — the part
> that is identical regardless of source cloud. Each skill supplies its own
> **auto-extraction signal**, its own **default when unanswered**, and its own
> **disposition escalation rule**, because those three legitimately differ per
> source cloud (see "What a consuming skill supplies" below).

## Why this file exists

`gcp-to-aws`'s Q6 and `azure-to-aws`'s Q-D1 ask the same underlying question —
how much downtime can this workload tolerate — with the same four-tier scale,
but had drifted to different wording, different category placement (GCP:
Global/Strategic; Azure: Database), and, more importantly, **different
defaults and different escalation rules**. Centralizing the tier definitions
and the RDS-vs-Aurora selection table means a wording fix lands everywhere at
once; the default and the escalation rule stay skill-owned because they encode
a genuine per-cloud product decision (see below), not accidental drift.

## The four tiers

Present these to the user so they can self-select accurately:

- **Inconvenient** — users can wait, no revenue impact (e.g., internal tool, dev/staging
  environment, hobby project)
- **Significant Issue** — users notice and complain, some revenue impact, but workarounds
  exist (e.g., B2B SaaS with email support SLA)
- **Mission-Critical** — direct revenue loss per minute of downtime, SLA obligations to
  customers, needs fast recovery (e.g., e-commerce checkout, paid API)
- **Catastrophic** — regulatory, safety, or major financial consequences; every minute of
  downtime is measurable loss (e.g., financial transactions, healthcare systems, real-time
  trading)

## The question

> If your application went down unexpectedly right now, what would happen?
>
> 1. INCONVENIENT — Users can wait, brief outages tolerable (5–30 min)
> 2. SIGNIFICANT ISSUE — Customers frustrated, revenue loss
> 3. MISSION-CRITICAL — Cannot tolerate outages, SLA violations
> 4. CATASTROPHIC — Regulatory, safety, or major financial consequences per minute of downtime
> 5. I don't know

| Answer            | Recommendation Impact                                                                                                                                                                                                                                            |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Inconvenient      | Single-AZ RDS acceptable, standard ECS/EKS deployment, no special HA requirements                                                                                                                                                                                |
| Significant Issue | Multi-AZ RDS required, ALB with health checks, auto-scaling groups                                                                                                                                                                                               |
| Mission-Critical  | Aurora Multi-AZ (higher availability than RDS), multi-AZ mandatory, Route 53 health checks; single-region with fast failover is sufficient for most mission-critical workloads                                                                                   |
| Catastrophic      | If users are global: Aurora Global Database + active-active multi-region + Route 53 failover routing; if users are single/multi-region: Aurora Multi-AZ with aggressive RTO/RPO targets is sufficient — global infrastructure not warranted without global users |

### Interpret — RDS vs Aurora family selection

This question is **the only question that selects the AWS database product family**
(RDS vs Aurora) for a relational source engine. No other question overrides this
selection — sizing/traffic/I/O questions tune **within** the family this answer chose,
never across it.

```
1 -> availability: "single-az" — Single-AZ RDS acceptable, standard deployment
2 -> availability: "multi-az" — Multi-AZ RDS required, ALB with health checks, auto-scaling
3 -> availability: "multi-az-ha" — Aurora Multi-AZ, multi-AZ mandatory, Route 53 health checks
4 -> IF users are global: availability: "multi-region" — Aurora Global Database + active-active multi-region + Route 53 failover
     IF users are single/multi-region: availability: "multi-az-ha" — Aurora Multi-AZ with aggressive RTO/RPO (global infra not warranted without global users)
5 -> resolves per the consuming skill's documented default (see below) — never silently assumed without a stated default
```

## What a consuming skill supplies

Each skill's own fragment supplies three things this file deliberately leaves open,
because they encode real per-cloud product decisions rather than wording drift:

1. **Auto-extraction signal.** GCP reads Cloud SQL `availability_type`
   (`ZONAL`→`single-az`, `REGIONAL`→`multi-az`) and resolves this question
   automatically when every instance agrees; `multi-az-ha` and `multi-region`
   are never auto-extracted (they require this question's Mission-Critical /
   Catastrophic answers — IaC cannot infer intent, only current configuration).
   Azure reads each flexible server's `high_availability.mode` and `zone` as
   **context only, never the answer** — Azure never auto-resolves this
   question from source HA configuration, because "what they bought" is not
   "what they need." A consuming skill MAY auto-extract when its source
   platform's HA signal is unambiguous, but MUST NOT treat a zone-redundant /
   HA-enabled source as proof the customer wants (or is willing to keep
   paying for) the equivalent AWS tier — see the escalation rule below.
2. **Default when unanswered.** GCP defaults to **Multi-AZ** (2) — a
   conservative middle ground. Azure defaults to **Single-AZ** (1) — "the
   smallest defensible database line." Both are deliberate, documented
   product decisions for their respective source clouds, not accidental
   drift, and this file does not force them to converge. A consuming skill
   states its own default explicitly and explains why in its own fragment.
3. **Escalation rule when the source is already HA.** A skill whose source
   platform shows the workload is currently zone-redundant / Multi-AZ /
   HA-enabled SHOULD escalate this question's disposition to **ESSENTIAL**
   rather than silently defaulting it down — downgrading resilience the
   customer is already paying for without asking is the one thing every
   consuming skill must avoid. When a skill's resolved answer is a downgrade
   from the source's current HA posture, it MUST emit a finding saying so
   (e.g. `availability_downgrade_from_source`) rather than burying the
   downgrade in a sizing table.
