# Creating images and pipelines

Contents: [Parameters](#1-gather-parameters-once) · [Base image](#2-resolve-the-base-image) · [Build role](#3-create-the-build-role) · [Components](#4-choose-components) · [Recipe](#5-create-the-image-recipe) · [Infrastructure](#6-create-the-infrastructure-configuration) · [One-off build](#7a-one-off-build) · [Pipeline](#7b-recurring-pipeline) · [Verify](#8-verify) · [Patterns](#9-patterns-golden-ami-patching-and-pipeline-chaining)

## 1. Gather parameters once

Ask for everything in one message so the build can run without stalling. (Commands in this skill use `${var}` placeholders — substitute the actual values into the command text, including inside quoted JSON; `${account_id}` is the account ID from `aws sts get-caller-identity --query Account --output text`.)

- **region** (required)
- **architecture**: x86_64 or arm64 (default x86_64). This drives the base image, component compatibility, and instance types together.
- **software to install** (their own software, plus anything an Amazon-managed component covers)
- **one-off or recurring** (see the SKILL.md decision table); if recurring, the rebuild cadence
- **distribution needs**: same Region only (default), other Regions, launch template to update, SSM parameter to publish (see [distribution-options.md](references/distribution-options.md))
- Everything else is overridable when the user asks (resource names, instance types, subnet/security group, an S3 bucket for build-log archival) — otherwise take the defaults below.

## 2. Resolve the base image

Default to Amazon Linux 2023 via the Amazon-managed Image Builder image, with the `x.x.x` wildcard so the recipe always tracks the latest version (this is also how scheduled rebuilds detect base-image updates — step 7b):

```
arn:aws:imagebuilder:${region}:aws:image/amazon-linux-2023-x86/x.x.x
arn:aws:imagebuilder:${region}:aws:image/amazon-linux-2023-arm64/x.x.x
```

Browse the Amazon-managed catalog with `aws imagebuilder list-images --owner Amazon --region ${region}`; if a create call rejects one of the AL2023 ARNs above, confirm the image name there. For an OS Image Builder doesn't publish as an Amazon-managed image, fall back to a public SSM parameter (e.g. `ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`). A specific AMI ID is a last resort for one-off builds only — it never picks up new releases or patches, so it's wrong for recurring pipelines.

Valid `--parent-image` forms (the API's term for the base image): an Image Builder image ARN, an `ssm:` parameter reference (name or ARN), an AMI ID, or a Marketplace product ID. An EC2-style image ARN (`arn:aws:ec2:...:image/ami-...`) is rejected.

Note: AL2023 ships with AWS CLI v2 preinstalled — don't add a CLI install component to an AL2023 image.

## 3. Create the build role

The build role (the IAM role on the build instance's instance profile) needs exactly two managed policies for AMI builds. Don't confuse it with the build's optional `executionRole`, the role Image Builder itself assumes to run the build's workflows — see [custom-workflows.md](references/custom-workflows.md); the flows here don't need one.

```bash
aws iam create-role --role-name ${name}-role --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"${account_id}"}}}]}'
aws iam attach-role-policy --role-name ${name}-role --policy-arn arn:aws:iam::aws:policy/EC2InstanceProfileForImageBuilder
aws iam attach-role-policy --role-name ${name}-role --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam create-instance-profile --instance-profile-name ${name}-role
aws iam add-role-to-instance-profile --instance-profile-name ${name}-role --role-name ${name}-role
# Only when using S3 build logging (step 6) - without this grant, S3 logs silently fail to deliver:
aws iam put-role-policy --role-name ${name}-role --policy-name s3-build-logs \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:PutObject","Resource":"arn:aws:s3:::${log_bucket}/imagebuilder/*"}]}'
```

- The `aws:SourceAccount` condition scopes the role to instances launched in this account (confused-deputy protection) — EC2 denies credential vending when the condition doesn't match.
- Do NOT attach `EC2InstanceProfileForImageBuilderECRContainerBuilds` — that is for container builds only and grants unnecessary ECR access.
- Wait 10–15 seconds after creating the instance profile before using it (IAM is eventually consistent).
- If the log bucket uses SSE-KMS with a customer-managed key, the S3 logging policy above also needs `{"Effect":"Allow","Action":"kms:GenerateDataKey","Resource":"${log_bucket_kms_key_arn}"}` — without it `PutObject` is denied and log delivery fails silently.

## 4. Choose components

**Check Amazon-managed components first**: `aws imagebuilder list-components --owner Amazon --region ${region}`. The registry covers common needs — `update-linux` (OS patching), `aws-cli-version-2-linux`, `amazon-cloudwatch-agent-linux`, `stig-build-linux` hardening, language runtimes, and more (confirm current names in the list-components output). Reference them by ARN; the `x.x.x` wildcard version is valid in recipes and tracks the latest version. Check the AWSTOE UpdateOS action-module documentation for the OSes `update-linux` covers before adding it — it doesn't cover AL2023, which patches via base-image refreshes instead (see step 9).

Write a custom component only for the user's own software:

```bash
aws imagebuilder create-component --name ${name} --semantic-version 1.0.0 --platform Linux --data '<yaml>' --region ${region}
```

- Pass the YAML via `--data` (inline or `file://`). `--uri` requires a prior S3 upload. To validate a document without creating anything, add `--dry-run`: a valid document returns `DryRunOperationException` ("Request would have succeeded"), an invalid one returns the actual validation error. Minimal component document:

```yaml
name: ${component_name}
description: Installs ${software}
schemaVersion: 1.0
phases:
  - name: build
    steps:
      - name: Install
        action: ExecuteBash
        inputs:
          commands:
            - <install commands>
  - name: validate
    steps:
      - name: Verify
        action: ExecuteBash
        inputs:
          commands:
            - <a command that fails if the install is broken>
```

- Make download URLs and binaries match the target architecture.
- Never put secrets (API keys, license tokens, passwords) in component YAML or echo them in commands: component documents are retrievable via `get-component`, and every command's stdout/stderr streams to CloudWatch and the S3 log bucket. Have instances fetch secrets at run time from AWS Secrets Manager or SSM Parameter Store (SecureString).
- To reboot mid-build (kernel updates, agent installs), exit a build step with code `194`: the instance reboots and the build re-runs that step from the top, so guard it with a marker file to avoid a reboot loop. A plain `reboot` command fails the step instead of resuming. The Amazon-managed `update-linux` component handles its own reboots.
- Versioning behavior: re-creating the same name+version with **identical** content returns `ResourceAlreadyExistsException` — the document already exists, reuse the ARN from the error or from `list-components`. Re-creating with **changed** content silently creates a new build version (`/1.0.0/2`), and a recipe that references the version without a build suffix (`.../my-component/1.0.0`) resolves to the latest build version at each build. Bump the semantic version only when you want a new pinnable version. Never delete a component to "fix" this.
- Capture `componentBuildVersionArn` from each response (create responses also include `latestVersionReferences` with ready-made wildcard ARNs).
- To test the finished image, give a component a `test` phase: it runs in the TEST stage on a fresh instance launched from the new AMI, and the image only distributes if tests pass (Amazon-managed test components exist too, e.g. `reboot-test-linux`). Skip the test stage with `--image-tests-configuration imageTestsEnabled=false` on the build if speed matters more.
- For the full component document schema (action modules beyond ExecuteBash, step chaining, test phases), see the [AWSTOE component documentation](https://docs.aws.amazon.com/imagebuilder/latest/userguide/toe-use-documents.html).

## 5. Create the image recipe

```bash
aws imagebuilder create-image-recipe --name ${name}-recipe --semantic-version 1.0.0 \
  --parent-image "${parent_image}" \
  --components "componentArn=${component_arn_1}" "componentArn=${component_arn_2}" \
  --block-device-mappings '[{"deviceName":"/dev/xvda","ebs":{"encrypted":true,"deleteOnTermination":true}}]' \
  --region ${region}
```

- The example encrypts the root volume with the account's default EBS key; add `"kmsKeyId":"${kms_key_arn}"` for a customer-managed key (required if the AMI will be shared cross-account — the default EBS key can't be). Block device mappings are also where root volume size and type are set. Distribution-side `kmsKeyId` only encrypts copies made to other Regions or accounts.
- Recipes are immutable. To pick up changed components or settings, create a new recipe version — pass either an explicit next version (`1.0.1`) or a wildcard patch (`--semantic-version 1.0.x`), which the create call auto-assigns to the next free patch (wildcards auto-assign in create requests and resolve to the latest version in ARN references — see the Image Builder semantic versioning documentation). A pipeline that references the recipe with the `x.x.x` wildcard (`arn:...:image-recipe/${name}-recipe/x.x.x`) builds from the latest recipe version automatically; one pinned to a specific version needs repointing with `update-image-pipeline`.
- `update-image-pipeline` is a **full replacement**: re-pass every field. Omitting `--status` resets a DISABLED pipeline to ENABLED; omitting `--schedule` makes the pipeline manual.

## 6. Create the infrastructure configuration

```bash
aws imagebuilder create-infrastructure-configuration --name ${name}-infra \
  --instance-profile-name ${name}-role \
  --instance-types ${type_a} ${type_b} \
  --instance-metadata-options httpTokens=required \
  --logging "s3Logs={s3BucketName=${log_bucket},s3KeyPrefix=imagebuilder}" \
  --region ${region}
```

Omit the `--logging` line unless the user wants the detailed on-instance AWSTOE logs delivered to an S3 bucket they own — these are more granular than the CloudWatch stream (which is on by default regardless) and useful for audits and deep debugging.

- Pass **two or more instance types** matching the architecture — pick current-generation general-purpose types from `aws ec2 describe-instance-types --filters Name=current-generation,Values=true Name=processor-info.supported-architecture,Values=${architecture}`. Image Builder picks by availability, which avoids capacity failures.
- `httpTokens=required` enforces IMDSv2 on build instances (AWS security best practice).
- S3 logging requires the logging grants from step 3. Logs contain the full output of every build command — use a bucket with Block Public Access enabled, server-side encryption enabled (SSE-KMS recommended), a bucket policy that denies requests where `aws:SecureTransport` is `false` to enforce TLS in transit, and S3 server access logging where log access must be auditable.
- For the CloudWatch log group, a customer-managed key is recommended for the same reason. To have it encrypted from the first build, pre-create the group and associate the key up front (the build writes into a pre-existing group): `aws logs create-log-group --log-group-name /aws/imagebuilder/${name}-recipe` then `aws logs associate-kms-key --log-group-name /aws/imagebuilder/${name}-recipe --kms-key-id ${kms_key_arn}`. Otherwise the group is created automatically with default at-rest encryption and the key can be associated after. The key's policy must grant the `logs.${region}.amazonaws.com` service principal use of the key, scoped with the `kms:EncryptionContext:aws:logs:arn` condition to this account's log groups — the CloudWatch Logs encryption documentation has the exact statement.
- The build instance must reach Systems Manager. With a default VPC this works out of the box. Otherwise pass `--subnet-id` and `--security-group-ids` for a subnet with a route to SSM — a private subnet with VPC endpoints for ssm, ssmmessages, ec2messages, and imagebuilder, plus S3 (add logs for CloudWatch logging) is the preferred production setup since the build instance then needs no internet path; a NAT gateway or a public IP also works. The security group needs no inbound rules — outbound HTTPS (443) is sufficient.
- Optional: `--sns-topic-arn` for build-completion notifications. Notification payloads include resource names, so use an encrypted topic with a restricted policy, and confirm the topic's existing subscribers are authorized recipients before attaching it (`aws sns list-subscriptions-by-topic --topic-arn ${topic_arn}`). Check encryption with `aws sns get-topic-attributes --topic-arn ${topic_arn} --query Attributes.KmsMasterKeyId`; when creating a topic, always pass `--attributes KmsMasterKeyId=${kms_key_id}` — prefer a customer-managed key for production (key-policy control and auditable key use), with `alias/aws/sns` as the fallback minimum. With an SSE-KMS topic, grant Image Builder's service-linked role access in the key policy — otherwise publishes fail silently.
- `--terminate-instance-on-failure` defaults to true (see [troubleshooting.md](references/troubleshooting.md) for when to set false).

If distribution is needed (launch template updates, SSM parameter, other Regions), create the distribution configuration now per [distribution-options.md](references/distribution-options.md) and capture `${dist_arn}`.

## 7a. One-off build

No pipeline needed:

```bash
aws imagebuilder create-image --image-recipe-arn ${recipe_arn} \
  --infrastructure-configuration-arn ${infra_arn} \
  --region ${region}
```

Add `--distribution-configuration-arn ${dist_arn}` if distribution was configured in step 6. This is `aws imagebuilder create-image` — not `aws ec2 create-image`, which snapshots a running instance. Capture `imageBuildVersionArn` from the response.

## 7b. Recurring pipeline

```bash
aws imagebuilder create-image-pipeline --name ${name} \
  --image-recipe-arn ${recipe_arn} \
  --infrastructure-configuration-arn ${infra_arn} \
  --schedule 'scheduleExpression="cron(0 9 ? * mon *)",pipelineExecutionStartCondition=EXPRESSION_MATCH_AND_DEPENDENCY_UPDATES_AVAILABLE' \
  --status ENABLED --region ${region}
aws imagebuilder start-image-pipeline-execution --image-pipeline-arn ${pipeline_arn} --region ${region}
```

Add `--distribution-configuration-arn ${dist_arn}` if distribution was configured in step 6. Capture `${pipeline_arn}` from the create response; `start-image-pipeline-execution` returns `imageBuildVersionArn` — capture it as the build ARN for step 8.

**Schedules.** Pipelines only run at their cron times — a dependency update never starts a build by itself. The start condition decides what happens at each tick:

- `EXPRESSION_MATCH_AND_DEPENDENCY_UPDATES_AVAILABLE` (the default) runs the scheduled build only if a dependency updated since the last build, and skips it otherwise.
  - Counts as an update: a new version behind an `x.x.x` wildcard reference (the default Amazon-managed parent image and Amazon-managed components), or a changed `ssm:` parent-image value — provided Image Builder can read the parameter at schedule time (public `/aws/service/*` parameters and parameters under `/imagebuilder/` by default; other names need an execution role on the pipeline that can read the parameter).
  - Never counts: a recipe pinned to an AMI ID or to full component build versions, or an `ssm:` parameter the pipeline can't read — such a pipeline never sees an update and never runs under this condition.
- `EXPRESSION_MATCH_ONLY` runs the build on every cron tick — use it for a guaranteed cadence regardless of updates.
- Scheduled pipelines auto-disable after consecutive failed scheduled builds (5 if unset) — see [troubleshooting.md](references/troubleshooting.md). To change a schedule later, see the `update-image-pipeline` note in step 5 (full replacement).

**Vulnerability scanning** (optional, also valid on `create-image` for one-off builds): add `--image-scanning-configuration imageScanningEnabled=true`. Two things to tell the user first: Amazon Inspector must already be activated for EC2 in the account (a paid, account-level decision — creation fails with a dependency error otherwise), and scan results are a findings snapshot in Inspector — scanning does not gate or fail the build (to get alerted on findings, use Inspector's own EventBridge events; see the Inspector documentation).

## 8. Verify

```bash
aws imagebuilder get-image --image-build-version-arn ${build_arn} --region ${region}
```

Confirm `image.state.status` is an in-flight state: `PENDING`, `CREATING`, `BUILDING`, `TESTING`, `DISTRIBUTING`, or `INTEGRATING`. Do not wait for completion (builds typically take 15–45 minutes); give the user this command to check later, and note the output AMI appears under `image.outputResources.amis` when `AVAILABLE`. If the status is `FAILED`, go to [troubleshooting.md](references/troubleshooting.md).

## 9. Patterns: golden-AMI patching and pipeline chaining

**Automatic OS patching.** Combine the 7b schedule with launch-template distribution (see [distribution-options.md](references/distribution-options.md)) and patching runs itself: each new base-image release behind the wildcard parent is picked up at the next scheduled run, and Auto Scaling groups roll onto each new AMI. That base-image refresh is the patching mechanism for the default AL2023 base, which `update-linux` doesn't cover (see step 4). For distros that `update-linux` covers, add it to the recipe as well, to pull the latest security updates between base-image releases. Note: every scheduled rebuild leaves the previous AMI and its snapshot behind — retiring old AMIs is out of scope here (see the Related skills table in SKILL.md).

**Pipeline chaining (golden-base → app image).** The direct form: the downstream recipe uses the upstream pipeline's output image as its parent, with the `x.x.x` wildcard (`arn:aws:imagebuilder:${region}:${account_id}:image/${upstream_image_name}/x.x.x`); downstream pipelines with the dependency-updates start condition pick up each new upstream build at their next scheduled run. When consumers live outside Image Builder, publish to SSM instead — an `ssm:/imagebuilder/${name}/latest` parent also registers updates (see [distribution-options.md](references/distribution-options.md)).
