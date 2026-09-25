# AWS FIS Concepts & Terminology

Authoritative source: <https://docs.aws.amazon.com/fis/> — verify specifics there, as FIS adds
actions, resource types, and scenarios over time.

## Contents

- What AWS FIS is
- Core concepts (official terminology)
- Lifecycle: template → experiment → analysis
- Experiment states
- Supported resource types
- Ways to work with FIS
- Pricing (high level)
- When to recommend FIS (and when not)
- How FIS fits the resilience lifecycle
- Security — see fis-security.md

## What AWS FIS is

AWS Fault Injection Service (AWS FIS) is a managed service for running **fault injection
experiments** on AWS workloads, based on the principles of **chaos engineering**. Experiments
stress an application with disruptive events so you can observe how it responds and then improve
its performance and resilience. FIS provides pre-built fault actions plus the controls and
guardrails (stop conditions, roll-back on threshold breach) needed to run experiments safely —
including in production.

**Important:** FIS carries out real actions on real AWS resources. Always plan first, run in
pre-production before production, and bound the blast radius with a stop condition.

## Core concepts (official terminology — use these exact terms)

| Term | Definition |
|---|---|
| **Experiment** | A single run that tests your theory of how the system behaves under fault. Started from an experiment template. Finishes when all actions complete, a stop condition triggers, an action errors, or you stop it manually. |
| **Experiment template** | The blueprint of an experiment. Contains **actions**, **targets**, **stop conditions**, an IAM **role**, and optional **logging**, **report configuration**, and **experiment options**. |
| **Action** | An activity FIS performs on a resource during an experiment (e.g., stop instances, inject latency). Runs for a set duration or until the experiment stops. Actions run sequentially (via `startAfter`) or in parallel. |
| **Target** | One or more AWS resources an action runs on. Selected by resource ARNs, tags, filters, or parameters, then narrowed by a **selection mode** (`ALL`, `COUNT(n)`, `PERCENT(n)`). |
| **Stop condition** | A guardrail that stops the experiment if a CloudWatch alarm enters ALARM state. Defines the safe boundary (blast radius) of the experiment. |
| **Scenario** | An AWS-owned, pre-built pattern (console-only "scenario library") of targets + actions for a common impairment. Used to create an experiment template. |
| **Experiment report** | An optional PDF summarizing an experiment's actions and (optionally) a CloudWatch dashboard snapshot; delivered to S3. |
| **Orchestrator / target account** | In multi-account experiments, the orchestrator account owns the template/experiment; target accounts hold the affected resources. |

## Lifecycle: template → experiment → analysis

1. **Create an experiment template** (`create-experiment-template`) — define actions, targets,
   stop conditions, role, and optional logging/report/options.
2. **(Recommended) Preview targets** — verify which resources will be affected before running.
3. **Start an experiment** (`start-experiment`) from the template.
4. **Monitor** (`get-experiment`) — track state and resolved targets; view logs.
5. **Experiment finishes** when: all actions complete, a stop condition triggers, an action
   errors, or you `stop-experiment` manually.
6. **Analyze** — review metrics/dashboards, logs, and (if enabled) the experiment report.

You **cannot resume** a stopped or failed experiment, and you cannot rerun a completed one — start
a new experiment from the (optionally updated) template.

## Experiment states

`pending` → `initiating` → `running` → `completed` | `stopping` → `stopped` | `failed`.
(Action states add `cancelled`.) A `failed` experiment usually means target resolution failed or
an action could not run; `stopped` usually means a stop condition fired or a manual stop.

## Supported resource types (target `resourceType`)

FIS adds support for new services over time, so **do not treat any list as exhaustive** — a stale
list will cause you to tell a user a resource type is unsupported when it is. Discover the current
set instead:

```bash
# every action, with the resource type each one targets
aws fis list-actions
aws fis get-action --id <action-id>   # inspect its targets
```

Illustrative examples of the shape these take: `aws:ec2:instance`, `aws:ecs:task`,
`aws:eks:pod`, `aws:rds:cluster`, `aws:lambda:function`, `aws:s3:bucket`. The authoritative list is
in the [FIS documentation](https://docs.aws.amazon.com/fis/latest/userguide/targets.html).

Each action supports exactly one resource type; a target must match the action's resource type.

## Ways to work with FIS

- **Console** — <https://console.aws.amazon.com/fis/> (only place with the scenario library).
- **AWS CLI** — `aws fis ...` ([CLI reference](https://docs.aws.amazon.com/cli/latest/reference/fis/)).
- **AWS CloudFormation** — `AWS::FIS::ExperimentTemplate` (and `AWS::FIS::TargetAccountConfiguration`).
- **AWS SDKs** — language-specific FIS clients.
- **HTTPS API** — [FIS API Reference](https://docs.aws.amazon.com/fis/latest/APIReference/).

## Pricing (high level)

FIS charges are based on action runtime and the number of target accounts; experiment logging
(vended logs to CloudWatch Logs / S3) and experiment reports (S3 storage plus the CloudWatch
`GetMetricWidgetImage`/`GetDashboard` calls) incur additional charges from those services.
Pricing details change — check <https://aws.amazon.com/fis/pricing/> for the current model rather
than quoting rates from here.

## When to recommend FIS (and when not)

**Recommend FIS when the user wants to:**

- Validate that an application actually survives a failure mode (AZ loss, Region isolation, DB
  failover, dependency latency/errors, resource exhaustion) — not just assume it does.
- Prove a Resilience Hub finding's remediation with a reproduced failure before marking it
  resolved (see `aws-resilience-lifecycle`).
- Run game days / continuous resilience testing with bounded, observable, auto-stopping faults.

**Redirect when:**

- They want to **set up** ARC routing controls or zonal shift → `recovery-controller-setup`
  (FIS can *trigger* zonal autoshift via `aws:arc:start-zonal-autoshift`, but does not configure ARC).
- They want the **end-to-end resilience program** (Define → Test → Operate) → `aws-resilience-lifecycle`.
- They want CloudWatch **alarm/dashboard setup** itself → the AWS Observability skill.

## How FIS fits the resilience lifecycle

Define (Resilience Hub) → **Test (FIS)** → Operate (ARC). FIS is the "Test" phase: it reproduces
the failure modes surfaced during Define and validates the operational controls built for
Operate. Stop conditions reuse the same CloudWatch alarms that define steady state.

## Security

FIS performs real, potentially destructive actions on real resources, so treat every experiment as
a privileged operation. Full guidance is in [fis-security.md](fis-security.md):

- The experiment IAM role — trust policy with **confused-deputy** conditions
  (`aws:SourceAccount` + `aws:SourceArn`), and least-privilege permissions scoped by ARN/tag.
- Restricting who may call `fis:StartExperiment`, including the caller's `iam:PassRole` condition.
- Bounding the blast radius — a mandatory CloudWatch-alarm stop condition, narrow targeting
  (`COUNT(1)` / low `PERCENT`), target preview, and pre-production before production.
- Data handling — no PII or secrets in template/experiment string fields, and encryption for
  experiment logs and reports.
