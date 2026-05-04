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

---

## Overview

Every CDK deployment target (account + region pair) MUST be bootstrapped before the first
deployment. Projects MUST be initialized with pinned dependencies and strict tooling to
ensure reproducible builds.

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

Dependencies SHOULD be pinned to exact versions in `requirements.txt`.

### Common Commands

```bash
cdk synth           # Synthesize CloudFormation template
cdk deploy          # Deploy stack(s)
cdk bootstrap       # Bootstrap target environment
cdk doctor          # Check for potential problems
```

---

## Version Management Best Practices

- `aws-cdk-lib` and `constructs` MUST be pinned to exact versions in
  `package.json` (or `requirements.txt` for Python).
- The CDK CLI MUST be installed as a pinned dev dependency and invoked via
  `npx cdk` — MUST NOT be installed globally.
- `@latest` MUST NOT be used for any CDK package.
- Teams SHOULD automate weekly dependency upgrades (e.g., Dependabot, Renovate)
  to stay current without manual drift.

```json
{
  "devDependencies": {
    "aws-cdk": "$EXACT_VERSION"
  },
  "dependencies": {
    "aws-cdk-lib": "$EXACT_VERSION",
    "constructs": "$EXACT_VERSION"
  }
}
```

Invoke the CLI through the pinned version:

```bash
npx cdk synth
npx cdk deploy $STACK_NAME
```
