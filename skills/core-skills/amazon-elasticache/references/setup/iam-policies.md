# IAM Policies for ElastiCache

Which permissions to generate based on what the user is doing.

## Profile Routing

| Activity | Profile | Key actions |
|----------|---------|-------------|
| Connecting from app (Lambda, ECS, EKS) | Connectivity | `elasticache:Connect` |
| Creating/modifying caches and RBAC | Provisioning | `elasticache:Create*`, `Modify*`, `Delete*` |
| Monitoring, alarms, cost review | Monitoring | `elasticache:Describe*`, `cloudwatch:PutMetricAlarm`, `ce:GetCostAndUsage` |
| Read-only inspection, debugging | Discovery | `elasticache:Describe*`, `elasticache:List*` |
| Password rotation Lambda | Rotation | `elasticache:ModifyUser`, `elasticache:DescribeUsers`, `secretsmanager:GetSecretValue`, `secretsmanager:PutSecretValue`, `secretsmanager:DescribeSecret`, `secretsmanager:UpdateSecretVersionStage`, `secretsmanager:GetRandomPassword` |

## ElastiCache-Specific Gotchas

**`elasticache:Connect` requires two ARNs.** The Resource list must include both the cache AND the user. Without both, connection is denied:

```
arn:aws:elasticache:<region>:<account-id>:serverlesscache:<cache-name>
arn:aws:elasticache:<region>:<account-id>:user:<user-id>
```

For node-based, replace `serverlesscache` with `replicationgroup`.

**KMS condition for at-rest encryption** (only if using customer-managed key):

```
"Condition": { "StringEquals": { "kms:ViaService": "elasticache.<region>.amazonaws.com" } }
```

Required KMS actions: `kms:CreateGrant`, `kms:DescribeKey`, `kms:GenerateDataKey`, `kms:Decrypt`.

**Service-linked role:** `AWSServiceRoleForElastiCache`. First-time account setup needs `iam:CreateServiceLinkedRole` with condition `"iam:AWSServiceName": "elasticache.amazonaws.com"`. Once created, remove.

**SSM tunnel document ARN:** `arn:aws:ssm:<region>::document/AWS-StartPortForwardingSessionToRemoteHost`. Include in connectivity profile only if using SSM port forwarding.

**Rotation Lambda** must call `elasticache.modify_user(UserId=..., Passwords=[new_password])`. Note: `Passwords` is a top-level parameter, not nested inside `AuthenticationMode`. The rotation Lambda also needs `secretsmanager:GetRandomPassword` on `Resource: "*"` (not scoped to a specific secret ARN).

## Combining Profiles

| Persona | Profiles |
|---------|----------|
| Developer | Discovery |
| Platform engineer | Provisioning + Discovery |
| SRE / on-call | Monitoring + Discovery |
| Application runtime | Connectivity only |

## Lambda VPC Connectivity

Any Lambda function connecting to ElastiCache in a VPC needs the `AWSLambdaVPCAccessExecutionRole` managed policy (or equivalent permissions: `ec2:CreateNetworkInterface`, `ec2:DescribeNetworkInterfaces`, `ec2:DeleteNetworkInterface`). Without these, the Lambda will time out connecting to ElastiCache.
