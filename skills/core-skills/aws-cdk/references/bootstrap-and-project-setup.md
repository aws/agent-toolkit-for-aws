# Bootstrap and Project Setup Reference

## Table of Contents

- [Bootstrap and Project Setup Reference](#bootstrap-and-project-setup-reference)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [Bootstrap Procedure](#bootstrap-procedure)
    - [What Bootstrap Creates](#what-bootstrap-creates)
    - [Bootstrap Command](#bootstrap-command)
    - [Cross-Account Trust](#cross-account-trust)
    - [Custom Qualifier](#custom-qualifier)
    - [Permissions Boundary](#permissions-boundary)
    - [Custom Bootstrap Template](#custom-bootstrap-template)
    - [Bootstrap Constraints](#bootstrap-constraints)
  - [TypeScript Project Setup](#typescript-project-setup)
    - [Prerequisites](#prerequisites)
    - [Initialize Project](#initialize-project)
    - [Project Structure](#project-structure)
    - [Configure tsx](#configure-tsx)
    - [Linting](#linting)
    - [Common Commands](#common-commands)
  - [Python Project Setup](#python-project-setup)
    - [Prerequisites](#prerequisites-1)
    - [Initialize Project](#initialize-project-1)
    - [Virtual Environment](#virtual-environment)
    - [Common Commands](#common-commands-1)
  - [Version Management Best Practices](#version-management-best-practices)
    - [CLI and Library Are Separate Release Tracks](#cli-and-library-are-separate-release-tracks)
    - [Feature Flags](#feature-flags)

---

## Overview

Every CDK deployment target (account + region pair) MUST be bootstrapped before the first
deployment. Projects MUST commit a lockfile and SHOULD use strict tooling to ensure reproducible builds.

---

## Bootstrap Procedure

### What Bootstrap Creates

The `CDKToolkit` CloudFormation stack provisions:

- An S3 bucket (file assets and CloudFormation templates)
- An ECR repository (Docker image assets)
- 4 IAM roles for user to assume (deploy, lookup, file-publishing, image-publishing)
- A CloudFormation execution role
- An SSM parameter (`/cdk-bootstrap/$QUALIFIER/version`)

### Bootstrap Command

```bash
cdk bootstrap aws://$ACCOUNT_ID/$REGION
```

Bootstrap REQUIRES near-administrator permissions in the target account.

### Cross-Account Trust

To allow a CI/CD account to deploy into a target account:

```bash
cdk bootstrap aws://$TARGET_ACCOUNT/$REGION \
  --trust $CI_ACCOUNT_ID \
  --cloudformation-execution-policies arn:aws:iam::aws:policy/$POLICY_NAME
```

The `--trust` flag grants the specified account permission to assume the CDK roles.
The `--cloudformation-execution-policies` flag MUST be provided with `--trust` to
scope the CloudFormation execution role.

### Custom Qualifier

To run multiple independent CDK environments in the same account/region:

```bash
cdk bootstrap aws://$ACCOUNT_ID/$REGION --qualifier $QUALIFIER
```

The qualifier MUST be alphanumeric and at most 10 characters. It distinguishes
bootstrap resources from other CDK environments in the same account.

### Permissions Boundary

To attach a permissions boundary to all IAM roles created by CDK:

```bash
cdk bootstrap aws://$ACCOUNT_ID/$REGION \
  --custom-permissions-boundary $BOUNDARY_POLICY_NAME
```

### Custom Bootstrap Template

To use an organization-approved bootstrap template:

```bash
cdk bootstrap aws://$ACCOUNT_ID/$REGION --template $TEMPLATE_PATH
```

### Bootstrap Constraints

- Deleting the `CDKToolkit` stack MUST NOT be done — it breaks all deployments
  in that account/region pair.
- Termination protection SHOULD be enabled on the `CDKToolkit` stack.
- Bootstrap MUST be re-run when upgrading to a CDK version that requires a newer
  bootstrap stack version.

---

## TypeScript Project Setup

### Prerequisites

- Node.js ≥ 20 MUST be installed.

### Initialize Project

```bash
cdk init app --language typescript
```

### Project Structure

```
$PROJECT_ROOT/
├── bin/          # Entry point (App instantiation)
├── lib/          # Stack and construct definitions
├── cdk.json      # CDK configuration
├── package.json
└── tsconfig.json
```

### Configure tsx

The `cdk.json` `app` field SHOULD use `tsx` instead of `ts-node` for faster startup:

```json
{
  "app": "npx tsx bin/$APP_NAME.ts"
}
```

### Linting

Projects MUST enforce strict typing — `any` MUST NOT be used. Configure with:

- `eslint` + `prettier`
- `eslint-plugin-awscdk` for CDK-specific rules

Construct props interfaces SHOULD use `readonly` on all properties:

```typescript
interface MyConstructProps {
  readonly bucketName: string;
  readonly enableVersioning: boolean;
}
```

### Common Commands

```bash
cdk synth          # Synthesize CloudFormation template
cdk diff           # Show pending changes
cdk deploy         # Deploy stack(s)
cdk destroy        # Tear down stack(s)
cdk list           # List all stacks in the app
```

---

## Python Project Setup

### Prerequisites

- Node.js ≥ 20 MUST be installed.
- Python ≥ 3.9 MUST be installed.

### Initialize Project

```bash
cdk init app --language python
```

### Virtual Environment

After initialization, activate the virtualenv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dependencies SHOULD be captured in `requirements.txt` (or `poetry.lock` / `Pipfile.lock`) and committed for reproducible builds. See [Version Management Best Practices](#version-management-best-practices).

### Common Commands

```bash
cdk synth           # Synthesize CloudFormation template
cdk deploy          # Deploy stack(s)
cdk bootstrap       # Bootstrap target environment
cdk doctor          # Check for potential problems
```

---

## Version Management Best Practices

- **Commit lockfiles** (`package-lock.json` / `poetry.lock` / `Pipfile.lock`). Unlocked builds drift and lose determinism.
- **For CDK applications**, use **caret (`^`) ranges** for `aws-cdk-lib` and `constructs` in `dependencies` — this is the officially recommended approach. The lockfile provides reproducibility; the caret range lets `npm update` pull compatible fixes and features.

  ```json
  {
    "dependencies": {
      "aws-cdk-lib": "^2.170.0",
      "constructs": "^10.5.0"
    }
  }
  ```

  Teams that prefer exact pinning for stricter reproducibility SHOULD pair it with automated upgrade tooling (Dependabot, Renovate) to avoid falling behind.
- **For construct libraries**, declare `aws-cdk-lib` and `constructs` as `peerDependencies` (caret, widest compatible) and as `devDependencies` at the oldest supported exact version.
- **Experimental / alpha modules** (e.g. `@aws-cdk/aws-*-alpha`) SHOULD use exact versions — their APIs can change between releases without SemVer guarantees.
- **Automate upgrades**: a weekly job that bumps `aws-cdk-lib`, runs `cdk synth` to catch breaking changes, deploys to a test environment, and opens a PR on success.

### CLI and Library Are Separate Release Tracks

The CDK CLI (`aws-cdk`) and the library (`aws-cdk-lib`) are **independent packages on different release tracks — their version numbers do NOT align**. A CLI at `2.1001.x` paired with a library at `2.200.x` is normal. The compatibility contract is one-way: a newer CLI can read assemblies produced by older libraries, but an older CLI CANNOT read assemblies produced by newer libraries. The mismatch surfaces as:

```
This CDK CLI is not compatible with the CDK library used by your application.
(Cloud assembly schema version mismatch)
```

The fix is to upgrade the CLI to a specific newer version. You MUST install `aws-cdk` as a dev dependency at an **exact** version and invoke it via `npx cdk`; you MUST NOT use `aws-cdk@latest` anywhere — it is non-deterministic, so a broken release can reach your pipeline instantly.

```json
{
  "devDependencies": {
    "aws-cdk": "2.1010.0"
  }
}
```

```bash
npx cdk synth
npx cdk deploy $STACK_NAME
```

Bump the pinned CLI version regularly (Dependabot / Renovate), on the same cadence as `aws-cdk-lib`.

### Feature Flags

`cdk.json`'s `context` object carries CDK feature flags — per-release opt-ins to behaviour changes. When upgrading `aws-cdk-lib`, review new flags and adopt them incrementally (inspect via `cdk flags --unstable=flags`). Do not flip everything to recommended in one commit.
