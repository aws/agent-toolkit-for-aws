# Fast Deployments: Hotswap and Express Mode

## Table of Contents

- [Overview](#overview)
- [Choosing a Deployment Mode](#choosing-a-deployment-mode)
- [Hotswap](#hotswap)
  - [`--hotswap` vs `--hotswap-fallback`](#--hotswap-vs---hotswap-fallback)
  - [Hotswappable Resource Types](#hotswappable-resource-types)
  - [cdk watch Defaults to Hotswap](#cdk-watch-defaults-to-hotswap)
  - [Hotswap Drift and Recovery](#hotswap-drift-and-recovery)
- [Express Mode](#express-mode)
  - [Supported Commands](#supported-commands)
  - [Rollback Behavior](#rollback-behavior)
  - [Recovering a Failed Express Deployment](#recovering-a-failed-express-deployment)
- [Production Prohibition](#production-prohibition)
- [Security Considerations](#security-considerations)

---

## Overview

A standard `cdk deploy` with no extra flags runs a full CloudFormation deployment and waits for every resource to stabilize. Two options trade safety for speed:

- **Hotswap** (`--hotswap`, `--hotswap-fallback`) — bypasses CloudFormation entirely and updates supported resources directly through AWS SDK or Cloud Control API calls.
- **Express mode** (`--express`) — still a CloudFormation deployment, but it does not wait for resources to stabilize.

Hotswap and express mode are **independent mechanisms**. When a `--hotswap-fallback` deployment falls back to CloudFormation, it performs a *standard* CloudFormation deployment, NOT an express-mode one.

You MUST NOT use either mode for production deployments. See [Production Prohibition](#production-prohibition).

---

## Choosing a Deployment Mode

| Situation | Mode |
|---|---|
| Any production deployment | Standard `cdk deploy` (no speed flags) |
| Iterating on mostly hotswappable resources, want the fastest possible deploy, drift does not matter | `cdk deploy --hotswap` |
| Same, but the deployment MUST still succeed when it touches a non-hotswappable resource | `cdk deploy --hotswap-fallback` |
| You want to avoid CloudFormation drift, or the resources are not hotswappable | `cdk deploy --express` |

Express mode is the right dev-loop choice when drift is unacceptable, because it remains a real CloudFormation deployment. Hotswap is faster but deliberately desynchronizes CloudFormation from reality.

---

## Hotswap

Hotswap updates resources directly via AWS SDK or Cloud Control API calls instead of submitting a CloudFormation change set. This is why it is fast, and also why it **creates drift on purpose**: the live state of the resource no longer matches the state CloudFormation believes it is in.

Hotswap is for development use cases ONLY.

The first hotswap deployment diffs your local changes against the last successful CloudFormation deployment. For back-to-back hotswap deployments, the template synthesized by the *previous hotswap deployment* is used as the basis for the current deployment's diff.

### `--hotswap` vs `--hotswap-fallback`

These two flags behave very differently when a deployment touches a resource that cannot be hotswapped. You MUST pick deliberately.

**`cdk deploy --hotswap`** — deploys only the changes to hotswappable resources. When a deployment involves both hotswappable and non-hotswappable resources, the changes to non-hotswappable resources are **silently ignored** and merely logged in the command output.

```bash
cdk deploy $STACK_NAME --hotswap
```

You MUST read the command output when using `--hotswap`. A change to a non-hotswappable resource will not be deployed even though the command reports success. If a code change appears to have no effect, check the output for ignored non-hotswappable changes before debugging further.

**`cdk deploy --hotswap-fallback`** — if the deployment involves only hotswappable changes, a hotswap deployment is performed. If it involves any non-hotswappable change, hotswap is not attempted at all and a standard CloudFormation deployment is performed instead.

```bash
cdk deploy $STACK_NAME --hotswap-fallback
```

The decision is all-or-nothing: either every changed resource is hotswappable and a hotswap deployment happens, or at least one is not and the whole deployment goes through CloudFormation. `--hotswap-fallback` SHOULD be preferred over `--hotswap` when you cannot afford a silently dropped change.

### Hotswappable Resource Types

Hotswap supports a specific set of resource types and change kinds that varies by CDK CLI version, so you MUST NOT answer from an enumerated list — including one recalled from training data.

The authoritative list lives in the `--hotswap` option of the [`cdk deploy` CLI reference](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-deploy.html#ref-cli-cmd-deploy-options-hotswap), in the section listing the supported hotswap changes. Read it before concluding a change is or is not hotswappable. For types not yet documented there, check the [aws-cdk-cli release notes](https://github.com/aws/aws-cdk-cli/releases). That page also documents which CloudFormation intrinsic functions resolve during a hotswap deployment, which constrains what a hotswappable resource's properties can reference. That set also changes across CDK CLI releases, so read it from the CLI reference or the release notes rather than assuming it.

Any change outside the current list is non-hotswappable and is subject to the `--hotswap` / `--hotswap-fallback` behavior above. The empirical check is the deployment itself: `--hotswap` logs every change it skipped as non-hotswappable, and `--hotswap-fallback` falls through to CloudFormation when it finds one.

### cdk watch Defaults to Hotswap

`cdk watch` (equivalently `cdk deploy --watch`) continuously observes CDK project files and automatically deploys the specified stacks when it detects a change.

```bash
cdk watch $STACK_NAME
```

By default `cdk watch` deploys using `--hotswap`. It therefore inherits both hotswap consequences: it creates drift, and it silently ignores changes to non-hotswappable resources. You MUST NOT run `cdk watch` against a production stack.

### Hotswap Drift and Recovery

Because hotswap writes directly to resources, CloudFormation's record of the stack becomes stale: the stored template still describes the pre-hotswap state, while the live resources hold the hotswapped state.

**Until you revert the drift, you MUST NOT treat CloudFormation's recorded state as authoritative.** After a hotswap deployment the live resources — not CloudFormation's records — are the source of truth for what is actually deployed. Anything that reads the stored template instead of the live resources (a drift-unaware audit, another engineer's `cdk diff`, compliance tooling that trusts CloudFormation) will report the stale pre-hotswap configuration, not what is running.

To reconcile CloudFormation's records with the live resources, deploy with the revert-drift flag:

```bash
cdk deploy $STACK_NAME --revert-drift
```

This performs a CloudFormation deployment using **Drift Aware Changesets**. A Drift Aware Changeset treats the *template being deployed* as the source of truth and, resource by resource, checks whether the live resource is already in the state the template specifies:

- If a resource is already in the expected state, it is left alone.
- If a resource is not in the expected state, it is updated so the live resource matches the template.

Note the direction of reconciliation: `--revert-drift` makes the **live resources** conform to the **template** (your desired state). It does NOT rewrite CloudFormation's records to match whatever the resources currently happen to be — the template is authoritative, not the drifted live state. This is the best way to recover from hotswap drift, because the template you deploy after a run of hotswap deployments describes the state you actually want your resources in, and the drift-aware changeset skips the resources hotswap already brought to that state instead of needlessly re-updating them.

---

## Express Mode

Express mode is a CloudFormation deployment option for faster deployments, enabled in CDK with `--express`. It is primarily for development use cases.

```bash
cdk deploy $STACK_NAME --express
```

Express mode is faster than a standard CloudFormation deployment because it **skips waiting for resources to stabilize**. It returns as soon as the create, update, or delete API call for each resource returns, reporting whether that call succeeded or failed, without waiting for the resource to reach a stable state. Consequently, resources MAY NOT be fully operational when the deployment reports completion.

Express mode still respects the resource dependencies declared in your template. When one resource references another, CloudFormation confirms the referenced resource's configuration is applied before starting the dependent resource. If a dependent resource fails because a referenced resource was not ready, CloudFormation retries the operation.

Express mode propagates automatically to nested stacks when an operation on the parent stack uses it.

Unlike hotswap, express mode does not bypass CloudFormation, so it does not create drift.

### Supported Commands

Express mode is available as an option on:

- `cdk deploy --express`
- `cdk bootstrap --express`
- `cdk destroy --express`

### Rollback Behavior

Express mode does NOT perform rollback automatically. When an operation fails, CloudFormation does not attempt to roll the change back and reports the stack as failed.

Automatic rollback can be enabled explicitly:

```bash
cdk deploy $STACK_NAME --express --rollback
```

This is NOT the preferred way to deploy with express mode.

Note the narrow scope of `--rollback`: when a deployment fails *during* `cdk deploy --express --rollback`, that stack will be rolled back. Express mode does not perform rollback in any other instance.

### Recovering a Failed Express Deployment

This is the highest-risk difference between express mode and a standard CloudFormation deployment, and standard recovery guidance does NOT apply.

- Express mode deployments MUST NOT be expected to use the CloudFormation Rollback Stack API — they cannot.
- Standard CloudFormation deployments MUST NOT be used to recover a failed express mode deployment.
- Running `cdk deploy --express` or `cdk deploy --express --rollback` against an already-failed stack will not attempt to use the Rollback Stack API to recover it, unlike `cdk deploy` without express mode. The changes are applied to the failed stack without first attempting a rollback.

You MUST recover by rolling **forward** with another express mode deployment that resolves the failure — either revert the resource to its last successful state in code, or make some other change that fixes the underlying cause — then:

```bash
cdk deploy $STACK_NAME --express
```

---

## Production Prohibition

You MUST NOT use hotswap in production deployments. Hotswap deployments create drift on purpose; the actual state of your resources may not match the state CloudFormation thinks they are in.

You MUST NOT use express mode in production deployments, because:

- An operation may quietly fail after express mode has already reported success, since it does not wait for resources to stabilize.
- Express mode disables automatic rollback by default, so stacks can end up in states that are difficult to recover from.

For production, deploy with a standard `cdk deploy` and no speed flags.

---

## Security Considerations

Both modes carry security consequences beyond the operational ones above.

**Hotswap drift can desynchronize security-critical configuration.** Hotswap writes directly to resources, so security groups, IAM policies, encryption settings, and resource policies can end up in states that diverge from what CloudFormation records. Any control that reads the CloudFormation template rather than live resource state will report the intended configuration, not the deployed one. You MUST NOT treat CloudFormation state as authoritative for an audit of a stack that has been hotswapped; reconcile first with `cdk deploy $STACK_NAME --revert-drift`.

**A failed express deployment can leave resources partially configured.** Because express mode does not wait for stabilization and does not roll back by default, a deployment that fails midway can leave a resource created but without its intended encryption, access controls, or policy attachments. You MUST NOT assume a failed `--express` deployment left nothing behind; inspect the stack's resources before reusing the environment.

**Enforce the production prohibition with IAM rather than developer discipline.** Hotswap performs its API calls with your current AWS credentials — it deliberately does not assume the bootstrap stack's deploy roles, because those roles do not have permission to update resources directly outside CloudFormation. A production account can therefore block hotswap outright: grant direct resource-mutation permissions only to the CloudFormation deployment role, and use an SCP or IAM permissions boundary to deny those mutations to developer principals. Hotswap then fails on the API call instead of silently drifting production. Because hotswap mutates resources directly under the developer's own identity, developers performing hotswap deployments SHOULD authenticate with short-lived credentials from IAM Identity Center (AWS SSO) rather than long-lived IAM user access keys, so that a compromised credential has a bounded lifetime and a smaller blast radius.

**Detect hotswap through drift.** Hotswap introduces CloudFormation drift by design, so drift detection is the signal that matches it most directly: run `cdk drift $STACK --fail` on production stacks in CI.
