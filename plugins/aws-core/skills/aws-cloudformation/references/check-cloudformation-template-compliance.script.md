# Check CloudFormation Template Compliance

## Overview

Deterministic procedure for validating a CloudFormation template against security and compliance rules using cfn-guard. Works via the `cfn-guard` CLI or the Python `guardpycfn` binding.

## Parameters

- **template_content** (required): The CloudFormation template as a YAML or JSON string, a file path, or a URL to the template.
- **rules_file_path** (optional): Path to a custom cfn-guard rules file. If omitted, you MUST obtain rules separately because cfn-guard has no built-in rule set. Recommended source: https://github.com/aws-cloudformation/aws-guard-rules-registry

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt rather than one at a time
- You MUST support multiple input methods for the template:
  - Direct input: Template content pasted directly
  - File path: Path to a local template file
  - URL: Link to a template in a repository or S3
- You MUST confirm successful acquisition of the template content before proceeding

## Steps

### 1. Verify Dependencies

Check which compliance mechanism is available.

**Constraints:**

- You MUST check in this order of preference:
  1. `cfn-guard` CLI available on the user's system (verify with `which cfn-guard` or `cfn-guard --version`)
  2. Python `guardpycfn` library (verify by attempting `import guardpycfn` in a throwaway Python command)
- If cfn-guard is not installed, You MUST ask the user: "I can install `cfn-guard` (see https://docs.aws.amazon.com/cfn-guard/latest/ug/setting-up.html for install options). Do you want me to install it, or would you prefer to install it manually?"
- You MUST NOT execute compliance checks or run any install command without the user's explicit approval because this changes the user's environment
- If no mechanism is available and the user declines installation, You MUST ask whether to abort or proceed anyway (knowing the SOP cannot complete)
- You MUST respect the user's decision to proceed, install, or abort

### 2. Acquire Template Content

Obtain the CloudFormation template from the user.

**Constraints:**

- You MUST ask the user which template(s) to check even if templates are discoverable in the working directory, because the user may only want a subset checked
- You MUST read the template content from the provided source (file path, direct input, or URL)
- You MUST confirm the template is non-empty and parseable as YAML or JSON before proceeding
- If the template cannot be read or parsed, You MUST inform the user with the specific error and stop
- You SHOULD recommend running the `validate-cloudformation-template` SOP first if the user has not already done so, because compliance checks assume a syntactically valid template

### 3. Acquire Rules File (if needed)

Determine which rules to apply.

**Constraints:**

- If the CLI or `guardpycfn` library is used, You MUST obtain a rules file because cfn-guard requires explicit rules:
  - If the user provided `rules_file_path`, You MUST use it
  - Otherwise, You MUST recommend the user download the AWS managed rules from https://github.com/aws-cloudformation/aws-guard-rules-registry
- You MUST confirm the rules file is readable before proceeding

### 4. Run Compliance Check

Execute cfn-guard against the template using the best available mechanism.

**Constraints:**

- If `cfn-guard` CLI is available, You MUST invoke it with the template and rules file:
  - Example: `cfn-guard validate --rules rules.guard --data template.yaml --output-format json`
  - You MUST use `--output-format json` for structured output
- Otherwise, if the Python `guardpycfn` library is available, You MUST invoke `guardpycfn.validate_with_guard(template_content, rules_content, verbose=True)`
- You MUST NOT modify the template content before checking because the user needs to see violations against their actual template
- You MUST capture the full output including rule IDs, resource names, resource types, and remediation messages

### 5. Present Results

Report compliance findings to the user.

**Constraints:**

- You MUST start the summary with: "Your template has X violations"
- You MUST group related violations together (e.g., all PublicAccessBlock settings for an S3 bucket)
- You MUST prioritize by severity: critical security issues first (encryption, public access), then best-practice recommendations (versioning, logging, replication)
- For repeated sub-property violations on the same resource, You MUST show them once: "Settings (A, B, C, D) must all be true"
- You MUST add context for optional features (e.g., ObjectLock and Replication may not be needed for all use cases)
- For each violation, You MUST provide the specific CloudFormation properties to add or change
- You MUST use inline YAML comments to explain why each property is needed
- You MUST NOT show entire resource definitions when only specific properties need to change
- If the template is fully compliant, You MUST confirm this clearly

### 6. Recommend Next Steps

Guide the user after compliance results.

**Constraints:**

- If critical security violations were found, You MUST recommend fixing them before deployment
- You SHOULD help the user understand which violations are mandatory fixes versus optional improvements based on their use case
- After fixes are applied, You SHOULD recommend re-running this SOP to confirm all violations are resolved
- Once compliance passes, You SHOULD recommend the `cloudformation-pre-deploy-validation` SOP for final pre-deployment readiness

## Examples

### Example Input

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: my-app-data
```

### Example Output

```
Your template has 4 violations.

**MyBucket (AWS::S3::Bucket) — Critical Security:**

1. Public access not blocked. Add:
   PublicAccessBlockConfiguration:
     BlockPublicAcls: true        # Prevents public ACLs
     BlockPublicPolicy: true      # Prevents public bucket policies
     IgnorePublicAcls: true       # Ignores existing public ACLs
     RestrictPublicBuckets: true  # Restricts public bucket access

2. Server-side encryption not configured. Add:
   BucketEncryption:
     ServerSideEncryptionConfiguration:
       - ServerSideEncryptionByDefault:
           SSEAlgorithm: aws:kms  # KMS encryption at rest

**MyBucket (AWS::S3::Bucket) — Best Practice:**

3. Versioning not enabled. Add:
   VersioningConfiguration:
     Status: Enabled              # Protects against accidental deletes

4. Access logging not configured. Add:
   LoggingConfiguration:
     DestinationBucketName: !Ref LogBucket

**Advisory — Optional Enhancements:**
ObjectLock and Replication rules also flagged. Evaluate based on your use case before adding.
```

## Troubleshooting

### High violation count on simple templates
Some rules check multiple sub-properties independently. A single missing `PublicAccessBlockConfiguration` block can produce 4 separate violations (one per sub-property). Group them mentally and fix the parent property.

### False positives for optional features
Rules like `S3_BUCKET_REPLICATION_ENABLED` and `S3_BUCKET_DEFAULT_LOCK_ENABLED` enforce best practices that may not apply to every bucket. Evaluate whether the feature is needed for your use case before adding it.

### Custom rules not found
If using a custom `rules_file_path`, ensure the file exists and follows cfn-guard rule syntax. Standalone CLI and `guardpycfn` usage both require obtaining rules separately (e.g., from the aws-guard-rules-registry).

### cfn-guard not installed
Install from https://docs.aws.amazon.com/cfn-guard/latest/ug/setting-up.html.
