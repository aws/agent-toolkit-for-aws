# Resilience Lifecycle: Define → Test → Operate

## Overview

This SOP guides the integrated use of all three AWS resilience services (Resilience Hub v2, FIS, ARC) to achieve proven, operational resilience through a continuous Define → Test → Operate loop.

## Parameters

**service_name** (required): Name of the service going through the lifecycle
**service_arn** (optional): Existing service ARN if already onboarded to Resilience Hub
**lifecycle_phase** (optional, default: "all"): Which phase to execute — define, test, operate, or all
**aws_region** (optional, default: "us-east-1"): Primary AWS region

## Steps

### 1. Verify Dependencies

Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify that either the AWS CLI or the AWS MCP server's `call_aws` tool is available (e.g., check the CLI is on PATH with `command -v aws`)
- You MUST NOT call AWS service APIs during verification — checking tool presence (such as `command -v aws`) is fine; do not make any AWS service calls
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You SHOULD recommend the user authenticate with short-lived IAM role credentials (IAM role assumption, AWS SSO, an instance profile, or `aws sts assume-role`) rather than long-lived IAM user access keys, since this lifecycle performs privileged and potentially destructive operations.
- You MUST honor the `lifecycle_phase` parameter and execute ONLY the selected phase(s): "define" → Step 2 only; "test" → Step 3 only; "operate" → Step 4 only; "all" (default) → Steps 2–5 in order
- You MUST skip any phase not selected by `lifecycle_phase`

### 2. Phase 1 — DEFINE (Resilience Hub)

Establish resilience targets and identify gaps through assessment.

**Constraints:**

- You MUST guide the user through: create policy → create system → create user journey → create service → add input sources → run assessment
- You MUST delegate execution of each step's mutating AWS CLI commands to the **resilience-hub-getting-started** skill, which owns those commands and their validation — this lifecycle skill sequences and gates the phases; it does not execute the Define-phase mutations itself
- You MUST triage findings by action required:
  - Architecture gap (NOT_ACHIEVABLE) → Fix infrastructure first
  - Untested failure mode → Design FIS experiment (Phase 2)
  - No recovery mechanism → Set up ARC controls (Phase 3)
  - Missing observability → Add CloudWatch alarms
- You MUST NOT skip directly to testing if findings show NOT_ACHIEVABLE — architecture must be fixed first

### 3. Phase 2 — TEST (Fault Injection Service)

Validate resilience through controlled fault-injection experiments.

**Constraints:**

- You MUST map each "untested" finding from Phase 1 to an FIS experiment
- You MUST guide the user through: identify scenario → define stop conditions → scope blast radius → create template → execute → analyze results
- You MUST recommend scoping the FIS execution role to least privilege — only the specific actions and resource ARNs each experiment needs (e.g. `ec2:TerminateInstances` limited to tagged resources), never broad `ec2:*` or `*`, since FIS execution roles are high-privilege (they terminate instances, disrupt networking, etc.).
- You MUST delegate execution of each step's mutating AWS CLI commands to the **fault-injection-experiment-design** skill, which owns those commands and their validation — this lifecycle skill sequences and gates the phases; it does not create or start experiments itself
- You MUST enforce the pre-experiment checklist:
  - Stop condition alarms are in OK state
  - Rollback plan documented
  - Team notified (or scheduled GameDay)
  - Blast radius limited (start non-prod, then canary %)
- You MUST present the fully-rendered experiment template (actions, targets, stop conditions, role ARN) to the user and receive explicit confirmation BEFORE calling `aws fis start-experiment` — never auto-start a fault-injection experiment, since it is destructive (terminates instances, disrupts networking). This mirrors the confirm-before-proceeding gate in Step 1.
- You MUST gate the finding update on validation — mark a finding RESOLVED **only after** the experiment confirms recovery within objectives. The actual `update-failure-mode-finding` call is executed by the **resilience-hub-getting-started** skill (which owns `resiliencehubv2` commands); this skill supplies the gate and the evidence comment, e.g. `--status RESOLVED --comment "Validated via FIS experiment {experiment_id}. RTO: {actual_rto}s (target: {target_rto}s)"`

### 4. Phase 3 — OPERATE (Application Recovery Controller)

Configure operational recovery mechanisms for production use.

**Constraints:**

- You MUST guide the user through: create routing controls → add safety rules → test failover → configure zonal autoshift
- You MUST delegate execution of each step's mutating AWS CLI commands to the **recovery-controller-setup** skill, which owns those commands and their validation — this lifecycle skill sequences and gates the phases; it does not create routing controls or configure autoshift itself
- You MUST NOT create routing controls without safety rules
- You MUST verify the application can handle N-1 AZ capacity before enabling zonal autoshift
- You MUST connect ARC back to NGRH findings:
  - "No cross-region failover mechanism" → Set up routing controls + safety rules
  - "Single-AZ dependency" → Enable zonal autoshift
  - "Recovery not validated" → Run FIS experiment, then enable ARC

### 5. Phase 4 — CONTINUOUS (Loop Back)

Establish ongoing resilience validation cadence.

**Constraints:**

- You MUST recommend the following cadence:
  - After architecture changes → Re-run NGRH assessment
  - After new deployments → Verify input sources capture new resources
  - Monthly → Run FIS experiments (single-service)
  - Quarterly → Cross-service GameDay
  - After incidents → Re-assess affected services, add new experiments
- You MUST inform the user that zonal autoshift practice runs provide continuous validation automatically
- You MUST recommend monitoring routing control state changes via CloudTrail
- You SHOULD suggest expanding experiments progressively: single-fault → multi-fault → cascading → surprise (unannounced to on-call)

## Examples

> **Note:** the CLI commands below illustrate what the delegated companion skills
> (`resilience-hub-getting-started`, `fault-injection-experiment-design`, `recovery-controller-setup`)
> execute on behalf of this lifecycle skill. This skill orchestrates the phases and gates
> progression — it does **not** run these commands directly.

```bash
# Phase 1: Define
aws resiliencehubv2 create-policy --name "tier-1" --availability-slo target=99.99 \
  --multi-az rtoInMinutes=5,rpoInMinutes=1,disasterRecoveryApproach=ACTIVE_ACTIVE \
  --multi-region rtoInMinutes=30,rpoInMinutes=5,disasterRecoveryApproach=HOT_STANDBY
aws resiliencehubv2 start-failure-mode-assessment --service-arn {service_arn}

# Phase 2: Test (from NGRH finding "AZ failure not validated")
aws fis create-experiment-template --description "Validate checkout-api survives us-east-1a AZ failure" \
  --actions '{"terminate-checkout":{"actionId":"aws:ec2:terminate-instances","targets":{"Instances":"checkout-instances"}}}' \
  --targets '{"checkout-instances":{"resourceType":"aws:ec2:instance","selectionMode":"ALL","resourceTags":{"resilience:service":["checkout-api"]},"filters":[{"path":"Placement.AvailabilityZone","values":["us-east-1a"]}]}}' \
  --stop-conditions '[{"source":"aws:cloudwatch:alarm","value":"arn:aws:cloudwatch:..."}]' \
  --log-configuration '{"cloudWatchLogsConfiguration":{"logGroupArn":"arn:aws:logs:us-east-1:123456789012:log-group:/fis/checkout-api:*"},"logSchemaVersion":2}' \
  --role-arn arn:aws:iam::123456789012:role/FISExperimentRole
# Enable experiment logging (above): the CloudWatch Logs group (or S3 bucket) receiving experiment
# logs SHOULD be KMS-encrypted (logs:AssociateKmsKey / SSE-KMS) — experiment logs can reveal
# infrastructure topology and failure modes.
# ⚠️ Present the fully-rendered template to the user and get explicit confirmation BEFORE the next line (see Step 3) — never auto-start a destructive experiment
aws fis start-experiment --experiment-template-id EXT123abc

# Phase 3: Operate
aws route53-recovery-control-config create-routing-control --cluster-arn {cluster_arn} --control-panel-arn {control_panel_arn} --routing-control-name checkout-us-east-1
aws arc-zonal-shift create-practice-run-configuration --resource-identifier {alb_arn} \
  --outcome-alarms '[{"alarmIdentifier":"arn:aws:cloudwatch:...","type":"CLOUDWATCH"}]'
aws arc-zonal-shift update-zonal-autoshift-configuration --resource-identifier {alb_arn} --zonal-autoshift-status ENABLED

# Phase 4: Update finding after validation
aws resiliencehubv2 update-failure-mode-finding --service-arn {service_arn} --finding-id {id} --status RESOLVED \
  --comment "Validated via FIS EXT123abc. RTO: 45s (target: 300s)"
```

## Troubleshooting

**User wants to skip Phase 1 and go straight to testing**
Advise against this — without NGRH assessment, they don't know which failure modes to test. Testing without targets means no way to measure success.

**Findings show NOT_ACHIEVABLE but user wants to test anyway**
Explain that testing will confirm the failure but won't fix it. Architecture changes are needed first. Testing validates that a fix works, not that a broken architecture is broken.

**User has existing FIS experiments but no NGRH**
Start with Phase 1 to get a complete picture. Existing experiments can be mapped to findings after assessment, and gaps in coverage will be identified.
