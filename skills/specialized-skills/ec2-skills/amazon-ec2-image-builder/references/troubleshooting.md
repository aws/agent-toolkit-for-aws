# Troubleshooting an Image Builder AMI build

(Applies to any Image Builder build, not only ones created through this skill; exit-code examples are Linux — Windows conventions are in [other-image-types.md](references/other-image-types.md).)

The single most important fact: **where the real error lives depends on which stage failed.** The approach:

1. Read `image.state.status` and `image.state.reason` (command below) — which stage failed decides everything else.
2. Match `state.reason` against the failure map. When it only names a component, go straight to the CloudWatch logs section — the APIs won't have more.
3. No matching row: localize by stage and check the pipeline's build history (the paragraph after the map), and let `list-workflow-step-executions` name the failing step.
4. Root cause found: fix it, then `retry-image` for test/distribution-stage failures or a new build otherwise. Root cause unclear: retry with the build instance kept alive (Live debugging below) and inspect it directly.

```bash
aws imagebuilder get-image --image-build-version-arn ${build_arn} --region ${region} --query "image.{state:state,name:name}"
```

## Failure map: stage → where the truth is

| What you see | Where the root cause actually is |
|---|---|
| `state.reason` says `Document arn:...:component/... failed!` (build/test stage, ApplyBuildComponents) | **CloudWatch Logs only.** The state reason names the failing component but not why. The workflow and step-execution APIs (`list-workflow-executions`, `list-workflow-step-executions`) return null messages for this class. Go to the log group below. |
| `state.reason` contains a full error message (e.g. an IAM AccessDenied during distribution/integration) | **Read `state.reason` directly** — post-build stages carry the real error there. Note the output AMI may already exist even though the image shows FAILED. |
| Build runs ~35–40 minutes, then fails with `An error occurred (InvalidInstanceId) when calling the SendCommand operation: Instances [[i-...]] not in a valid state`, or `Step <name> timed out` | The build instance can't reach SSM. See the SSM section below. |

When `state.reason` matches none of these, localize by stage — launch instance → SSM agent connect → build components → test components → create image (snapshot/Sysprep) → distribute → integrate — and check history: `list-image-pipeline-images` on the image's `sourcePipelineArn` shows whether the pipeline ever succeeded. A first-build failure points at configuration; a regression on a scheduled build points at a new base-image version or a changed component.

## CloudWatch logs (the build's full record)

Image Builder streams the build's full execution record to CloudWatch by default — the service's own workflow activity (launching the instance, polling, creating the output image) alongside every command's stdout/stderr from AWSTOE (the on-instance component runner):

```bash
aws logs tail "/aws/imagebuilder/${image_name}" --region ${region} --since 1h
```

The log group is named after the **image name** from the get-image output above (it matches the recipe name for pipeline builds; don't derive it from the build ARN — the ARN lowercases the name while the log group preserves its case). Within the group, each build writes to a stream named `<image version>/<build version>` (e.g. `1.0.0/1`) — the same two segments that end the build ARN — so when a pipeline's group holds many builds, read the stream for the failing build version. Pipeline-level events are in a separate group, `/aws/imagebuilder/pipeline/${pipeline_name}`, with date-named streams (`YYYY/MM/DD`).

A build can fail at any workflow step — launching the instance, running a component (TOE document), creating the output image — and each shape reads differently in the stream, so start from the first error and work outwards rather than hunting for one marker:

- **A failed command step** (components using the `ExecuteBash`/`ExecutePowerShell`/`ExecuteBinary` action modules): searching `ExitCode` jumps to it. **`ExitCode 126`** ("cannot execute") is usually an architecture mismatch — an x86 binary running on an arm64 instance or vice versa (exec format error) — or a file that isn't executable; for a mismatch, fix the component's download URLs or the parent image/instance types so all three agree. For other nonzero codes, read the surrounding stdout/stderr — it is the full output of the failing command.
- **Everything else carries no exit code**: components built on the other AWSTOE action modules (downloads, file operations, reboots, assertions, OS updates) each fail with their own error message, and the same goes for TOE document validation, bootstrap problems, and service-side steps failing (launch, image creation) — all surface as error text in the stream. The Common errors list below carries the recurring signatures (`Unable to bootstrap TOE`, `GetComponent ... dial tcp`, a step restarting mid-run), and `list-workflow-step-executions` names the failing step when the stream alone doesn't make it obvious.
- The logs also reference the SSM RunCommand invocations that drove each stage (`command id: <uuid>`) — `aws ssm get-command-invocation --command-id ${command_id} --instance-id ${build_instance_id}` returns that command's status and output, a useful second view when the log stream cuts off.

If S3 logging was configured on the infrastructure configuration, the bucket holds the detailed on-instance AWSTOE logs — more granular than the CloudWatch stream. Both destinations carry everything build commands print — a secret echoed by a step lands in the logs, which is why secrets are fetched at run time from AWS Secrets Manager or SSM Parameter Store, never embedded in components ([creating-images.md](references/creating-images.md) step 4).

## Live debugging on the build instance

By default Image Builder terminates the build instance on failure, so logs are all you get. To keep the instance running for SSH/SSM inspection, update the infrastructure configuration before retrying. `update-infrastructure-configuration` is a full replacement: read the current settings back with `aws imagebuilder get-infrastructure-configuration --infrastructure-configuration-arn ${infra_arn}` and re-pass every set field (instance profile, instance types, metadata options, logging, subnet/security groups) or they are dropped. If the configuration doesn't use S3 logging, drop the `--logging` line below; add `--subnet-id`/`--security-group-ids` if the configuration sets them:

```bash
aws imagebuilder update-infrastructure-configuration \
  --infrastructure-configuration-arn ${infra_arn} \
  --instance-profile-name ${name}-role \
  --instance-types ${type_a} ${type_b} \
  --instance-metadata-options httpTokens=required \
  --logging "s3Logs={s3BucketName=${log_bucket},s3KeyPrefix=imagebuilder}" \
  --no-terminate-instance-on-failure --region ${region}
```

Instance charges apply until you terminate it manually, and the kept instance still vends the build role's credentials via IMDS — terminate it as soon as inspection is done, then revert with `--terminate-instance-on-failure`.

## Common errors

- **Build fails at launch because the parent AMI can't be found or isn't available — and re-runs keep failing the same way**: the recipe is likely pinned to a hardcoded AMI ID that has since been deregistered or unshared. Repoint the recipe's parent image at an `ssm:` parameter or an Image Builder image ARN with `x.x.x` ([creating-images.md](references/creating-images.md) step 2).
- **SSM unreachable (`InvalidInstanceId ... not in a valid state` / step timeout)**: the instance has no path to Systems Manager. Causes: account has no default VPC (builds need `--subnet-id`/`--security-group-ids`), private subnet without VPC endpoints (needs ssm, ssmmessages, ec2messages, and imagebuilder, plus S3; add logs for CloudWatch logging), or the role is missing `AmazonSSMManagedInstanceCore`. A component-download failure in the logs (`GetComponent ... dial tcp ... i/o timeout`) usually points at the same connectivity gap — check the imagebuilder VPC endpoint in particular.
- **`Unable to bootstrap TOE`**: two common causes to check — the instance can't fetch the AWSTOE bootstrap from the regional `ec2imagebuilder-toe-<region>-prod` S3 bucket (S3 endpoint policy), or a hardened (CIS/STIG) base image mounts `/tmp` `noexec`; setting the recipe's `workingDirectory` somewhere executable is the usual fix for the latter.
- **`ssm:ListCommandInvocations returned terminal state Failed` at ApplyBuildComponents**: often a component rebooted the instance outside the supported reboot protocol (Windows updates are the usual suspect) — check the logs for a step that restarted mid-run, and use the exit-code protocol (194/3010) or the Reboot action module instead ([other-image-types.md](references/other-image-types.md) has the Windows specifics).
- **The `aws-cli-version-2-linux` component fails during its install steps**: the base image may already ship the AWS CLI, and the preinstalled copy collides with the component's install. Check whether the base includes it (`which aws` on the base image, or its documentation) — if so, remove the component; it's redundant there.
- **`inspector-test-linux`/`-windows` component fails with an Inspector `CreateResourceGroup` AccessDenied**: that component targets the retired Inspector Classic — remove it and use the build's native scanning instead (`--image-scanning-configuration imageScanningEnabled=true`, [creating-images.md](references/creating-images.md) step 7b).
- **Pipeline is ENABLED but scheduled dependency-update runs never happen**: compare `dateLastRun`/`dateNextRun` from `get-image-pipeline` against the cron, then check the recipe's references are update-detectable — a pinned AMI ID or full component build version never registers an update, and an `ssm:` parent image only counts if Image Builder can read the parameter at schedule time ([creating-images.md](references/creating-images.md) step 7b has the trigger requirements).
- **`You are not authorized to use the provided image` on `create-image-recipe`**: usually the CALLING role, not the build role — it needs `ec2:DescribeImages` to validate the parent image.
- **Scheduled pipeline silently stopped building**: pipelines auto-disable after consecutive failed scheduled builds (5 if unset; the pipeline's `autoDisablePolicy` sets the threshold — manual runs don't count toward it, and any success or pipeline update resets the counter). Check `get-image-pipeline` for `status: DISABLED`, fix the underlying failure, then re-enable with `update-image-pipeline` (a full replacement — re-pass every field).
- **`InsufficientInstanceCapacity`**: the infrastructure configuration accepts a list of instance types — pass 2–3 so Image Builder can pick an available one.
- **`InvalidParameterValueException` — "The provided instance profile does not exist"** on `create-infrastructure-configuration` right after creating the role: IAM propagation. Wait 10–15 seconds and retry.
- **`ResourceAlreadyExistsException` on `create-component`**: the identical document already exists — reuse it (the existing ARN is in the error). Do not delete components to resolve this.
- **`InvalidParameterValueException`**: almost always a malformed identifier. Use the exact ARN a create call returned; check the parent-image form (AMI ID, `ssm:` parameter, Image Builder ARN, or Marketplace ID — an `arn:aws:ec2:...:image/...` ARN is rejected).
- **Image FAILED after build and tests succeeded, `ssm:PutParameter` AccessDenied in `state.reason`**: the SSM-parameter distribution permissions gotcha — the service-linked role can only write under `/imagebuilder/`. Fixes in [distribution-options.md](references/distribution-options.md) (rename the parameter under `/imagebuilder/`, or use an execution role); the output AMI already exists, so publish the parameter manually or start a new build (`retry-image` doesn't cover integration-stage failures).
- **Container build FAILED after components succeeded, ECR AccessDenied/`denied` in logs**: the build role is missing `EC2InstanceProfileForImageBuilderECRContainerBuilds`, or the target ECR repository doesn't exist in that Region (see [other-image-types.md](references/other-image-types.md)).
- **Build stage succeeds but the TEST stage fails at LaunchInstance or times out**: something the build changed broke the output AMI's connectivity — commonly networking changes or hardening that blocks the SSM agent on the fresh test instance. Compare what the components changed against the SSM requirements above.
- **macOS build never launches an instance**: no capacity on the Mac dedicated host, missing Dedicated Host placement (tenancy `host` plus a host target) in the infrastructure configuration, or host family vs image architecture mismatch — the launch error appears in `image.state.reason`.
- **Windows build looks hung**: `update-windows` and Sysprep legitimately run a long time — check the CloudWatch log group is still progressing before declaring it stuck. A step restarting repeatedly in the logs is an unguarded exit-3010 reboot loop (see [other-image-types.md](references/other-image-types.md)).
- **Stuck or unwanted in-flight build**: `aws imagebuilder cancel-image-creation --image-build-version-arn ${build_arn}`. For test- or distribution-stage failures fixed in place (flaky tests, permissions, target roles), `retry-image` retries from the failed stage without rebuilding the image.
- **CLI `ParamValidation` errors on `--filters`**: quote filter values containing spaces: `--filters "name=name,values=Amazon Linux 2023 x86"`.

## A note on baked-AMI oddities

If an instance launched from the output AMI "behaves oddly" (SSM agent missing, SSH host keys regenerated, machine-id reset): that's Image Builder's post-build cleanup, which sanitizes the image before snapshotting. The SSM agent uninstall is controlled by `systemsManagerAgent.uninstallAfterBuild` in the recipe.
