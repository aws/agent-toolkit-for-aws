# Clean Rooms ML Custom Model Logging Debugging

Systematic diagnostic procedure for CloudWatch log publishing failures in Clean Rooms ML custom model training and inference jobs.

## Parameters

- **membership_id** (required): The Clean Rooms membership ID
- **region** (required): The AWS region
- **trained_model_arn** (optional): ARN of the specific trained model or inference job

You MUST ask for all required parameters upfront.

## Steps

### 1. Validate AWS Credentials and Region

- `aws sts get-caller-identity`
- Inform the user about the AWS account and region being used

### 2. Check Trained Model or Inference Job Status

Determine the resource type by inspecting the ARN: if it contains `trained-model-inference-job`, use the inference job call; otherwise use the trained model call. If `ResourceNotFoundException`, try the other.

- `aws cleanroomsml get-trained-model --membership-identifier ${membership_id} --trained-model-arn ${trained_model_arn} --region ${region}`
- `aws cleanroomsml get-trained-model-inference-job --membership-identifier ${membership_id} --trained-model-inference-job-arn ${trained_model_arn} --region ${region}`

If no ARN provided, list recent resources:

- `aws cleanroomsml list-trained-models --membership-identifier ${membership_id} --region ${region}`
- `aws cleanroomsml list-trained-model-inference-jobs --membership-identifier ${membership_id} --region ${region}`

If multiple returned, present the list and ask the user to confirm which to investigate.

Extract: `logsStatus`, `logsStatusDetails`, `configuredModelAlgorithmAssociationArn`, job status.

If `configuredModelAlgorithmAssociationArn` is not in the response, use: `aws cleanroomsml list-configured-model-algorithm-associations --membership-identifier ${membership_id} --region ${region}`. If multiple associations are returned, present the list and ask the user to confirm which one is relevant to the resource under investigation.

### 3. Check Configured Model Algorithm Association Privacy Configuration

- `aws cleanroomsml get-configured-model-algorithm-association --membership-identifier ${membership_id} --configured-model-algorithm-association-arn ${configured_model_algorithm_association_arn} --region ${region}`
- Check `privacyConfiguration.policies` for:
  - `trainedModels.containerLogs` with `allowedAccountIds` (for training)
  - `trainedModelInferenceJobs.containerLogs` with `allowedAccountIds` (for inference)
- You MUST verify the customer's account ID is included in `allowedAccountIds`
- If `containerLogs` is empty/missing, flag this as a likely root cause — but you MUST continue through all remaining steps before generating the diagnosis, as multiple issues may exist simultaneously
- Explain that logging is configured in CreateConfiguredModelAlgorithmAssociation, NOT CreateTrainedModel

### 4. Check ML Configuration

- `aws cleanroomsml get-ml-configuration --membership-identifier ${membership_id} --region ${region}`
- Extract `defaultOutputLocation.roleArn` — this role publishes logs
- If no ML Configuration exists (ResourceNotFoundException), flag this as a root cause — the user must create one via PutMLConfiguration. Skip Step 5 (role permissions cannot be checked without a role ARN) and continue to Step 6, as multiple issues may exist simultaneously.

### 5. Check ML Configuration Role CloudWatch Permissions

- `aws iam get-role --role-name ${role_name}`
- `aws iam list-role-policies --role-name ${role_name}`
- `aws iam list-attached-role-policies --role-name ${role_name}`
- For each inline policy: `aws iam get-role-policy --role-name ${role_name} --policy-name ${policy_name}`
- For each attached managed policy: `aws iam get-policy --policy-arn ${policy_arn}` then `aws iam get-policy-version --policy-arn ${policy_arn} --version-id ${version_id}`
- Required permissions: `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` on `arn:aws:logs:*:*:log-group:/aws/cleanroomsml/*`
- Also check `cloudwatch:PutMetricData` (requires `"Resource": "*"`) for training metrics
- Trust policy must allow `cleanrooms-ml.amazonaws.com`

### 6. Check CloudWatch Log Groups

- `aws logs describe-log-groups --log-group-name-prefix /aws/cleanroomsml/TrainedModels --region ${region}`
- `aws logs describe-log-groups --log-group-name-prefix /aws/cleanroomsml/TrainedModelInferenceJobs --region ${region}`
- If groups exist, check streams using the discovered log group name:
  - `aws logs describe-log-streams --log-group-name ${log_group_name} --order-by LastEventTime --descending --max-items 5 --region ${region}`
- If groups don't exist, this may indicate missing `logs:CreateLogGroup` permission. Cross-reference with logsStatus and privacy config.

### 7. Log Publishing Status Interpretation

Only if logsStatus is PUBLISH_FAILED:

- Each member sees their own logsStatus based on their account's log publishing
- Do NOT suggest checking other accounts
- Accounts without an ML Configuration role show "Failed to publish logs as no ML Config role is set"
- Direct customer to check their ML Configuration role permissions (Step 5)

### 8. Generate Diagnosis

Identify root cause (typically: missing privacy config, missing CloudWatch permissions, missing ML Configuration, or missing trust policy). Provide exact fix with CLI commands. Reference [ML roles docs](https://docs.aws.amazon.com/clean-rooms/latest/userguide/ml-roles.html) and [LogsConfigurationPolicy API](https://docs.aws.amazon.com/cleanrooms-ml/latest/APIReference/API_LogsConfigurationPolicy.html). Note that a new job must be run after fixing — existing failed jobs won't retroactively publish logs.

**Expected output format:**

```
## Current Status
- Resource: [name] ([status])
- Logs status: [PUBLISH_FAILED/PUBLISH_SUCCEEDED]

## Diagnostic Results
1. [PASS/FAIL] Privacy Config (containerLogs)
2. [PASS/FAIL] ML Configuration exists
3. [N/A/PASS/FAIL] ML Config Role Permissions
4. [PASS/FAIL] Log Groups

## Root Cause
[One-paragraph explanation]

## Fix
[Exact policy statement + CLI command]
```
