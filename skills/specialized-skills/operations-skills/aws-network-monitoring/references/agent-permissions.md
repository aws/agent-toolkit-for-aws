# Agent Permissions Setup

## Required Policy

Attach the AWS managed policy `CloudWatchNetworkFlowMonitorAgentPublishPolicy` to the
instance role used by your EC2 instances. Without this policy, the agent installs
successfully but cannot publish metrics.

**Policy ARN:** `arn:aws:iam::aws:policy/CloudWatchNetworkFlowMonitorAgentPublishPolicy`

## Attach to existing role

Find the instance role:

```bash
PROFILE_ARN=$(aws ec2 describe-instances \
  --instance-ids <instance-id> \
  --query "Reservations[].Instances[].IamInstanceProfile.Arn" \
  --output text)

PROFILE_NAME=$(echo $PROFILE_ARN | awk -F/ '{print $NF}')

ROLE_NAME=$(aws iam get-instance-profile \
  --instance-profile-name $PROFILE_NAME \
  --query "InstanceProfile.Roles[0].RoleName" \
  --output text)
```

Attach the policy:

```bash
aws iam attach-role-policy \
  --role-name $ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/CloudWatchNetworkFlowMonitorAgentPublishPolicy
```

## Instance has no instance role yet

If the EC2 instance has no instance profile attached, use the
`setting-up-ec2-instance-profiles` skill first to create the instance role and
attach `AmazonSSMManagedInstanceCore`. Then return here and follow
"Attach to existing role" above to add
`CloudWatchNetworkFlowMonitorAgentPublishPolicy`.

## Verify

```bash
aws iam list-attached-role-policies \
  --role-name <role-name> \
  --query "AttachedPolicies[?PolicyName=='CloudWatchNetworkFlowMonitorAgentPublishPolicy']" \
  --output table
```
