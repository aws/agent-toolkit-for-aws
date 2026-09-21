# AWS FIS Experiment Workflow

Follow this procedure to build, run, monitor, and analyze a FIS experiment. Consult
[fis-api-reference.md](fis-api-reference.md) before writing any command and
[fis-actions-reference.md](fis-actions-reference.md) to choose actions/targets.

## Contents

- 0\. Plan first (do not skip)
- 1\. Create (or reuse) the experiment IAM role
- 2\. Author the experiment template
- 3\. Add stop conditions (blast-radius guardrail)
- 4\. Enable experiment logging (strongly recommended)
- 5\. (Optional) Configure an experiment report
- 6\. (Optional) Experiment options & multi-account
- 7\. Preview targets before running (recommended)
- 8\. Start and monitor the experiment
- 9\. Stop manually if needed
- 10\. Analyze results
- 11\. Iterate the template
- CloudFormation option

## 0. Plan first (do not skip)

1. Define **steady state** — the business/technical metrics that mean the app is healthy
   (latency, error rate, successful transactions). These become your stop-condition alarm(s).
2. Form a **hypothesis** — "when the fault is injected, the system stays within steady state
   because of a specific control."
3. Decide **blast radius** — narrowest useful target (`COUNT(1)` / low `PERCENT`), pre-production
   first. Only widen after it passes.
4. Confirm this is authorized — production fault injection needs change-management approval.

## 1. Create (or reuse) the experiment IAM role

The template needs a `roleArn` FIS assumes to perform actions. Create it with a trust policy for
`fis.amazonaws.com` and confused-deputy conditions, plus least-privilege permissions for the
target service APIs (and SSM / logs / report S3+CloudWatch if used). See
[fis-security.md](fis-security.md) for the exact trust policy and permission examples.

## 2. Author the experiment template

An experiment template combines: `description`, `roleArn`, `actions`, `targets`,
`stopConditions`, optional `logConfiguration`, optional `experimentReportConfiguration`, optional
`experimentOptions`, and `tags`.

### Option A — from a scenario (recommended when one fits)

Scenarios are console-only. In the FIS console: **Scenario library** → pick a scenario →
**Create template with scenario** → fill missing parameters, choose the service-access role, add
stop conditions and logging → **Create experiment template**. To automate later, export the
created template's JSON. (See scenario list in [fis-actions-reference.md](fis-actions-reference.md).)

### Option B — hand-authored template (CLI/JSON)

Build a JSON document and pass it to `create-experiment-template`. Minimal shape:

```json
{
  "description": "Reboot one prod EC2 instance; stop if error rate alarms",
  "roleArn": "arn:aws:iam::123456789012:role/FISExperimentRole",
  "actions": {
    "RebootInstance": {
      "actionId": "aws:ec2:reboot-instances",
      "targets": { "Instances": "oneProdInstance" }
    }
  },
  "targets": {
    "oneProdInstance": {
      "resourceType": "aws:ec2:instance",
      "resourceTags": { "env": "prod" },
      "selectionMode": "COUNT(1)"
    }
  },
  "stopConditions": [
    { "source": "aws:cloudwatch:alarm",
      "value": "arn:aws:cloudwatch:us-east-1:123456789012:alarm:HighErrorRate" }
  ],
  "tags": { "Name": "reboot-one-prod-instance", "team": "checkout" }
}
```

Create it:

```bash
aws fis create-experiment-template --cli-input-json file://template.json
```

> `stopConditions` is **required** in the template. Use `[{"source":"none"}]` only when you
> genuinely have no alarm — strongly discouraged for anything beyond a sandbox. Prefer a real
> `aws:cloudwatch:alarm` on your steady-state metric.

### Sequencing actions

Actions run in parallel by default. To sequence, set `startAfter` to the names of prerequisite
actions. Use an `aws:fis:wait` action to insert a controlled pause (e.g., hold a fault for N
minutes before a follow-on action or before letting steady state recover).

## 3. Add stop conditions (blast-radius guardrail)

A stop condition stops the experiment when a CloudWatch alarm enters ALARM. Base the alarm on the
steady-state metric from step 0.

```json
"stopConditions": [
  { "source": "aws:cloudwatch:alarm",
    "value": "arn:aws:cloudwatch:us-east-1:123456789012:alarm:P99LatencyHigh" }
]
```

You can specify multiple alarms (subject to the account quota). Alarm/dashboard creation itself
belongs to the AWS Observability skill.

## 4. Enable experiment logging (strongly recommended)

Capture per-experiment records (`experiment-start`, `target-resolution-*`, `action-start/end/
error`, `experiment-end`) to CloudWatch Logs and/or S3. `logSchemaVersion` must be `2`.

FIS does not require logging, but without it there is no experiment-level audit trail beyond
CloudTrail, which makes post-incident troubleshooting very difficult. Enable it for anything
beyond a throwaway sandbox.

```json
"logConfiguration": {
  "logSchemaVersion": 2,
  "cloudWatchLogsConfiguration": {
    "logGroupArn": "arn:aws:logs:us-east-1:123456789012:log-group:/aws/fis/experiments:*"
  },
  "s3Configuration": { "bucketName": "my-fis-logs", "prefix": "experiments" }
}
```

Grant FIS the vended-logs delivery permissions for each destination. First run to a new
destination is delayed ~15 s to configure delivery. Logging is disabled by default; enable via
`create-experiment-template` or add later with `update-experiment-template`. Use logs (not the
report) to troubleshoot failed experiments.

> **Encrypt both destinations.** Experiment logs reveal resilience posture and architectural
> weaknesses. Encrypt the CloudWatch Logs log group with a KMS key (`kmsKeyId` at creation, or
> `aws logs associate-kms-key`), and enable SSE-KMS on the S3 bucket with a bucket policy that
> denies non-TLS requests (`aws:SecureTransport`). See
> [fis-security.md](fis-security.md) — Data handling.

## 5. (Optional) Configure an experiment report

Generate a PDF summarizing the experiment plus a CloudWatch dashboard snapshot, delivered to S3.

```json
"experimentReportConfiguration": {
  "outputs": { "s3Configuration": { "bucketName": "my-fis-reports", "prefix": "checkout" } },
  "dataSources": {
    "cloudWatchDashboards": [
      { "dashboardIdentifier": "arn:aws:cloudwatch::123456789012:dashboard/CheckoutHealth" }
    ]
  },
  "preExperimentDuration": "PT20M",
  "postExperimentDuration": "PT20M"
}
```

- Reports are NOT generated for cancelled runs or target-preview (`actionsMode: skip-all`) runs.
  `preExperimentDuration` and `postExperimentDuration` are ISO 8601 and default to 20 min each;
  both are capped, as is the number of dashboards per report. Check the current values in the
  [FIS quotas documentation](https://docs.aws.amazon.com/fis/latest/userguide/fis-quotas.html)
  rather than assuming a fixed limit.
- **Encrypt the report bucket.** Reports are PDFs summarizing resilience posture — enable SSE-KMS
  and enforce TLS with a bucket policy condition on `aws:SecureTransport`, the same way as the log
  destinations above.
- Report role permissions: `cloudwatch:GetDashboard`, `cloudwatch:GetMetricWidgetImage`,
  `s3:GetObject`, `s3:PutObject` (+ `kms:GenerateDataKey`, `kms:Decrypt` for CMK-encrypted
  buckets). Use the report only for successfully completed runs — troubleshoot failures with logs.

## 6. (Optional) Experiment options & multi-account

`experimentOptions` on the template controls:

- `accountTargeting`: `single-account` (default) or `multi-account`.
- `emptyTargetResolutionMode`: `fail` (default) or `skip` (don't fail when a target resolves to
  zero resources).
- `actionsMode`: `run-all` (normal) or `skip-all` (target preview — resolves targets without
  running actions).

**Multi-account experiments** run from an *orchestrator account* against resources in *target
accounts* (same Region). Set `accountTargeting: multi-account`, then add a **target account
configuration** per account (account ID + IAM role FIS assumes there + optional description):

```bash
aws fis create-target-account-configuration \
  --experiment-template-id EXTxxxx --account-id 222233334444 \
  --role-arn arn:aws:iam::222233334444:role/FISTargetAccountRole \
  --description "checkout target account"
```

Target accounts are notified via their AWS Health dashboards. Prefer **consistent resource tags**
across accounts and target AZs by **AZ ID**. Per-account action quotas apply.

## 7. Preview targets before running (recommended)

Generate a target preview (run with `actionsMode: skip-all`, or use the console/`get-experiment`
resolved-targets view) to confirm the exact resources that will be affected. This is the cheapest
way to catch an over-broad tag/filter before a real fault.

## 8. Start and monitor the experiment

```bash
# Start
aws fis start-experiment --experiment-template-id EXTxxxx \
  --tags Name=game-day-checkout

# Watch state
aws fis get-experiment --id EXPxxxx --query 'experiment.state'

# List which resources FIS actually selected
aws fis list-experiment-resolved-targets --id EXPxxxx
```

States: `pending → initiating → running → completed | stopping → stopped | failed`. Watch your
steady-state dashboard live. A stopped/failed experiment cannot be resumed.

## 9. Stop manually if needed

```bash
aws fis stop-experiment --id EXPxxxx
```

Use this if you observe unacceptable impact the stop-condition alarm didn't catch. Afterward,
consider tightening the alarm so the guardrail catches it automatically next time.

## 10. Analyze results

1. Compare steady-state metrics before/during/after; confirm the hypothesis and measure actual
   recovery time (RTO) vs. objective.
2. Read experiment logs for the action/target timeline and any `action-error` reasons.
3. If enabled, retrieve the S3 experiment report as evidence of the test.
4. If validating a Resilience Hub finding, only now mark it resolved (see `aws-resilience-lifecycle`).
5. Iterate: widen blast radius, add multi-fault scenarios, or promote from pre-prod to prod under
   change management. If the experiment surfaced a defect, fix it and re-run to confirm.

## 11. Iterate the template

```bash
aws fis update-experiment-template --id EXTxxxx --cli-input-json file://template-v2.json
aws fis delete-experiment-template --id EXTxxxx   # when retiring
```

## CloudFormation option

Model the template as `AWS::FIS::ExperimentTemplate` (and
`AWS::FIS::TargetAccountConfiguration` for multi-account) so experiments are version-controlled
and reviewed like other infrastructure. The property shape mirrors the CLI/JSON above.
