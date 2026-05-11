# Compliance and Drift Reference

## Table of Contents

- [Overview](#overview)
- [cdk-nag Setup and Rule Packs](#cdk-nag-setup-and-rule-packs)
  - [Installation](#installation)
  - [Available Rule Packs](#available-rule-packs)
  - [Applying Rule Packs](#applying-rule-packs)
- [Suppression Patterns](#suppression-patterns)
- [Drift Detection](#drift-detection)
  - [cdk drift vs cdk diff](#cdk-drift-vs-cdk-diff)
  - [Running Drift Detection](#running-drift-detection)
- [Drift Resolution Strategies](#drift-resolution-strategies)
- [CI Integration](#ci-integration)
  - [Strict Mode](#strict-mode)
  - [cdk-nag in CI](#cdk-nag-in-ci)
  - [Drift in CI](#drift-in-ci)
  - [Security Scanning Layers](#security-scanning-layers)
  - [Strict Mode Rollout](#strict-mode-rollout)

---

## Overview

CDK applications MUST be scanned for compliance violations before deployment and
monitored for drift after deployment. `cdk-nag` provides compile-time policy
enforcement. `cdk drift` detects runtime configuration changes made outside CDK.

---

## cdk-nag Setup and Rule Packs

### Installation

```bash
npm install cdk-nag
```

cdk-nag MUST be wired in before the first deploy to prevent non-compliant
resources from ever reaching production.

### Available Rule Packs

| Rule Pack               | Use Case                                    |
|-------------------------|---------------------------------------------|
| `AwsSolutionsChecks`    | General AWS best practices                  |
| `HIPAASecurityChecks`   | HIPAA compliance                            |
| `NIST80053R5Checks`     | NIST 800-53 Rev 5 compliance                |
| `PCIDSS321Checks`       | PCI DSS 3.2.1 compliance                    |

For SOX compliance, apply both `NIST80053R5Checks` and `AwsSolutionsChecks` together.

### Applying Rule Packs

Rule packs are applied as CDK Aspects:

```typescript
import { Aspects } from 'aws-cdk-lib';
import { AwsSolutionsChecks } from 'cdk-nag';

Aspects.of($APP).add(new AwsSolutionsChecks());
```

Multiple rule packs MAY be applied simultaneously:

```typescript
Aspects.of($APP).add(new AwsSolutionsChecks());
Aspects.of($APP).add(new NIST80053R5Checks());
```

---

## Suppression Patterns

When a finding is intentionally accepted, suppress it with
`NagSuppressions.addResourceSuppressions()`. Every suppression MUST include a
documented reason:

```typescript
import { NagSuppressions } from 'cdk-nag';

NagSuppressions.addResourceSuppressions($CONSTRUCT, [
  {
    id: '$RULE_ID',
    reason: '$DOCUMENTED_JUSTIFICATION',
  },
]);
```

Suppressions MUST NOT be used to bypass findings without genuine justification.

---

## Drift Detection

### cdk drift vs cdk diff

- `cdk diff` compares the local CDK app against the **last deployed template**.
  It shows what a new deployment would change.
- `cdk drift` compares the **deployed template** against the **actual live
  resource state**. It shows out-of-band changes made outside CDK.

### Running Drift Detection

Single stack:

```bash
cdk drift $STACK_NAME
```

All stacks:

```bash
cdk drift
```

---

## Drift Resolution Strategies

When drift is detected, resolve it using one of these approaches (in order of
preference):

1. **Redeploy** — Run `cdk deploy $STACK_NAME` to overwrite the drifted state
   with the CDK-defined state. This is the simplest resolution.

2. **Adopt the change** — If the out-of-band change is desired, update the CDK
   code to match the live state using `Cfn``<Resource>``PropsMixin` to adopt the drifted
   property values.

3. **Fallback overrides** — If `Cfn``<Resource>``PropsMixin` is not available for the
   resource type, use `addPropertyOverride` or `node.defaultChild` to set the
   property at the L1 level.

4. **Handle deleted resources** — If a resource was deleted outside CDK,
   remove it from the CDK code or re-import it.

Drift SHOULD be prevented proactively using SCPs (Service Control Policies) that
restrict manual changes to CDK-managed resources.

---

## CI Integration

### Strict Mode

`--strict` MUST be passed on every `cdk synth` and `cdk deploy` in CI. Strict
mode promotes warnings to build failures:

```bash
npx cdk synth --strict
npx cdk deploy $STACK_NAME --strict
```

Pair `--strict` with cdk-nag to catch both CDK warnings and compliance violations.

### cdk-nag in CI

cdk-nag MUST be enforced in CI pipelines. Because rule packs are applied as
Aspects, `cdk synth` will fail if any violations are found (when using
`--strict`), blocking the deployment.

cdk-nag scans for:

- Over-permissive IAM policies
- Open security groups
- Unencrypted resources
- Missing logging

### Drift in CI

Automate drift detection in CI with the `--fail` flag:

```bash
cdk drift --fail
```

This exits with a non-zero code when drift is detected, failing the pipeline.

### Security Scanning Layers

1. Wire cdk-nag first as the primary compliance layer.
2. Add Checkov as a second scanning layer for additional coverage.

### Strict Mode Rollout

To adopt `--strict` incrementally on an existing project:

1. Collect current warnings with `cdk synth`.
2. Triage each warning — determine if it is a real issue or acceptable.
3. Fix genuine issues; suppress accepted findings with `NagSuppressions`.
4. Enable `--strict` in CI once all warnings are resolved or suppressed.
