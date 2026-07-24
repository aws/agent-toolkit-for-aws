# Resilience Best Practices

## Overview

This reference provides design guidance, naming conventions, operational patterns, and anti-patterns for AWS resilience services. Use as a companion to the procedural skills when making architectural decisions or establishing team practices.

## Parameters

**tier** (optional): Service tier for policy recommendations (0, 1, 2, or 3)
**service_count** (optional): Number of services being onboarded (affects organizational guidance)

## Policy Design

### Tiered Policy Model

**Constraints:**

- You MUST recommend a tiered policy model (classify services by business criticality) rather than one policy per service
- You MUST set the availability SLO higher as criticality rises. The API accepts only a fixed set of SLO values and rejects out-of-set ones — **confirm the valid values from the API/docs** (e.g. `aws resiliencehubv2 create-policy help`) rather than relying on a hardcoded list (illustratively, values such as `99.9`/`99.95`/`99.99`).
- You MUST tighten RTO/RPO as criticality rises (single-digit minutes for critical, hours for low)
- You MUST match the DR approach to criticality (more aggressive for more critical services), using a value from the API's DR-approach enum — **verify the valid set via the API/docs** (e.g. `aws resiliencehubv2 create-policy help`); illustratively `ACTIVE_ACTIVE` … `BACKUP_AND_RESTORE`.
- Example (illustrative, not a fixed table): critical payments/auth → `99.99` + low-minutes RTO + `ACTIVE_ACTIVE`; standard internal tools → `99.9` + tens-of-minutes RTO + `WARM_STANDBY`; low dev/test → `99.9` + multi-hour RTO + `BACKUP_AND_RESTORE`. Treat the RTO figures as rough illustration, not commitments — very aggressive multi-AZ RTOs (≈1 minute) are realistic only for clean, hard failures; gray/partial failures are slower to detect and recover, so set targets you can actually meet under realistic failure modes.

### Policy Anti-Patterns

**Constraints:**

- You MUST warn against these anti-patterns:
  - Setting the maximum SLO (99.99) with Backup & Restore DR (contradictory)
  - Same policy for all services (over-engineering low-tier services)
  - Multi-region RTO < multi-AZ RTO (region failover is always slower)
  - No policy at all (assessments have no target to measure against)

## System & Service Organization

### Naming Conventions

**Constraints:**

- You SHOULD recommend consistent naming:
  - Systems: `{domain}-platform` (e.g., payment-platform, identity-platform)
  - Services: `{domain}-{component}` (e.g., payment-api, payment-processor)
  - Journeys: `{verb}-{noun}` (e.g., process-payment, authenticate-user)
  - Policies: `tier-{N}-{qualifier}` (e.g., tier-1-standard, tier-0-critical)

### Tagging Strategy

**Constraints:**

- You MUST recommend resilience-specific tags that serve double duty (NGRH discovery + FIS targeting):
  - `resilience:tier` — Policy tier (0-3)
  - `resilience:system` — Parent system name
  - `resilience:service` — Service name
  - `resilience:owner` — Owning team
  - `resilience:fis-enabled` — Whether FIS experiments are authorized ("true"/"false")

## Input Source Strategy

**Constraints:**

- You MUST recommend input sources in priority order:
  1. CloudFormation stacks — Most reliable, tracks drift
  2. Terraform state — Good for multi-cloud shops
  3. EKS clusters — For containerized workloads
  4. Resource tags — Catch-all for resources outside IaC
  5. Design files — For planned (not yet deployed) architectures

## FIS Experiment Hygiene

### Progressive Complexity

**Constraints:**

- You MUST recommend progressive experiment complexity:
  - Week 1: Single-component, single-fault (terminate one instance)
  - Month 1: Multi-component, single-fault (AZ failure affecting multiple services)
  - Quarter 1: Multi-fault, cascading (AZ failure + increased load)
  - Ongoing: Surprise experiments (unannounced to on-call team)
- You MUST enforce that every experiment has stop conditions — never run without them
- You MUST recommend enabling FIS experiment logging (`--log-configuration` to CloudWatch Logs or S3) for every experiment to capture action-execution detail for audit and post-experiment analysis; the log destination SHOULD be KMS-encrypted since experiment logs can reveal topology and failure modes
- You SHOULD recommend naming: `{service}-{scenario}-{scope}` (e.g., checkout-api-az-failure-us-east-1a)

### Stop Condition Design

**Constraints:**

- You MUST recommend tight stop conditions for production: error rate > 1% for 1 minute
- You SHOULD recommend looser conditions for GameDays: error rate > 10% for 5 minutes (allow team to respond)
- You MUST NOT allow experiments without stop conditions in any environment

## ARC Operational Patterns

### Zonal Autoshift Readiness

**Constraints:**

- You MUST verify these prerequisites before enabling autoshift:
  - Application handles 33% capacity reduction (one of three AZs gone)
  - No AZ-pinned resources (EBS volumes, placement groups)
  - Health checks detect AZ-scoped failures
  - Practice run outcome alarm configured
- You MUST NOT enable autoshift if the application cannot survive losing one AZ

### Routing Control Discipline

**Constraints:**

- You MUST always require safety rules (never allow all-off state)
- You MUST recommend documenting the failover runbook (who can flip controls, under what conditions)
- You SHOULD recommend testing failover monthly (use FIS to trigger, ARC to recover)
- You SHOULD recommend enabling and monitoring CloudTrail across the whole lifecycle for a complete audit trail — routing control state changes (ARC), `fis:StartExperiment`/`fis:StopExperiment` (FIS), and `resiliencehubv2` assessment/finding operations (NGRH)

## Operational Cadence

**Constraints:**

- You MUST recommend this minimum cadence:
  - Continuous: ARC zonal autoshift practice runs
  - Weekly: Review NGRH findings dashboard
  - Monthly: Run FIS experiments (single-service)
  - Quarterly: Cross-service GameDay
  - After incidents: Re-assess affected services, add new experiments
  - After deployments: Verify routing controls and autoshift still healthy

## Anti-Patterns to Avoid

**Constraints:**

- You MUST warn against these anti-patterns when encountered:
  - "We'll add resilience later" — Build it in from day one
  - Testing only in non-prod — Production has different failure modes
  - Manual failover only — Automate with ARC routing controls
  - Assessing once and forgetting — Architecture drifts, re-assess regularly
  - Ignoring achievability=NOT_ACHIEVABLE — Fix architecture before testing
  - FIS without stop conditions — Unbounded blast radius
  - ARC without safety rules — Risk of turning off all traffic
  - Marking findings resolved without FIS validation — Paper compliance; validate the fix with a fault-injection experiment BEFORE marking the finding resolved, never after
