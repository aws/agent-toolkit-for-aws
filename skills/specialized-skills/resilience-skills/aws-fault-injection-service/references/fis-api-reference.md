# AWS FIS API Quick Reference

**Read this BEFORE producing any `aws fis` command.** This is the canonical, deterministic source
of truth for FIS operation names and template parameters. Without explicit guidance, models
substitute plausible-sounding API names that don't exist. Action IDs and resource types still
evolve — verify those with `aws fis list-actions` / `aws fis get-action`.

---

## Contents

- ⚠️ TOP HALLUCINATIONS — DO NOT WRITE THESE
- Canonical `aws fis` operations
- Template top-level fields (create/update)
- Experiment & action states
- Tooling prerequisite — the client must support FIS
- Related service namespaces (do NOT confuse with `aws fis`)

## ⚠️ TOP HALLUCINATIONS — DO NOT WRITE THESE

| ❌ NEVER WRITE | ✅ ALWAYS WRITE |
|---|---|
| `aws fis create-experiment` | `aws fis create-experiment-template` (you create a *template*, then start an experiment from it) |
| `aws fis run-experiment` | `aws fis start-experiment --experiment-template-id EXTxxxx` |
| `aws fis start-experiment --template-id` | `aws fis start-experiment --experiment-template-id` (full flag) |
| `aws fis describe-experiment` | `aws fis get-experiment --id EXPxxxx` |
| `aws fis describe-experiment-template` | `aws fis get-experiment-template --id EXTxxxx` |
| `aws fis list-experiment-templates --template-id` | `aws fis list-experiment-templates` (no id) / `get-experiment-template --id` for one |
| `aws fis cancel-experiment` | `aws fis stop-experiment --id EXPxxxx` |
| `aws fis get-action --action-id` | `aws fis get-action --id <action-id>` |
| `aws fis list-experiment-targets` | `aws fis list-experiment-resolved-targets --id EXPxxxx` |
| `aws:fis:inject-api-unavailable` (no suffix) | `aws:fis:inject-api-unavailable-error` (real action ends in `-error`) |
| `aws:ec2:stop-instance` (singular) | `aws:ec2:stop-instances` (plural) |
| `aws:rds:failover-cluster` | `aws:rds:failover-db-cluster` |
| `aws:eks:delete-pod` | `aws:eks:pod-delete` |
| `--stop-conditions` omitted on create | `stopConditions` is **required**. Always prefer a real `aws:cloudwatch:alarm` stop condition; use `[{"source":"none"}]` **ONLY in a disposable sandbox — never in production** |
| `roleArn` optional | `roleArn` is **required** — FIS assumes it to run actions |

**Memory aids:**

- Templates use **get/create/update/delete-experiment-template**; runs use
  **start/stop/get-experiment** + **list-experiment-resolved-targets**. There is no
  "create-experiment" or "run-experiment".
- All three FIS API-fault actions end in **`-error`**:
  `inject-api-internal-error`, `inject-api-throttle-error`, `inject-api-unavailable-error`.

---

## Canonical `aws fis` operations

### Experiment templates

- `create-experiment-template --cli-input-json file://template.json`
  (or explicit `--description --role-arn --actions --targets --stop-conditions [--log-configuration]
  [--experiment-options] [--experiment-report-configuration] [--tags]`)
- `get-experiment-template --id EXTxxxx`
- `list-experiment-templates`
- `update-experiment-template --id EXTxxxx --cli-input-json file://template-v2.json`
- `delete-experiment-template --id EXTxxxx`

### Experiments (runs)

- `start-experiment --experiment-template-id EXTxxxx [--tags K=V] [--experiment-options ...]`
- `get-experiment --id EXPxxxx`
- `list-experiments`
- `stop-experiment --id EXPxxxx`
- `list-experiment-resolved-targets --id EXPxxxx [--target-name NAME]`

### Actions (discovery — use to VERIFY action IDs)

- `list-actions` — enumerate all available action IDs.
- `get-action --id <action-id>` — parameters, targets, and description for one action.

### Multi-account target account configurations

- `create-target-account-configuration --experiment-template-id EXTxxxx --account-id 222233334444 --role-arn ARN [--description "..."]`
- `get-target-account-configuration --experiment-template-id EXTxxxx --account-id 222233334444`
- `list-target-account-configurations --experiment-template-id EXTxxxx`
- `update-target-account-configuration --experiment-template-id EXTxxxx --account-id 222233334444 ...`
- `delete-target-account-configuration --experiment-template-id EXTxxxx --account-id 222233334444`

### Tagging

Tagging operations take a **resource ARN** (`--resource-arn`), not the `--id` used by the
template/experiment operations. FIS resource ARN formats:

- Experiment template: `arn:aws:fis:<region>:<account-id>:experiment-template/<EXTxxxx>`
- Experiment (run): `arn:aws:fis:<region>:<account-id>:experiment/<EXPxxxx>`

- `list-tags-for-resource --resource-arn ARN`
- `tag-resource --resource-arn ARN --tags K=V`
- `untag-resource --resource-arn ARN --tag-keys K`

---

## Template top-level fields (create/update)

| Field | Required | Notes |
|---|---|---|
| `description` | yes | Free text — no PII/secrets (surfaces in CloudTrail/console). |
| `roleArn` | yes | Role FIS assumes; trust `fis.amazonaws.com` + confused-deputy conditions. |
| `actions` | yes | Map of action name → `{actionId, parameters, targets, startAfter, description}`. |
| `targets` | yes (may be `{}`) | Map of target name → `{resourceType, resourceArns \| resourceTags \| filters \| parameters, selectionMode}`. Field is **required even when no action needs a target** — pass `{}` for target-less actions (e.g. `aws:fis:wait`); omitting it fails create with `targets is required`. |
| `stopConditions` | yes | List of `{source, value}`; `source` = `aws:cloudwatch:alarm` (with alarm ARN in `value`) or `none`. |
| `logConfiguration` | no | `{logSchemaVersion, cloudWatchLogsConfiguration and/or s3Configuration}` — **both destinations may be set together**, unlike the mutually exclusive selectors in `targets` above. `logSchemaVersion` must be `2`. |
| `experimentReportConfiguration` | no | `{outputs.s3Configuration, dataSources.cloudWatchDashboards, preExperimentDuration, postExperimentDuration}`. |
| `experimentOptions` | no | `{accountTargeting: single-account \| multi-account, emptyTargetResolutionMode: fail \| skip, actionsMode: run-all \| skip-all}`. |
| `tags` | no | Map. |

### Selection modes
Random pick from the identified set:

- `ALL` — every identified resource.
- `COUNT(n)` — exactly `n` resources. No rounding.
- `PERCENT(n)` — resolves the percentage to a count and **rounds down**; if it resolves to fewer
  than 1 resource, nothing is selected and the experiment fails.

### `experimentOptions` semantics

- `accountTargeting`: `multi-account` requires ≥1 target account configuration.
- `emptyTargetResolutionMode`: `fail` (default) fails the experiment if any target resolves to
  zero; `skip` continues.
- `actionsMode`: `skip-all` = **target preview** (resolves targets, runs no actions, no report/
  charge for actions).

---

## Experiment & action states

- Experiment: `pending` → `initiating` → `running` → `completed` | `stopping` → `stopped` | `failed`.
- Action: adds `cancelled`.
- `stopped` ≈ stop condition fired or manual stop; `failed` ≈ target resolution or action error.
- Cannot resume `stopped`/`failed` or rerun `completed` — start a new experiment.

---

## Tooling prerequisite — the client must support FIS

The `fis` subcommand requires **AWS CLI v2**. If `aws fis ...` fails with `Invalid choice: fis`,
the client predates FIS support: upgrade to AWS CLI v2, use the **AWS MCP server**, or call FIS
via an SDK that includes the FIS client (e.g. `boto3`) — the operation and parameter names above
are identical across all of them.

---

## Related service namespaces (do NOT confuse with `aws fis`)

- CloudWatch alarms (stop conditions): `aws cloudwatch put-metric-alarm` / `describe-alarms`.
- ARC zonal shift (FIS can *trigger* autoshift via the `aws:arc:start-zonal-autoshift` action;
  ARC *setup* is `aws arc-zonal-shift ...` — see the `recovery-controller-setup` skill).
- Resilience Hub v2 (Define phase): `aws resiliencehubv2 ...` — see `aws-resilience-lifecycle`.

Verify the authoritative FIS command surface with `aws fis help` and each subcommand's `help`
rather than treating this list as permanently fixed.
