# AWS IAM Policy Generation

## CRITICAL RULE — READ THIS FIRST

**If the user provides source code in Python, Go, TypeScript, JavaScript, or Java:**
You MUST propose the `uvx iam-policy-autopilot@latest generate-policies` command. You MUST NOT manually analyze the code and construct a policy yourself. The Autopilot tool does deterministic static analysis — your job is to construct the correct command with the right flags, NOT to replicate what the tool does.

**If no source code is provided, or the language is unsupported (Rust, C#, PHP, Ruby, etc.):**
Use the Service Authorization Reference path to produce the policy directly.

## Overview

Generates baseline AWS IAM identity-based policies through two complementary approaches:

1. **IAM Policy Autopilot** (primary, MANDATORY when source code in a supported language is present) — Deterministic static analysis of application source code. Produces policies by parsing actual AWS SDK calls. Preferred for security because it is reproducible and not subject to LLM hallucination. You MUST use this path when source code is available in a supported language.
2. **Service Authorization Reference** (fallback) — Queries the programmatic service reference to map API operations to correct IAM actions. Used ONLY when Autopilot is unavailable, the task does not involve source code, or the source language is not supported.

**Output completeness rule — CRITICAL:**

- When using the Service Authorization Reference path (Task 3): You MUST always produce a complete policy document in your response. Use placeholder values (e.g., `<bucket-name>`, `<role-arn>`, `<REGION>`) when specific resource names are not provided. NEVER ask clarifying questions instead of producing a policy.
- When using the Autopilot path (Task 2): You MUST produce the complete `uvx iam-policy-autopilot@latest generate-policies` command with all required flags. You MUST NOT manually construct a policy — the Autopilot command IS your output. Do not also produce a hand-written policy "in case Autopilot isn't available."
- If the user's code uses runtime variables for resource names, use descriptive placeholders in the ARNs (Reference path) or note that Autopilot handles this automatically (Autopilot path).

## Common Tasks

### 0. Language Gate (MANDATORY FIRST STEP)

When source code is provided, identify the programming language before choosing a path.

**Supported languages** (use Autopilot — Task 1 → Task 2):

- Python (boto3)
- Go (SDK v2)
- TypeScript/JavaScript (SDK v3)
- Java (SDK v2)

**Unsupported languages** (Rust, C#, PHP, Ruby, Kotlin, Swift, etc.) — fall back silently to the Service Authorization Reference path (Task 3). Do NOT attempt to use Autopilot. Do NOT ask the user whether to proceed with the fallback — just produce the policy directly using the Reference path. Even if a Terraform directory is mentioned alongside unsupported-language code, you MUST NOT attempt to use `--tf-dir` with Autopilot — the language is unsupported, so Autopilot cannot be used at all.

**For supported languages**, you MUST:

1. Propose the `uvx iam-policy-autopilot@latest generate-policies` command with the correct flags
2. Present the command for the user to run
3. You MUST NOT use `service_reference_query`, `curl`, or any manual approach to derive policies from source code when the language is supported by Autopilot

You MUST NOT manually analyze source code and construct policies yourself when Autopilot can do it deterministically. The entire point of Autopilot is that it produces reproducible, auditable results without LLM interpretation. Your job is to construct the correct Autopilot command, not to replicate what Autopilot does.

Fall back to the Service Authorization Reference path ONLY when:

- The `iam-policy-autopilot` CLI is not installed AND installation fails
- The user's task does not involve source code (e.g., they name specific API operations or actions directly)
- The source language is not supported (Rust, C#, PHP, Ruby, Kotlin, Swift, etc. are NOT supported)

### 1. Verify Autopilot Availability

The tool runs via `uvx` (the Python package runner from `uv`). No separate installation is needed — `uvx` downloads and executes the tool in one step.

**Constraints:**

- You MUST verify `uvx` is available before any policy generation task involving source code
- You MUST NOT skip this step or assume availability

```bash
uvx iam-policy-autopilot@latest --version
```

If this fails:

- If `uvx` is not found: attempt installation before falling back. Try `brew install uv` (macOS) or `pip install uv` (any platform). If installation succeeds, retry the version check.
- If `uv` cannot be installed: try installing iam-policy-autopilot directly via `pip install iam-policy-autopilot` and then run `iam-policy-autopilot --version`.
- If ALL installation attempts fail: inform the user and fall back to the Service Authorization Reference path (Task 3).
- If `uvx` is found but the command fails for another reason (network error, etc.): retry once, then fall back.

The goal is to use Autopilot whenever possible — exhaust installation options before falling back to LLM-based policy generation.

Once `uvx iam-policy-autopilot@latest --version` (or `iam-policy-autopilot --version`) succeeds, proceed with Task 1b.

### 1b. Discover Account ID and Region

Before constructing the Autopilot command, attempt to discover the AWS account ID and region. These produce more precisely scoped resource ARNs in the generated policy (without them, Autopilot uses wildcards).

**Discovery methods (try in order):**

1. **User-provided values** — If the user specified an account ID or region in their prompt, use those directly.
2. **Environment variables** — Check for `AWS_ACCOUNT_ID`, `AWS_DEFAULT_REGION`, or `AWS_REGION`:

   ```bash
   echo "Account: ${AWS_ACCOUNT_ID:-not set}" && echo "Region: ${AWS_REGION:-${AWS_DEFAULT_REGION:-not set}}"
   ```

3. **AWS CLI / STS** — If AWS credentials are configured, query STS:

   ```bash
   aws sts get-caller-identity --query Account --output text
   aws configure get region
   ```

4. **Project configuration files** — Look for account/region in common locations:
   - `terraform.tfvars`, `*.tf` files (look for `region` or `account_id` variables)
   - `cdk.json` or `cdk.context.json`
   - `samconfig.toml` (look for `region` parameter)
   - `.env` files (look for `AWS_REGION`, `AWS_ACCOUNT_ID`)
   - `serverless.yml` (look for `provider.region`)

**Constraints:**

- You SHOULD attempt discovery but MUST NOT block on it — if discovery fails, proceed without `--account` and `--region` (Autopilot will use wildcards in ARNs)
- You MUST NOT hallucinate or guess account IDs or regions. If you cannot discover them through the methods above, OMIT the `--account` and `--region` flags entirely. A missing flag (producing wildcard ARNs) is always better than a fabricated value (producing incorrect ARNs that won't match real resources).
- You MUST NOT ask the user for their account ID or region if you can discover it automatically
- If you discover values, include them as `--account` and `--region` flags in the Autopilot command

### 2. Generate Policies from Source Code (Autopilot)

Analyzes source files using deterministic static analysis to produce minimal IAM identity-based policies.

**When to use:** User has application source code that makes AWS SDK calls and wants IAM policies generated from it.

```bash
uvx iam-policy-autopilot@latest generate-policies \
  /home/user/project/src/app.py /home/user/project/src/handler.py \
  --region us-east-1 \
  --account 123456789012 \
  --service-hints s3 dynamodb \
  --pretty
```

**Required parameters:**

- `<source_files>` — One or more absolute paths to source files

**Optional parameters:**

- `--region <REGION>` — AWS region for resource ARNs
- `--account <ACCOUNT>` — AWS account ID for resource ARNs
- `--service-hints <SERVICES>` — Space-separated AWS service names to scope analysis
- `--pretty` — Pretty-print JSON output
- `--upload-policies <PREFIX>` — Upload generated policies to IAM with given prefix
- `--tf-dir <DIR>` — Terraform project directory for more precise ARNs
- `--tfstate <FILES>` — terraform.tfstate files for deployed resource ARNs (highest precision)
- `--explain <PATTERN>` — Explain why specific actions were included

**Constraints:**

- You MUST use absolute paths when passing source files
- You MUST include ALL relevant source files that interact with AWS services
- You MUST ONLY include files that contain runtime AWS SDK calls — do NOT include infrastructure-as-code files (CDK stacks, Terraform configs, CloudFormation templates) as these define resources, not runtime behavior
- You SHOULD use `--service-hints` to reduce false positives from ambiguous method names
- You MUST include `--region` and `--account` if values were discovered in Task 1b or provided by the user — these produce scoped ARNs instead of wildcards
- You MUST NOT upload or apply policies without explicit user confirmation
- When the user confirms use of `--upload-policies`, recommend enabling CloudTrail logging and CloudWatch alarms for IAM changes (see Security Considerations)
- You MUST NOT use `service_reference_query` or manually construct the policy — delegate to Autopilot
- You MUST NOT call AWS APIs or query the service authorization reference as a substitute for running Autopilot
- The presence of non-AWS libraries (HTTP clients, database drivers, Redis, etc.) in the same file does NOT disqualify Autopilot — it only analyzes AWS SDK calls and ignores everything else

**Terraform integration — MANDATORY:**

- If the user mentions a Terraform directory, Terraform project, or Terraform state, you MUST include `--tf-dir <absolute_path>` (or `--tfstate <file>`) in the Autopilot command. This is NOT optional.
- You MUST NOT manually construct a policy when both source code in a supported language AND a Terraform directory are available — Autopilot with `--tf-dir` produces more precise ARNs than manual construction.

### 3. Generate Policies from API Operations (Service Authorization Reference)

**When to use:** Autopilot is unavailable, the task does not involve source code, or the user names specific API operations/IAM actions directly.

#### 3a. Verify Dependencies

**Constraints:**

- You MUST check whether the `service_reference_query` tool is available
- If unavailable, proceed with the `curl` and `jq` fallback automatically — do NOT ask the user for permission to proceed

#### 3b. Gather Parameters

Collect the information needed to generate the policy.

**Required parameters:**

- `operations` — The AWS API operations the user wants to perform (e.g., `CopyObject` — note: this is an API operation, not an IAM action. CopyObject requires `s3:GetObject` + `s3:PutObject`; there is no `s3:CopyObject` IAM action). API operation names and IAM action names frequently differ.

**Optional parameters:**

- `account_id` — AWS account ID for ARN construction (default: placeholder `123456789012`)
- `region` — AWS region (default: `us-east-1`)
- `resource_scope` — Specific resource ARNs or patterns (default: derived from service reference)
- `policy_type` — `identity` or `resource` (default: `identity`)

**Constraints:**

- You MUST ask for all required parameters upfront in a single prompt if they are not already provided in the user's request
- You MUST support multiple input methods (direct input, file path, URL)
- You MUST confirm the interpreted operations with the user before proceeding ONLY if the request is ambiguous — if the operations are clear from context, proceed directly

#### 3c. Query the Service Authorization Reference

Look up the correct IAM actions for each requested API operation.

The reference lives at `https://servicereference.us-east-1.amazonaws.com/v1/<service>/<service>.json`. These files are large. Use the `service_reference_query` tool or `curl` with `jq` to extract only what you need.

See [service authorization reference details](service-authorization.md) for all query patterns and the reference structure.

**Tool call example:**

```
service_reference_query(service="lambda", operation="CreateFunction")
```

**CLI fallback** (when the tool is unavailable):

```bash
curl -s "https://servicereference.us-east-1.amazonaws.com/v1/lambda/lambda.json" | \
  jq '.Operations[] | select(.Name == "CreateFunction")'
```

**Constraints:**

- You MUST query the service authorization reference for every operation — never assume action names
- You MUST include ALL actions listed in `AuthorizedActions` for each operation, including cross-service actions (e.g., `iam:PassRole` for `lambda:CreateFunction`) and prerequisite actions (e.g., `lambda:GetLayerVersion` for `lambda:CreateFunction` — required to attach layers during creation). Do NOT omit actions from the AuthorizedActions list based on your own judgment about whether they seem "optional" — if the service reference lists them, include them.
- You MUST NOT include actions for optional service variants (e.g., `s3-object-lambda:*`, `s3:GetObjectVersion`, `s3:GetObjectTagging`) unless the user explicitly mentions Object Lambda, versioning, tagging, access points, or similar features
- You MUST NOT use the API operation name as the IAM action unless the reference confirms they match
- You MUST NOT add actions for operations the user did not request — least privilege means exactly what was asked
- If the user names a specific IAM action directly (e.g., "allow s3:PutObject"), you MUST use that exact action without expanding it to all authorized actions for the underlying API operation
- If the user names a specific condition key (e.g., "use aws:TagKeys"), you MUST use that exact key — do not substitute a service-specific alternative
- You SHOULD explain to the user what you are querying and why

#### 3d. Construct the Policy

Build the IAM policy document from the queried actions.

**Pre-flight check — BEFORE writing any action name into a policy, verify it is not in the hallucinated-actions table (see Troubleshooting section).** Common mistakes: writing `s3:SelectObjectContent` instead of `s3:GetObject`, `s3:HeadObject` instead of `s3:GetObject`, `s3:CreateMultipartUpload` instead of `s3:PutObject`, `s3:DeleteBucketEncryption` instead of `s3:PutEncryptionConfiguration`. If you are about to write any S3 action that looks like an API operation name rather than a permission name, STOP and check the table.

**Constraints:**

- You MUST scope resources using specific ARNs when possible — avoid `*`
- You MUST separate cross-service actions (e.g., `iam:PassRole`) into their own statement with appropriate conditions
- You MUST present the complete policy to the user and explain each statement before considering the task complete
- You MUST NOT include "optional", "additional", or "you may also need" permissions sections in your response. If the user asked for permission to create an API, provide ONLY the creation permission. Do not suggest read, update, or delete permissions "in case they need them later." This violates least privilege even when labeled as optional.
- Your response MUST contain exactly ONE policy document. Do not present a "minimal" policy followed by a "comprehensive" or "expanded" policy — only the minimal one. If the user needs more permissions, they will ask.
- You MUST NOT add actions for operations the user did not request — least privilege means exactly what was asked, nothing more

**Resource-based policy requirements:**

When constructing resource-based policies (i.e., `policy_type` is `resource`), you MUST include condition keys to prevent confused deputy attacks where applicable:

- `aws:SourceArn` — to restrict which resource ARN can invoke the cross-service call
- `aws:SourceAccount` — to restrict which account ID can make the request
- `aws:PrincipalOrgID` — to restrict access to principals within a specific AWS Organization

Include whichever condition keys are supported by the service and relevant to the use case. Omit only when the service does not support the key or the user explicitly requests unrestricted access.

**Condition operator safety rules (CRITICAL):**

- When using `ForAnyValue` in a **Deny** statement, you MUST add a separate Deny statement with a `Null` condition (`"Null": {"<key>": "true"}`) to handle the case where the context key is absent. Without this, requests missing the key bypass the deny entirely.
- When using `ForAllValues` in an **Allow** statement, you MUST add a `Null` condition (`"Null": {"<key>": "false"}`) in the same statement to require the key to exist. Without this, requests missing the key are silently allowed.
- `ForAnyValue` and `ForAllValues` MUST only be used with array-typed condition keys (`ArrayOfString`, `ArrayOfARN`, etc.) — never with scalar types.
- Multi-valued condition keys (e.g., `aws:TagKeys`, `aws:VpceOrgPaths`) MUST use a set operator (`ForAnyValue:` or `ForAllValues:`) — plain `StringNotLike` or `StringEquals` without a set operator is INCORRECT for these keys.

**Worked example — ForAnyValue:StringNotLike in Deny (MANDATORY pattern):**

When restricting access based on a multi-valued key like `aws:VpceOrgPaths`, you MUST produce TWO Deny statements:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyNonMatchingVpceOrgPath",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::my-bucket", "arn:aws:s3:::my-bucket/*"],
      "Condition": {
        "ForAnyValue:StringNotLike": {
          "aws:VpceOrgPaths": "o-orgid/r-rootid/ou-ouid/*"
        }
      }
    },
    {
      "Sid": "DenyMissingVpceOrgPath",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::my-bucket", "arn:aws:s3:::my-bucket/*"],
      "Condition": {
        "Null": { "aws:VpceOrgPaths": "true" }
      }
    }
  ]
}
```

Key rules for this pattern:

1. Use `ForAnyValue:StringNotLike` (NOT plain `StringNotLike`) because `aws:VpceOrgPaths` is a multi-valued/array key
2. The `Null` check MUST reference the SAME condition key (`aws:VpceOrgPaths`), not a different key like `aws:VpcEndpointId`
3. Without the Null statement, requests not traversing any VPC endpoint bypass the deny entirely

See [common pitfalls](common-pitfalls.md) for additional examples.

## Decision Guide

| Situation                                           | Path      | Command/Approach                       |
| --------------------------------------------------- | --------- | -------------------------------------- |
| Source code using AWS SDKs                          | Autopilot | `generate-policies` with source files  |
| Policy seems too broad from Autopilot               | Autopilot | Re-run with `--service-hints`          |
| Need to understand a specific action                | Autopilot | Use `--explain` with an action pattern |
| Using Terraform and want precise ARNs               | Autopilot | Add `--tf-dir` or `--tfstate` flags    |
| Autopilot unavailable or install failed             | Reference | Query service authorization reference  |
| User names specific API operations (no source code) | Reference | Query service authorization reference  |
| Unsupported language                                | Reference | Query service authorization reference  |
| Need resource-based policies                        | Reference | Autopilot only supports identity-based |

## Security Considerations

- **Over-permissive policies:** If `--service-hints` are omitted, Autopilot may match ambiguous method names across multiple services, producing broader policies than intended. When using the Reference path, incomplete operation lists or missing cross-service actions can result in either over- or under-permissive policies. Always review generated policies before deployment.
- **Credential exposure during discovery:** Task 1b queries STS and reads project configuration files (`.env`, `terraform.tfvars`) to discover account IDs and regions. Ensure these files do not contain secrets beyond what is needed, and be aware that STS calls appear in CloudTrail logs.
- **Policy upload without approval:** The `--upload-policies` flag creates and attaches IAM policies directly. You MUST NOT use this flag without explicit user confirmation. When using `--upload-policies`, recommend that users:
  - Enable CloudTrail logging to audit IAM policy creation and attachment events
  - Enable SSE-KMS encryption on the CloudTrail S3 bucket and enable log file validation
  - Set up CloudWatch alarms for unexpected IAM changes (e.g., `CreatePolicy`, `AttachRolePolicy` events)
  - Encrypt CloudWatch Logs log groups that receive IAM change events using a KMS key
  - Use a change management or approval workflow before uploading to production accounts
- **Review before attaching:** Always recommend that users review generated policies before attaching them to any principal. Use `iam:SimulateCustomPolicy` or the IAM Policy Simulator to validate that the policy grants only the intended access.
- **Prefer IAM roles over IAM users:** Generated policies should preferably be attached to IAM roles for workloads (EC2 instance profiles, Lambda execution roles, ECS task roles, EKS pod identity) rather than IAM users with long-lived static access keys. Roles provide ephemeral credentials that automatically rotate.
- **Confused deputy prevention for resource-based policies:** When generating resource-based policies via the Reference path, always include condition keys to prevent confused deputy attacks:
  - `aws:SourceArn` — restricts access to a specific resource ARN making the cross-service call
  - `aws:SourceAccount` — restricts access to a specific account ID
  - `aws:PrincipalOrgID` — restricts access to principals within a specific AWS Organization
  - Include whichever keys are applicable based on the service and use case

## Troubleshooting

### Autopilot not found

If `uvx` is not installed, the user needs to install `uv` first: https://docs.astral.sh/uv/getting-started/installation/ (or `brew install uv` on macOS, `pip install uv` elsewhere). Once `uv` is installed, `uvx` is available and no further setup is needed. If `uvx` cannot be installed, fall back to the Service Authorization Reference path.

### Overly broad policies from Autopilot

Use `--service-hints` to restrict analysis. Without hints, ambiguous method names may match multiple AWS services.

### No actions generated by Autopilot

Ensure source files contain actual AWS SDK client calls (e.g., `s3_client.get_object()`, `new S3Client().send()`). Wrapper functions without direct SDK usage won't be detected.

### Action name does not match API operation (Reference path)

API names and IAM actions frequently differ. Query the service authorization reference — do not guess. For example, `dynamodb:BatchExecuteStatement` does not exist as an IAM action — the operation requires `dynamodb:PartiQLDelete`, `PartiQLInsert`, `PartiQLSelect`, and `PartiQLUpdate`.

### Common hallucinated IAM actions (DO NOT USE)

These are API operation names that models incorrectly use as IAM actions. The left column shows what you MUST NOT write; the right column shows what you MUST write instead:

| ❌ WRONG (not a real IAM action) | ✅ CORRECT IAM action(s)                               |
| -------------------------------- | ------------------------------------------------------ |
| `s3:UploadPartCopy`              | `s3:PutObject` (destination) + `s3:GetObject` (source) |
| `s3:CopyObject`                  | `s3:PutObject` (destination) + `s3:GetObject` (source) |
| `s3:SelectObjectContent`         | `s3:GetObject`                                         |
| `s3:HeadObject`                  | `s3:GetObject`                                         |
| `s3:HeadBucket`                  | `s3:ListBucket`                                        |
| `s3:ListBuckets`                 | `s3:ListAllMyBuckets`                                  |
| `s3:ListObjectVersions`          | `s3:ListBucketVersions`                                |
| `s3:DeleteBucketEncryption`      | `s3:PutEncryptionConfiguration`                        |
| `s3:GetObjectLockConfiguration`  | `s3:GetBucketObjectLockConfiguration`                  |
| `s3:CreateMultipartUpload`       | `s3:PutObject`                                         |
| `dynamodb:BatchExecuteStatement` | `dynamodb:PartiQL*` actions                            |
| `apigateway:CreateRestApi`       | `apigateway:POST` + `apigateway:PUT` on `/restapis`    |
| `apigateway:CreateApi`           | `apigateway:POST` on `/apis`                           |
| `apigatewayv2:CreateApi`         | `apigateway:POST` on `/apis`                           |
| `apigateway:UpdateStage`         | `apigateway:PATCH` on `/restapis/*/stages/*`           |
| `apigateway:DeleteRestApi`       | `apigateway:DELETE` on `/restapis/<api-id>`            |

**How to read this table:** If you find yourself about to write an action from the left column, STOP and use the right column instead. The left column contains API operation names that do NOT exist as IAM actions.

When in doubt, ALWAYS query the service authorization reference. Never guess action names from API operation names.

### API Gateway resource ARN patterns

API Gateway uses HTTP-verb-based actions (POST, GET, PUT, PATCH, DELETE). Always scope to the specific resource path — do NOT use `"Resource": "*"`:

| Operation            | Action(s)                           | Resource ARN                                    |
| -------------------- | ----------------------------------- | ----------------------------------------------- |
| Create REST API      | `apigateway:POST`, `apigateway:PUT` | `arn:aws:apigateway:*::/restapis`               |
| Create HTTP API (v2) | `apigateway:POST`                   | `arn:aws:apigateway:*::/apis`                   |
| Create authorizer    | `apigateway:POST`                   | `arn:aws:apigateway:*::/restapis/*/authorizers` |
| Create domain name   | `apigateway:POST`                   | `arn:aws:apigateway:*::/domainnames`            |
| Update stage         | `apigateway:PATCH`                  | `arn:aws:apigateway:*::/restapis/*/stages/*`    |
| Delete REST API      | `apigateway:DELETE`                 | `arn:aws:apigateway:*::/restapis/<api-id>`      |
| Invoke (data plane)  | `execute-api:Invoke`                | `arn:aws:execute-api:*:*:<api-id>/<stage>/*/*`  |

**IMPORTANT — API Gateway v2 (HTTP APIs) ARN format:**

- HTTP APIs (v2) use `/apis` in the IAM resource ARN — NOT `/v2/apis`
- The `/v2/` prefix is an API endpoint URL path, NOT part of the IAM ARN format
- Both REST APIs (`/restapis`) and HTTP APIs (`/apis`) use the same `apigateway:` service prefix in IAM
- Do NOT confuse the AWS CLI/SDK endpoint path with the IAM resource ARN

**IMPORTANT — CreateRestApi requires both POST and PUT:**

- The `CreateRestApi` operation requires `apigateway:POST` for the core creation, plus `apigateway:PUT` for import/clone operations that occur during creation (e.g., importing an OpenAPI definition)
- Always include both `apigateway:POST` and `apigateway:PUT` when generating policies for REST API creation

### Missing cross-service actions (Reference path)

Some operations require actions in other services (e.g., `lambda:CreateFunction` requires `iam:PassRole`). Always check the full `AuthorizedActions` list including entries where `Service` differs from the queried service.

**Lambda CreateFunction — complete action list (commonly incomplete):**
The `CreateFunction` operation requires ALL of the following:

- `lambda:CreateFunction` (core action)
- `lambda:GetLayerVersion` (required to attach layers during creation)
- `lambda:TagResource` (required if tags are applied at creation)
- `iam:PassRole` with `iam:PassedToService` condition for `lambda.amazonaws.com` (cross-service, separate statement)

Do NOT omit `lambda:GetLayerVersion` — it is listed in `AuthorizedActions` and is required for the operation to succeed when layers are involved.

### ForAnyValue/ForAllValues behaving unexpectedly

These operators have critical edge cases with missing context keys. See [common pitfalls](common-pitfalls.md) for the Null-check patterns required to use them safely.

### Access denied despite correct action (Reference path)

Verify the resource ARN format matches what the service expects. Use query pattern 3 from the [service authorization reference](service-authorization.md) to look up the correct ARN format.

## Supported Languages (Autopilot)

| Language   | SDK                       |
| ---------- | ------------------------- |
| Python     | boto3, botocore           |
| Go         | AWS SDK for Go v2         |
| TypeScript | AWS SDK for JavaScript v3 |
| JavaScript | AWS SDK for JavaScript v3 |
| Java       | AWS SDK for Java v2       |

## Scope and Limitations

- Autopilot produces IAM **identity-based policies** only
- Autopilot does NOT support resource-based policies, RCPs, SCPs, or permission boundaries — use the Reference path for these
- Runtime-determined resource names cannot be predicted by Autopilot — use `--tfstate` for deployed resource ARNs
- The Reference path can construct both identity and resource-based policies

## Additional Resources

- [IAM Policy Autopilot GitHub](https://github.com/awslabs/iam-policy-autopilot)
- [Supported Languages and SDKs](https://github.com/awslabs/iam-policy-autopilot#supported-languages-and-sdks-for-policy-generation)
- [IAM Actions, Resources, and Condition Keys](https://docs.aws.amazon.com/service-authorization/latest/reference/)
- [IAM Policy Evaluation Logic](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html)
- [IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [Common pitfalls with condition operators](common-pitfalls.md)
- [Service authorization reference query patterns](service-authorization.md)
