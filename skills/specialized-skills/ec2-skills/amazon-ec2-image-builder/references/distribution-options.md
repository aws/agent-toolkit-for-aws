# Distribution options

How the output AMI gets where it's needed. All of these live in a distribution configuration attached to the pipeline or one-off build. Default with no distribution configuration: the AMI lands in the build Region only, which is right for most users — treat everything below as opt-in. Note: the output AMI's encryption comes from the recipe's block device mappings, not from the distribution configuration — see [Cross-account sharing and encryption](#cross-account-sharing-and-encryption).

## Launch templates (Auto Scaling groups pick up new AMIs automatically)

This is the default recommendation for Auto Scaling groups: put the launch template in the distribution configuration. Never create launch template versions manually after each build:

```bash
aws imagebuilder create-distribution-configuration --name ${name}-dist \
  --distributions '[{"region":"${region}","amiDistributionConfiguration":{"name":"${name}-{{imagebuilder:buildDate}}"},"launchTemplateConfigurations":[{"launchTemplateId":"${lt_id}","setDefaultVersion":true}]}]' \
  --region ${region}
```

After each successful build, Image Builder's service-linked role creates a new launch template version pointing at the new AMI and sets it as the default. An Auto Scaling group referencing `$Default` (or `$Latest`) picks it up with no manual steps.

- Verify which version the ASG uses: `aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names ${asg} --query "AutoScalingGroups[0].LaunchTemplate"`. If it pins a numbered version, switch it: `aws autoscaling update-auto-scaling-group --auto-scaling-group-name ${asg} --launch-template "LaunchTemplateId=${lt_id},Version=\$Default"`.
- This means each new AMI reaches whatever uses that launch template with no approval step — confirm the user wants automatic rollout, and point the distribution at a staging launch template if they don't.
- Alternative: `resolve:ssm` in the template's ImageId pointing at a parameter this pipeline publishes — use it when the launch template is managed through IaC.

## SSM parameters (publish the AMI ID for downstream automation)

```json
"ssmParameterConfigurations": [{"parameterName": "/imagebuilder/${name}/latest", "dataType": "aws:ec2:image"}]
```

- `dataType: aws:ec2:image` is recommended — SSM validates the value is a real AMI ID.
- **Permissions gotcha (fails after a successful build):** Image Builder's service-linked role can only write parameters under the `/imagebuilder/` prefix.
  - Simplest fix: name the parameter under `/imagebuilder/` (zero IAM changes). For any other name, create an Image Builder execution role with the `EC2ImageBuilderExecutionPolicy` managed policy plus an `ssm:PutParameter` statement scoped to that parameter's ARN (and `ec2:DescribeImages` for the `aws:ec2:image` data type), and pass it as the build's execution role ([custom-workflows.md](references/custom-workflows.md) shows the create-role command and trust policy).
  - If the permission is missing, the build and tests succeed and the image then goes `FAILED` at the integration stage with an `ssm:PutParameter` AccessDenied in `image.state.reason` — and the AMI still exists despite the FAILED state. After fixing the permissions, publish the parameter yourself from the existing AMI (`aws ssm put-parameter --name ${param} --type String --data-type aws:ec2:image --value ${ami_id}`) or start a new build. Note `retry-image` does not cover this case — it only retries test- and distribution-stage failures, not the integration stage.
- The `/imagebuilder/` prefix matters twice: it's what the service-linked role can publish to AND read at schedule time — so a published parameter can also feed a downstream pipeline's parent image (pipeline chaining — see creating-images.md, Patterns).

## Other Regions

Add more entries to `distributions`, one per Region, each with its own `amiDistributionConfiguration`; the first entry is the build Region. Note the cost: every Region stores its own snapshot copy. Only add Regions the user actually launches in. Tag output AMIs for governance/cost allocation with `"amiTags": {"team": "${team}"}` inside `amiDistributionConfiguration`.

## Cross-account sharing and encryption

Cross-account distribution of an encrypted AMI requires a customer-managed key in the recipe's block device mappings, planned before the first build — the default AWS-managed EBS key can't be shared ([creating-images.md](references/creating-images.md) step 5). Two forms, both in `amiDistributionConfiguration`:

- `launchPermission` shares the AMI in place. Always list explicit account IDs — `"launchPermission": {"userIds": ["${consumer_account_id}"]}` inside `amiDistributionConfiguration` — a launch permission opened to all accounts makes the AMI public, which is never the default.
- `targetAccountIds` copies the AMI into each target account. The copy requires the `EC2ImageBuilderDistributionCrossAccountRole` role (with `Ec2ImageBuilderCrossAccountDistributionAccess`) to exist in every target account first, created per the AWS cross-account distribution documentation — its trust policy is scoped to the source account, so only that account can assume it — without it the build succeeds and distribution then fails with AccessDenied in `image.state.reason` (fix the role, then `retry-image`). An EventBridge rule on `EC2 Image Builder Image State Change` events surfaces these failures promptly (see SKILL.md, Security considerations).

`kmsKeyId` in this file only encrypts copies made to other Regions or accounts — the output AMI's own encryption comes from the recipe, per the requirement above. A distribution failure quoting `Snapshots encrypted with the AWS Managed CMK can't be shared` is this constraint surfacing — re-bake with a customer-managed key in the recipe. KMS-encrypted copies and License Manager association otherwise follow the AWS documentation.
