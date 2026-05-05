# CloudFormation Authoring Best Practices Checklist

## Overview

Deterministic procedure for applying CloudFormation authoring best practices to a new or modified template. Works as a review pass: for each best-practice rule, check whether the template complies and propose specific fixes.

## Parameters

- **template_content** (required): The CloudFormation template as a YAML or JSON string or a file path.
- **strictness** (optional, default: "recommended"): Which rule tiers to enforce. One of:
  - `critical` — only rules that prevent security incidents or deployment failures
  - `recommended` (default) — critical + widely-agreed best practices
  - `strict` — recommended + opinionated improvements

**Constraints for parameter acquisition:**

- You MUST ask for the template upfront
- You SHOULD default to `strictness=recommended` unless the user specifies otherwise

## Steps

### 1. Verify Dependencies

No external tools required. This SOP is purely analytical.

**Constraints:**

- You MUST be able to read and parse the template as YAML or JSON

### 2. Check Resource Naming

**Rule:** Avoid hardcoded physical resource names (e.g., `BucketName`, `TableName`, `FunctionName`) when they are not required, because hardcoded names prevent multiple deployments and block blue/green replacement.

**Constraints:**

- You MUST flag any resource where a physical name is hardcoded as a literal string
- You MUST recommend using `!Sub "${AWS::StackName}-<suffix>"` or omitting the name to let CloudFormation generate it
- You MUST NOT flag names that are references (`!Ref`, `!Sub` with parameters) because those are already dynamic
- You SHOULD exempt resources where the name is functional (e.g., IAM role name referenced by an external system)

### 3. Check Parameter Design

**Rule:** Parameters MUST have sensible constraints and defaults where possible.

**Constraints:**

- You MUST flag parameters without a `Type` (the implicit default `String` is legal but loses validation)
- You MUST flag `String` parameters without `AllowedValues` or `AllowedPattern` when the parameter represents an enum (e.g., environment names like prod/staging/dev)
- You MUST flag parameters with `NoEcho: true` that are not sensitive and flag sensitive parameters (`DbPassword`, `ApiKey`, etc.) missing `NoEcho: true`
- You MUST recommend using CloudFormation dynamic references (`{{resolve:secretsmanager:MySecret}}` or `{{resolve:ssm-secure:MyParam}}`) for secrets rather than plain `String` parameters, because dynamic references resolve at deploy time and avoid exposing secrets in the template, console, or API responses

### 4. Check Cross-Stack References

**Rule:** Prefer cross-stack references via `Export`/`ImportValue` OR parameter passing. Avoid hardcoding ARNs from other stacks.

**Constraints:**

- You MUST flag hardcoded ARNs or resource IDs that reference resources likely in other stacks (e.g., `arn:aws:ec2:us-east-1:123456789012:vpc/vpc-0abc12345` or a literal VPC ID like `vpc-0abc12345`)
- You MUST recommend either exporting from the producing stack and using `!ImportValue`, or passing the value as a parameter
- You SHOULD warn that `!ImportValue` creates a tight coupling (the exporting stack cannot delete the export while it is imported)

### 5. Check Security Defaults

**Rule (critical tier):** Apply secure-by-default settings for stateful and network-facing resources.

**Constraints:**

- For `AWS::S3::Bucket`, You MUST flag:
  - Missing `PublicAccessBlockConfiguration` with all four sub-properties true
  - Missing `BucketEncryption`
- For `AWS::S3::Bucket`, You SHOULD flag missing `VersioningConfiguration` with `Status: Enabled` on buckets that store data (not static website hosting or logs-only buckets)
- For `AWS::SQS::Queue`, You SHOULD note that SQS queues are encrypted at rest by default with SSE-SQS. You MUST only flag missing `KmsMasterKeyId` when the user explicitly requires KMS-CMK encryption (e.g., for cross-account access, custom key rotation policies, or compliance requirements that mandate CMK). Flag `SqsManagedSseEnabled: false` as a security issue since it disables the default encryption.
- For `AWS::SNS::Topic`, You MUST flag missing `KmsMasterKeyId` because SNS topics are not encrypted at rest by default.
- For `AWS::EC2::SecurityGroup`, You MUST flag ingress rules with `CidrIp: 0.0.0.0/0` or `CidrIpv6: ::/0` on non-public ports (anything other than 80/443 for load balancers)
- For `AWS::RDS::DBInstance` and `AWS::RDS::DBCluster`, You MUST flag `StorageEncrypted: false` (or missing)
- For `AWS::Lambda::Function`, You SHOULD flag missing `DeadLetterConfig` for async-invoked functions (per cfn-guard `LAMBDA_DLQ_CHECK`)
- You MUST NOT flag missing encryption when the user explicitly sets `BucketEncryption: !Ref AWS::NoValue` (indicates a deliberate decision)

### 6. Check Template Structure

**Rule:** Organize the template sections in a consistent order and limit template size.

**Constraints:**

- You SHOULD recommend the canonical section order: `AWSTemplateFormatVersion`, `Description`, `Metadata`, `Parameters`, `Mappings`, `Conditions`, `Transform`, `Resources`, `Outputs`
- You MUST flag templates exceeding 51,200 bytes (the `--template-body` inline limit) and recommend using `--template-url` with S3, or splitting into nested stacks
- You SHOULD recommend splitting templates exceeding 200 resources into nested stacks because large single stacks slow down deploy times and complicate rollback

### 7. Check DeletionPolicy and UpdateReplacePolicy

**Rule:** Stateful resources (databases, buckets with data, tables with data) MUST have an explicit `DeletionPolicy`.

**Constraints:**

- You MUST flag `AWS::S3::Bucket`, `AWS::DynamoDB::Table`, `AWS::RDS::DBInstance`, `AWS::RDS::DBCluster`, `AWS::EFS::FileSystem` resources without `DeletionPolicy`
- You MUST recommend `DeletionPolicy: Retain` for production stateful resources and `DeletionPolicy: Snapshot` for databases where point-in-time recovery is desired
- You SHOULD also recommend `UpdateReplacePolicy: Retain` on the same resources because replacement (not just deletion) can cause data loss

### 8. Check Conditions and Intrinsic Functions

**Rule:** Conditions must be string references to named conditions, not inline intrinsic functions.

**Constraints:**

- You MUST flag resources with `Condition: !Not [...]` or any inline intrinsic in the `Condition` key (this is a common mistake that cfn-lint catches as E3001)
- You MUST recommend defining a named condition in the `Conditions:` section and referencing it by name

### 9. Check Outputs

**Rule:** Outputs should be named consistently and exported only if intended for cross-stack use.

**Constraints:**

- You SHOULD note exported outputs and remind the user that exports create cross-stack coupling — confirm each export has a known consumer. Single-template analysis cannot determine whether an export is consumed by another stack, so this is advisory rather than a hard failure.
- You SHOULD recommend adding a `Description` to every output

### 10. Present Findings

Report the checklist results.

**Constraints:**

- You MUST group findings by severity: Critical (security, will-fail-deployment) → Recommended → Strict
- You MUST provide the specific template change for each finding
- You MUST show line numbers where applicable
- You SHOULD respect the `strictness` parameter and suppress findings below the selected tier
- You SHOULD end with a summary: "X critical, Y recommended, Z strict findings"

## Examples

### Example Input

```yaml
Parameters:
  Environment:
    Type: String
Resources:
  DataBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: acme-data-prod
```

### Example Output (strictness=recommended)

```
2 critical, 2 recommended findings.

Critical:

1. DataBucket — public access not blocked
   Add: PublicAccessBlockConfiguration with all four blocks true
   Add: BucketEncryption with SSEAlgorithm AES256 or aws:kms

2. DataBucket — no DeletionPolicy on a stateful resource
   Add: DeletionPolicy: Retain and UpdateReplacePolicy: Retain

Recommended:

3. Parameters.Environment — String parameter without AllowedValues
   Change: AllowedValues: [prod, staging, dev]
   Why: constrains to valid environments; cfn-lint will validate

4. DataBucket.BucketName — hardcoded ("acme-data-prod")
   Change: use !Sub "${AWS::StackName}-data" or omit the name
   Why: hardcoded names prevent multiple deployments and block replacement
```

## Troubleshooting

### User disagrees with a finding
Best practices are not absolutes. If the user explains a deliberate deviation, You MUST record the reason and not keep re-flagging it in subsequent runs. Some exceptions are valid:

- Hardcoded names for resources referenced by external systems
- Missing encryption for resources storing only non-sensitive public data
- Missing DLQ on functions that are synchronously-invoked only

### Strictness tier feels off
If the user finds `recommended` too noisy, offer `critical` mode. If they want more, offer `strict`. Adjust based on feedback.
