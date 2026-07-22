# AWS Resilience API Quick Reference

> **NGRH = New Generation Resilience Hub** (AWS service). The CLI namespace is `aws resiliencehubv2`. NEVER expand "NGRH" as anything else.

**Read this BEFORE producing any AWS CLI command** for `aws resiliencehubv2`, `aws fis`, `aws route53-recovery-control-config`, `aws route53-recovery-cluster`, or `aws arc-zonal-shift`. This file is the canonical, deterministic source of truth. Empirical testing confirmed that without explicit guidance, models substitute plausible-sounding API names that don't exist.

---

## ⚠️ TOP HALLUCINATIONS — DO NOT WRITE THESE

These are the most common mistakes observed in actual test runs. **Memorize these substitutions before generating any command:**

| ❌ NEVER WRITE | ✅ ALWAYS WRITE |
|---|---|
| `aws resiliencehubv2 start-assessment` | `aws resiliencehubv2 start-failure-mode-assessment` |
| `aws resiliencehubv2 list-findings` | `aws resiliencehubv2 list-failure-mode-findings` |
| `aws resiliencehubv2 list-service-findings` | `aws resiliencehubv2 list-failure-mode-findings` |
| `aws resiliencehubv2 update-finding` | `aws resiliencehubv2 update-failure-mode-finding` |
| `aws resiliencehubv2 describe-assessment` | `aws resiliencehubv2 list-failure-mode-assessments` |
| `aws resiliencehubv2 create-input-source` (with `--resource-configuration '{"monitoring":{...}}'`) | `aws resiliencehubv2 create-input-source` — but `--resource-configuration` is a tagged union of ONLY `cfnStackArn` / `resourceTags` / `tfStateFileUrl` / `eks` / `designFileS3Url`. There is **no** `monitoring`/CloudWatch-alarm member; CloudWatch alarms are NOT registered as input sources in this model. |
| `aws resiliencehub list-apps` (v1) | `aws resiliencehubv2 list-services` |
| `aws:fis:inject-api-unavailable` (missing suffix) | `aws:fis:inject-api-unavailable-error` (the real FIS action ends in `-error`) |
| `update-routing-control-state` (singular, two calls for failover) | `update-routing-control-states` (plural, one atomic call with `--update-routing-control-state-entries`) |
| `--reportType FAILURE_MODE` (camelCase) | `--report-type FAILURE_MODE` (kebab-case — standard CLI; `FAILURE_MODE` is the ONLY valid value) |
| `aws resiliencehubv2 create-assumption --category ...` | `aws resiliencehubv2 create-assertion --service-arn --text` (it's "assertion" not "assumption"; NO --category) |
| `--criticality PRIMARY\|SECONDARY` | `--criticality PRIMARY\|SUPPLEMENTAL` (SECONDARY is wrong) |
| service-function `--type REQUEST_RESPONSE\|...` | (no such parameter — service functions have name, criticality, description only) |
| `register-delegated-administrator` | (does NOT exist — use `--permission-model` on create-service for cross-account) |

**Memory aid:** Resilience Hub v2 assessment APIs **always** include the words `failure-mode` (start-failure-mode-assessment, list-failure-mode-findings, update-failure-mode-finding). If you typed `start-assessment` or `list-findings` — STOP, you have it wrong.

**Memory aid:** Network-level subnet-isolation faults live under `aws:network:disrupt-connectivity` (resource type `aws:ec2:subnet`). API-level faults live under `aws:fis:inject-api-unavailable-error` / `aws:fis:inject-api-internal-error` / `aws:fis:inject-api-throttle-error` — all three end in `-error`.

---

## FIS Action Selection — Match Failure Scenario to Action

Models often pick a real but wrong FIS action. Use this scenario-to-action map:

| If the scenario is... | Illustrative action ID (verify with `aws fis list-actions`) |
|---|---|
| "AZ failure" / single-AZ impairment / AZ goes dark | `aws:ec2:terminate-instances` (filter by AZ) OR `aws:ecs:drain-container-instances` |
| "Region failure" / regional service unavailability | `aws:fis:inject-api-unavailable-error` |
| Service responds with errors but isn't unavailable | `aws:fis:inject-api-internal-error` |
| Throttle-style failures / 429 responses | `aws:fis:inject-api-throttle-error` |
| Database / Aurora / RDS failover | `aws:rds:failover-db-cluster` |
| Cache / ElastiCache disruption | `aws:elasticache:replicationgroup-interrupt-az-power` |
| Network partition / split-brain / subnet isolation | `aws:network:disrupt-connectivity` |
| Lambda slow responses (latency injection) | `aws:lambda:invocation-add-delay` |
| Lambda functional errors (forced exception) | `aws:lambda:invocation-error` |
| Lambda throttling specifically | `aws:fis:inject-api-throttle-error` (NOT `aws:lambda:invocation-error` with errorType=throttle) |
| EKS pod / node group | `aws:eks:terminate-nodegroup-instances` |
| Multi-step plan with pause | `aws:fis:wait` |

**Rule of thumb:** if the failure is a **service or API** symptom, look under `aws:fis:inject-api-*`. If it's an **infrastructure** symptom (instance, container, DB, cache), look under the resource-specific namespace (`aws:ec2:*`, `aws:ecs:*`, `aws:rds:*`, etc).

> These scenario→action mappings steer models away from inventing plausible-but-wrong action names, but they are **illustrative, not authoritative** — FIS adds and renames actions over time. **Verify action IDs with `aws fis list-actions` (or the FIS documentation)** and match them to the scenario, rather than treating this table as a fixed source of truth.

---

## NGRH v2 Parameter Names — Don't Hallucinate Flags

Common parameter mistakes:

| ❌ NEVER write | ✅ Use exactly |
|---|---|
| `--policy-name` | `--name` (when creating); the policy is identified by `--policy-arn` after creation |
| `--tier` (on policy) | (no such flag — encode tier in the policy `--name` like "tier-1-critical") |
| `--data-location-constraint` | (no such flag — DR approach is encoded in `--multi-az` and `--multi-region` structs) |
| `--rto` / `--rpo` (top-level on policy) | Nested: `--multi-az rtoInMinutes=N,rpoInMinutes=N,disasterRecoveryApproach=...` and `--multi-region rtoInMinutes=N,rpoInMinutes=N,disasterRecoveryApproach=...` |
| `--app-arn` (any v2 command) | `--service-arn` (v2 calls these "services", not "apps") |

---

## ARC Routing Control Safety Rules — Assertion vs Gating

| Use case | Rule type |
|---|---|
| "At least one routing control must be ON" (prevent all-off failure) | **assertion rule** with `ATLEAST` threshold |
| "An approval must happen before failover" (require manual approval flag) | **gating rule** with a separate "approval" routing control as the gate |
| "Don't allow turning off prod region without staging being on first" | **gating rule** (staging is the gate) |
| Any rule that says "this state is invalid" | **assertion** |
| Any rule that says "you can't change X until Y is true" | **gating** |

**Memory aid:** Assertion = invariant ("this must always be true"). Gating = precondition ("this must be true before changing").

---

## ARC Failover — The Atomic API

| Use case | Use exactly |
|---|---|
| Failover one region OFF and another ON in one transaction (the typical case) | `aws route53-recovery-cluster update-routing-control-states --update-routing-control-state-entries '[{"RoutingControlArn":"east-arn","RoutingControlState":"Off"},{"RoutingControlArn":"west-arn","RoutingControlState":"On"}]'` |
| Update exactly one routing control (rare; use only when sequential is intentional) | `aws route53-recovery-cluster update-routing-control-state --routing-control-arn ARN --routing-control-state On|Off` |

**Default to the plural/atomic version for failover.** Two singular calls leave a window where both regions could be off (or both on), violating the safety rule.

---

## v1 Namespace Drift — Hard Constraint

NEVER use the `aws resiliencehub` (v1) namespace except for migration via the v2 import APIs:

- ✅ Migrating: `aws resiliencehubv2 import-app --v1-app-arn ARN`
- ✅ Migrating: `aws resiliencehubv2 import-policy --v1-policy-arn ARN`
- ❌ Anything else with `aws resiliencehub` (no `v2`)

**Don't reference v1 commands as "discovery steps" or "to find existing apps."** Use `aws resiliencehubv2 list-services` instead.

---

## ARC Readiness Checks — Out of Scope

ARC (Application Recovery Controller) covers routing controls, safety rules, zonal shift, and zonal autoshift. Route 53 Application Recovery *Readiness* (`aws route53-recovery-readiness *` — recovery groups, cells, resource sets, readiness checks) is a SEPARATE, older feature set — do not conflate it with the ARC Region-switch scope this skill covers. Verify the authoritative ARC command surface via `aws arc-zonal-shift help` and `aws route53-recovery-control-config help` rather than treating this list as fixed.

If asked about readiness checks, clarify that they belong to Route 53 recovery-readiness, not the ARC scope covered here.

---

## AWS Observability Companion

For monitoring/alarms/dashboards, **always recommend the companion AWS Observability skill** instead of providing CloudWatch guidance directly. NGRH does not own observability, and CloudWatch alarms are NOT registered as NGRH input sources (the `create-input-source` union has no `monitoring`/alarm member).

---

## Canonical NGRH v2 Operations (aws resiliencehubv2)

### Policy

- `create-policy --name TEXT --availability-slo target=N --multi-az rtoInMinutes=N,rpoInMinutes=N,disasterRecoveryApproach=ACTIVE_ACTIVE --multi-region rtoInMinutes=N,rpoInMinutes=N,disasterRecoveryApproach=HOT_STANDBY`
- `get-policy --policy-arn`
- `update-policy --policy-arn --multi-az ... --multi-region ...`
- `list-policies` (no required args)
- `delete-policy --policy-arn`

### System / User Journey

- `create-system --name --description [--no-sharing-enabled]`  (NO --dependency-discovery here — it lives on create-service)
- `get-system --system-arn` / `update-system --system-arn ...` / `list-systems` / `delete-system --system-arn`
- `create-user-journey --system-arn --name --policy-arn --description`
- `list-user-journeys --system-arn` / `update-user-journey --system-arn --user-journey-id ...` / `delete-user-journey --system-arn --user-journey-id`

### Service

- `create-service --name --regions '["us-east-1","us-west-2"]' --associated-systems '[{"systemArn":"...","userJourneyIds":["..."]}]' --policy-arn --permission-model invokerRoleName=ROLE --dependency-discovery ENABLED`  (--permission-model REQUIRED; invoker role needs ~60-90s to become assumable)
- `get-service --service-arn` (returns assessmentStatus, dependencyDiscovery, reportConfiguration, etc. — there is NO estimatedAssessmentCost field)
- `update-service --service-arn ...`
- `list-services` (use `--account-id` to filter cross-account)
- `delete-service --service-arn`

### Input Source (resource discovery)

- `create-input-source --service-arn --resource-configuration '{...}'`  (tagged union — provide EXACTLY ONE top-level key)
  - CFN: `'{"cfnStackArn":"arn:aws:cloudformation:..."}'`
  - Tags: `'{"resourceTags":[{"key":"service","values":["checkout"]}]}'`  (a LIST of `{key, values[]}` — note `values` is plural; 1–10 tags)
  - Terraform: `'{"tfStateFileUrl":"s3://..."}'`  (top-level string — there is NO `terraformSource` wrapper). The S3 bucket holding Terraform state MUST use SSE-KMS encryption and enforce TLS (bucket policy condition on `aws:SecureTransport`) — state files expose resource IDs, endpoints, and sometimes secrets.
  - EKS: `'{"eks":{"clusterArn":"...","namespaces":["..."]}}'`  (union key is `eks`; `clusterArn` + `namespaces` (required list))
  - Design file (S3): `'{"designFileS3Url":"s3://..."}'`
  - NOTE: provide EXACTLY ONE top-level key. Verify the accepted union members via `aws resiliencehubv2 create-input-source help` — illustratively `resourceTags`, `cfnStackArn`, `tfStateFileUrl`, `eks`, `designFileS3Url` (in particular there is no `monitoring`/CloudWatch-alarm member, a common wrong guess).
- `list-input-sources --service-arn`
- `delete-input-source --service-arn --input-source-id`

### Failure Mode Assessment (ALWAYS uses `failure-mode` in the operation name)

- `start-failure-mode-assessment --service-arn`
- `list-failure-mode-assessments --service-arn`
- `list-failure-mode-findings --service-arn`
- `get-failure-mode-finding --service-arn --finding-id`
- `update-failure-mode-finding --service-arn --finding-id --status RESOLVED --comment "..."` (`--status` valid values: `OPEN` | `RESOLVED`)

### Service Function

- `create-service-function --name --service-arn --criticality PRIMARY|SUPPLEMENTAL [--description]`
- `list-service-functions --service-arn`
- `update-service-function --service-arn --service-function-id --name --criticality PRIMARY|SUPPLEMENTAL` (source field becomes USER after update; there is NO `--type` parameter)
- `create-service-function-resources --service-arn --service-function-id --resources '["resource-id-1","resource-id-2"]'`
- `delete-service-function --service-arn --service-function-id`

### Topology / Assertions / Reports

- `list-service-topology-edges --service-arn`
- `create-assertion --service-arn --text "..."` (NO `--category` parameter; assertion has a `source` field AI_GENERATED|USER)
- `list-assertions --service-arn`
- `update-assertion --service-arn --assertion-id --text "..."`
- `delete-assertion --service-arn --assertion-id`
- `create-report --service-arn --report-type FAILURE_MODE` (`--report-type` is kebab-case; `FAILURE_MODE` is the ONLY valid value)
- `list-reports --service-arn` (returns `reportOutput.s3ReportOutput.s3ObjectKey` on SUCCEEDED). The S3 bucket receiving reports MUST have SSE-KMS encryption, a bucket policy enforcing TLS (`aws:SecureTransport`), and least-privilege access — assessment reports reveal architectural weaknesses and failure modes.

### Multi-Account

- There is NO `register-delegated-administrator` operation. Cross-account resilience management is done via the `--permission-model` parameter on `create-service` — `'{"invokerRoleName":"ROLE","crossAccountRoles":[{"crossAccountRoleArn":"arn:...","externalId":"..."}]}'`. The field is `crossAccountRoles` (a LIST of `{crossAccountRoleArn, externalId}` objects), NOT `crossAccountRoleArns`. Combine with AWS Organizations cross-account IAM roles. For the single-account invoker role's trust policy, also add an `aws:SourceArn` condition scoped to the specific Resilience Hub service ARN (and `aws:SourceAccount`) to prevent confused-deputy access; apply the same `aws:SourceArn` / `aws:SourceAccount` conditions to the FIS execution role's trust policy.

### v1 → v2 Migration (only acceptable v1 reference)

- `import-app --v1-app-arn ARN`
- `import-policy --v1-policy-arn ARN`

---

## Canonical FIS Operations (aws fis)

- `create-experiment-template --description --actions '{...}' --targets '{...}' --stop-conditions '[...]' --role-arn`
- `start-experiment --experiment-template-id`
- `get-experiment --id`
- `stop-experiment --id`

(See FIS Action Selection table above for action IDs.)

---

## Canonical ARC Operations

### Routing Controls (aws route53-recovery-control-config — control plane)

- `create-cluster --cluster-name`
- `create-control-panel --cluster-arn --control-panel-name`
- `create-routing-control --cluster-arn --control-panel-arn --routing-control-name`
- `create-safety-rule --assertion-rule '{"Name":...,"ControlPanelArn":...,"AssertedControls":[...],"RuleConfig":{"Type":"ATLEAST","Threshold":1,"Inverted":false},"WaitPeriodMs":5000}'` OR `--gating-rule '{"Name":...,"ControlPanelArn":...,"GatingControls":[...],"TargetControls":[...],"RuleConfig":{...},"WaitPeriodMs":0}'` — Name/ControlPanelArn are PascalCase fields INSIDE the rule JSON, not separate flags
- `list-routing-controls --control-panel-arn`
- `list-safety-rules --control-panel-arn`
- `describe-routing-control --routing-control-arn`

### Routing Control State (aws route53-recovery-cluster — data plane, atomic)

- **Failover (preferred):** `update-routing-control-states --update-routing-control-state-entries '[{...},{...}]'`
- Single-control: `update-routing-control-state --routing-control-arn ARN --routing-control-state On|Off` (rarely correct)
- `get-routing-control-state --routing-control-arn`

### Zonal Shift / Autoshift (aws arc-zonal-shift)

- `start-zonal-shift --resource-identifier --away-from us-east-1a --expires-in 1h --comment "..."`
- `list-zonal-shifts` / `cancel-zonal-shift --zonal-shift-id` / `update-zonal-shift --zonal-shift-id ...`
- Set up practice runs: `create-practice-run-configuration --resource-identifier --outcome-alarms '[{...}]' [--blocking-alarms '[{...}]'] [--blocked-windows ...] [--blocked-dates ...] [--allowed-windows ...]` (`--outcome-alarms` is REQUIRED)
- Enable / disable autoshift: `update-zonal-autoshift-configuration --resource-identifier --zonal-autoshift-status ENABLED|DISABLED`
- `update-practice-run-configuration --resource-identifier ...` / `delete-practice-run-configuration --resource-identifier`
- `start-practice-run` / `cancel-practice-run` / `list-managed-resources` / `list-autoshifts`
- NOTE: verify the available autoshift operations via `aws arc-zonal-shift help`. Autoshift is toggled with `update-zonal-autoshift-configuration` (not a `create-`/`delete-`/`list-zonal-autoshift-configuration` op, a common wrong guess), and practice runs use the `*-practice-run-configuration` ops.
