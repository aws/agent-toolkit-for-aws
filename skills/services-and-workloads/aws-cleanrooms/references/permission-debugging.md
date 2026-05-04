# Clean Rooms Permission Debugging

Systematic diagnostic procedure for permission and access errors in AWS Clean Rooms.

## Parameters

- **error_message** (required): The exact error message or description of the permission failure
- **membership_id** (required): The Clean Rooms membership ID. If the user only has a collaboration ID, resolve it using `aws cleanrooms list-memberships --status ACTIVE --region ${region}` and filter by `collaborationId`.
- **collaboration_id** (optional): The Clean Rooms collaboration ID
- **region** (required): The AWS region

You MUST ask for all required parameters upfront. You MUST NOT block on optional parameters.

## Steps

### 1. Validate AWS Credentials and Region

- `aws sts get-caller-identity`
- Inform the user about the AWS account and region being used

### 2. Identify the Error Context

Classify the error: result writing failure (result receiver role), data access failure (data access service role), table association failure, or cross-account failure.

- `aws cleanrooms get-membership --membership-identifier ${membership_id} --region ${region}`
- If `collaboration_id` was not provided, extract it from the get-membership response
- `aws cleanrooms get-collaboration --collaboration-identifier ${collaboration_id} --region ${region}`
- If the error involves a protected query:
  - `aws cleanrooms list-protected-queries --membership-identifier ${membership_id} --status FAILED --region ${region}`
  - Extract `protectedQueryId`. If multiple, ask the user to confirm.
  - `aws cleanrooms get-protected-query --membership-identifier ${membership_id} --protected-query-identifier ${query_id} --region ${region}`
- For result writing failures, extract the output S3 bucket and result receiver role ARN from `defaultResultConfiguration` in the get-membership response. If a protected query is involved, also check its `outputConfiguration` as it may override the membership default.
- For data access failures involving configured tables (not ID mapping tables or training datasets), resolve to the underlying S3 bucket:
  - `aws cleanrooms list-configured-table-associations --membership-identifier ${membership_id} --region ${region}`
  - Extract `configuredTableAssociationIdentifier`. If multiple, ask the user to confirm.
  - `aws cleanrooms get-configured-table-association --membership-identifier ${membership_id} --configured-table-association-identifier ${association_id} --region ${region}`
  - Extract `configuredTableIdentifier` and the service role ARN.
  - `aws cleanrooms get-configured-table --configured-table-identifier ${configured_table_id} --region ${region}`
  - Extract `databaseName` and `tableName` from `tableReference.glue`.
  - `aws glue get-table --database-name ${database_name} --name ${table_name} --region ${region}`
  - Extract S3 bucket from `Table.StorageDescriptor.Location`
- For non-Glue/S3 data sources (Snowflake, Redshift), the permission model differs — ask the user for the data source type and use `search_documentation` for that source's access requirements.
- You MUST NOT fix permissions before completing the full diagnostic chain.

### 3. Check IAM Role Policies

- Extract `role_name` from the role ARN (segment after the last `/`). Retain the full ARN as `role_arn` for policy resource checks.
- `aws iam get-role --role-name ${role_name}`
- `aws iam list-role-policies --role-name ${role_name}`
- `aws iam list-attached-role-policies --role-name ${role_name}`
- For each inline policy: `aws iam get-role-policy --role-name ${role_name} --policy-name ${policy_name}`
- For each attached managed policy: `aws iam get-policy --policy-arn ${policy_arn}` then `aws iam get-policy-version --policy-arn ${policy_arn} --version-id ${version_id}`
- Verify trust policy allows `cleanrooms.amazonaws.com`
- For Glue/S3-backed configured tables, data access roles need: `glue:GetDatabase`, `glue:GetTable`, `glue:GetPartitions`, `glue:BatchGetPartition`, `glue:GetSchema`, `glue:GetSchemaVersion`, `s3:GetObject`, `s3:GetBucketLocation`, `s3:ListBucket`. For other data source types, use `search_documentation` for current requirements.
- Result receiver roles need: `s3:PutObject`, `s3:GetBucketLocation`, `s3:ListBucket`
- For AccessDenied on a Clean Rooms API call, also verify the caller has all dependent actions — even if they have the primary permission (e.g., `cleanrooms:StartProtectedQuery`):
  - `StartProtectedQuery`: `cleanrooms:GetCollaborationAnalysisTemplate`, `cleanrooms:GetSchema`, `s3:GetBucketLocation`, `s3:ListBucket`, `s3:PutObject`
  - `StartProtectedJob`: `cleanrooms:GetCollaborationAnalysisTemplate`, `cleanrooms:GetSchema`
  - `CreateConfiguredTableAssociation` / `UpdateConfiguredTableAssociation`: `iam:PassRole`
  - `CreateMembership` / `UpdateMembership`: `iam:PassRole`, `s3:GetBucketLocation`; also logging actions if query logging is configured: `logs:CreateLogDelivery`, `logs:CreateLogGroup`, `logs:DeleteLogDelivery`, `logs:DescribeLogGroups`, `logs:DescribeResourcePolicies`, `logs:GetLogDelivery`, `logs:ListLogDeliveries`, `logs:PutResourcePolicy`, `logs:UpdateLogDelivery`
  - `CreateConfiguredTable`: `glue:GetDatabase`, `glue:GetDatabases`, `glue:GetTable`, `glue:GetTables`, `glue:GetPartition`, `glue:GetPartitions`, `glue:BatchGetPartition`, `glue:GetSchema`, `glue:GetSchemaVersion`
- For `iam:PassRole` failures, verify the policy includes `iam:PassRole` with `iam:PassedToService` restricted to `cleanrooms.amazonaws.com`. Reference: [IAM troubleshooting](https://docs.aws.amazon.com/clean-rooms/latest/userguide/security_iam_troubleshoot.html)
- Check if `AWSCleanRoomsFullAccessNoQuerying` is attached — this policy **explicitly denies** `cleanrooms:StartProtectedQuery` and `cleanrooms:UpdateProtectedQuery` and cannot be overridden by adding permissions. Reference: [AWS managed policies](https://docs.aws.amazon.com/clean-rooms/latest/userguide/security-iam-awsmanpol.html)
- Check for explicit Deny statements that could override Allow (including `aws:PrincipalOrgID`, VPC endpoint, or IP restriction conditions)

### 4. Check S3 Bucket Policy

- `aws s3api get-bucket-policy --bucket ${bucket_name}`
- Check for explicit Allow/Deny statements for the role
- For cross-account: bucket policy MUST explicitly allow the role ARN
- `aws s3api get-bucket-encryption --bucket ${bucket_name}` — if `SSEAlgorithm` is `aws:kms`, extract the KMS key ARN from `KMSMasterKeyID`

### 5. Check KMS Key Policy (if SSE-KMS)

- `aws kms get-key-policy --key-id ${key_id} --policy-name default`
- For data access roles: verify `kms:Decrypt` and `kms:DescribeKey`
- For result receiver roles: also verify `kms:GenerateDataKey` (required to write new objects to an SSE-KMS bucket)
- For cross-account: the KMS key policy MUST explicitly allow the role from the other account
- IAM role policy MUST also include these KMS permissions for the specific key ARN

### 6. Check Lake Formation Permissions (if applicable)

You MUST perform this step for Glue/S3-backed data sources if IAM and S3 policies appear correct, as multiple issues may exist simultaneously. Lake Formation settings apply account-wide to all Glue catalog access.

- `aws lakeformation get-data-lake-settings --region ${region}`
- If `CreateDatabaseDefaultPermissions` or `CreateTableDefaultPermissions` is empty, Lake Formation enforces fine-grained access — IAM Glue permissions alone are not sufficient
- Check permissions on the specific Glue table (resolved in Step 2):
  - `aws lakeformation list-permissions --resource-type TABLE --resource '{"Table":{"DatabaseName":"${database_name}","Name":"${table_name}"}}' --region ${region}`
  - If the table has `IAM_ALLOWED_PRINCIPALS` granted, Lake Formation is not blocking — look elsewhere
  - If not, check for explicit grants to the role:
    - `aws lakeformation list-permissions --principal DataLakePrincipalIdentifier=${role_arn} --region ${region}`
    - Verify SELECT and DESCRIBE on the relevant database and table
- Reference: [Lake Formation permissions](https://docs.aws.amazon.com/lake-formation/latest/dg/onboarding-lf-permissions.html)

### 7. Check Cross-Account Trust (if applicable)

- Re-examine the `AssumeRolePolicyDocument` from the `aws iam get-role` output in Step 3
- Verify the trust policy contains `"Principal": {"Service": "cleanrooms.amazonaws.com"}` and `"Action": "sts:AssumeRole"`
- Check `Condition` block for overly restrictive keys:
  - `aws:SourceArn` — must match the collaboration or membership ARN pattern
  - `aws:SourceAccount` — must include the collaborating account ID(s)
- For cross-account roles, verify the role's account is a member of the collaboration:
  - `aws cleanrooms list-members --collaboration-identifier ${collaboration_id} --region ${region}`

### 8. Generate Diagnosis

Identify the root cause, provide the exact policy fix with CLI commands. Warn the user about security implications of permission changes and suggest least-privilege policies. Reference [service role setup docs](https://docs.aws.amazon.com/clean-rooms/latest/userguide/setting-up-roles.html).

**Expected output format:**

```
## Error Classification
- Type: [result writing | data access | table association | caller IAM | iam:PassRole | cross-account]
- Role: [role ARN]

## Diagnostic Results
1. [PASS/FAIL] IAM Role Policies
2. [PASS/FAIL] S3 Bucket Policy
3. [N/A/PASS/FAIL] KMS Key Policy
4. [N/A/PASS/FAIL] Lake Formation

## Root Cause
[One-paragraph explanation]

## Fix
[Exact policy statement + CLI command]
```
