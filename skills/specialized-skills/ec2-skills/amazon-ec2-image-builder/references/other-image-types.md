# Windows, macOS, and container images

The [creating-images.md](references/creating-images.md) flow (role → components → recipe → infrastructure → build/pipeline) applies to all of these — this file covers only what changes per image type.

## Windows AMIs

- **Base image:** Amazon-managed Windows Server images cover multiple releases (Core and Full, plus SQL and hardened variants). Resolve the image name with `aws imagebuilder list-images --owner Amazon --filters "name=platform,values=Windows"` and take the name segment from the output rather than assuming a naming pattern, then reference it with the `x.x.x` wildcard (e.g. `arn:aws:imagebuilder:${region}:aws:image/windows-server-${release}-english-full-base-x86/x.x.x`).
- **Components:** use `--platform Windows`; steps use `ExecutePowerShell` (or `ExecuteBinary`), and the Amazon-managed `update-windows` component covers OS patching.
- **Reboots:** exit code `3010` is the Windows equivalent of Linux's 194 — the instance reboots and the build re-runs that step from the top, so guard it with a marker file. `update-windows` manages its own reboots.
- **Expectations:** Windows build time varies widely with the patch load — `update-windows` can dominate the run, and Image Builder runs Sysprep automatically before snapshotting. Windows license cost is part of the instance/AMI, nothing extra to configure.

## macOS AMIs

- **Hard prerequisite:** macOS builds run only on EC2 Mac **Dedicated Hosts** — without an allocated host and `tenancy=host` placement, macOS builds cannot launch an instance.
  - Allocate a host: `aws ec2 allocate-hosts --instance-type ${mac_instance_type} ...`. List current Mac families with `aws ec2 describe-instance-types --filters "Name=instance-type,Values=mac*"`; the family must match the target architecture. Dedicated Host minimum-allocation billing applies — see the EC2 Dedicated Hosts documentation for billing terms.
  - Set the infrastructure configuration's `placement` to tenancy `host` and target the host. Default to a specific `hostId` (simplest); use a **host resource group** (`hostResourceGroupArn` — a License Manager / Resource Groups setup, follow the AWS docs for that part) when License Manager governs the fleet, or host auto-placement when multiple hosts are pooled.
- **Base image:** Amazon-managed macOS images — browse with `aws imagebuilder list-images --owner Amazon --filters "name=platform,values=macOS"` and match the host's architecture.
- Components use `--platform macOS` with `ExecuteBash`. Everything else follows the standard flow; budget for long builds and the dedicated-host cost.

## Container images (Docker to ECR)

- **Recipe:** use a container recipe instead of an image recipe. Default the parent to an Amazon-managed Image Builder container image (browse with `aws imagebuilder list-images --owner Amazon --filters "name=type,values=DOCKER"`); a DockerHub or ECR image is acceptable when the user explicitly chooses one. the output goes to an ECR repository you create first (`create-container-recipe` validates the repository exists and fails with `ResourceNotFoundException` otherwise) — `aws ecr create-repository --repository-name ${ecr_repo} --encryption-configuration encryptionType=KMS,kmsKey=${kms_key_arn} --region ${region}`. A customer-managed key is the production recommendation (auditability and key-policy control); drop `,kmsKey=${kms_key_arn}` to fall back to the AWS-managed `aws/ecr` key. ECR uses AES-256 if the encryption configuration is omitted entirely:

```bash
aws imagebuilder create-container-recipe --name ${name}-recipe --semantic-version 1.0.0 \
  --container-type DOCKER --parent-image "arn:aws:imagebuilder:${region}:aws:image/amazon-linux-2023-x86-latest/x.x.x" \
  --components "componentArn=${component_arn}" \
  --instance-configuration '{"blockDeviceMappings":[{"deviceName":"/dev/xvda","ebs":{"encrypted":true,"deleteOnTermination":true}}]}' \
  --dockerfile-template-data 'FROM {{{ imagebuilder:parentImage }}}
{{{ imagebuilder:environments }}}
{{{ imagebuilder:components }}}' \
  --target-repository "service=ECR,repositoryName=${ecr_repo}" --region ${region}
```

- **Build instance storage:** the `--instance-configuration` block device mapping in the example encrypts the build instance's working storage — the container counterpart of the AMI recipe's encrypted root volume in creating-images.md step 5.
- **Build role:** container builds are the one case that needs the third managed policy — attach `EC2InstanceProfileForImageBuilderECRContainerBuilds` to the build role (the same policy [creating-images.md](references/creating-images.md) step 3 says to leave off for AMI-only builds).
- **Build and pipeline:** pass `--container-recipe-arn` instead of `--image-recipe-arn` on `create-image`/`create-image-pipeline`; infrastructure configuration and schedules are unchanged. When verifying, the output appears under `outputResources.containers` rather than `.amis`.
- **Distribution:** use `containerDistributionConfiguration` (target ECR repositories per Region) in the distribution configuration instead of the AMI settings in [distribution-options.md](references/distribution-options.md).
