# IaC Deployment Best Practices

Operational guidance for deploying ElastiCache via CloudFormation, Terraform, and CDK. For resource names, property mappings, and endpoint attributes, see `iac-reference.md`.

## API Rate Limiting During Deployment

ElastiCache control-plane APIs enforce throttle limits. Deploying multiple caches in a single stack or account can trigger `ThrottlingException`.

**Mitigation strategies:**

* **DependsOn chains**: When a single CFN stack creates multiple caches, add explicit `DependsOn` between them so they provision sequentially rather than in parallel.
* **StackSets with MaxConcurrentCount**: For multi-account or multi-region rollouts, set `MaxConcurrentCount: 1` (or a low value) in StackSet operation preferences to stagger deployments.
* **Terraform parallelism**: Use `terraform apply -parallelism=1` or add `depends_on` between cache resources to serialize creation.
* **Retry with backoff**: If using custom scripts or CI/CD wrappers, implement exponential backoff on throttle errors.

## Common CloudFormation Failures

### Stack stuck in UPDATE_ROLLBACK_FAILED

A stack can get stuck when a rollback itself fails (for example, a resource that was modified outside of CFN).

**Resolution:**

1. Open the CloudFormation console or run `aws cloudformation describe-stack-events` to identify the failed resource.
2. Run `aws cloudformation continue-update-rollback --stack-name <name>` to retry.
3. If a specific resource cannot roll back, skip it: `aws cloudformation continue-update-rollback --stack-name <name> --resources-to-skip <logical-id>`.
4. After the rollback completes, fix the template and update again.

### Deletion fails due to VPC endpoints

Serverless caches create VPC endpoints in the associated subnets. If these endpoints still exist when the stack tries to delete the cache or its networking resources, deletion fails.

**Resolution:**

1. List endpoints: `aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=<vpc-id>` and identify ElastiCache-related endpoints.
2. Delete them: `aws ec2 delete-vpc-endpoints --vpc-endpoint-ids <id1> <id2>`.
3. Retry the stack deletion.

**Prevention:** In CFN templates, place the cache resource with an explicit `DependsOn` on the VPC/subnet resources so CFN deletes the cache (and its endpoints) before attempting to remove networking resources.

### CREATE_FAILED on ReplicationGroup

Common causes:

* Subnet group references subnets in a single AZ (Multi-AZ requires at least 2 AZs).
* Security group does not allow inbound on port 6379.
* Insufficient IP addresses in the subnet for the requested node count.

## Template Structure Best Practices

### Separate parameter groups as their own resources

Define `AWS::ElastiCache::ParameterGroup` (CFN) or `aws_elasticache_parameter_group` (Terraform) as standalone resources rather than relying on defaults. This allows parameter changes without replacing the cache.

### Export endpoints via Outputs

Always export cache endpoints so dependent stacks or applications can reference them:

```yaml
Outputs:
  CacheEndpoint:
    # For AWS::ElastiCache::ServerlessCache: !GetAtt Cache.Endpoint.Address
    # For AWS::ElastiCache::ReplicationGroup (CME): !GetAtt Cache.ConfigurationEndPoint.Address
    # For AWS::ElastiCache::ReplicationGroup (CMD): !GetAtt Cache.PrimaryEndPoint.Address
    Value: !GetAtt Cache.PrimaryEndPoint.Address
    Export:
      Name: !Sub "${AWS::StackName}-cache-endpoint"
```

### Multi-environment templates with Conditions

Use `Conditions` and `Mappings` to manage dev/staging/prod from a single template:

```yaml
Parameters:
  Environment:
    Type: String
    AllowedValues: [dev, staging, prod]
Conditions:
  IsProd: !Equals [!Ref Environment, prod]
```

Then use `!If [IsProd, ...]` to vary node types, replica counts, snapshot retention, and cost limits by environment. For serverless, vary `CacheUsageLimits` (lower maximums in dev to control cost).

### Auto Scaling policies via CloudFormation

For node-based replication groups, define auto-scaling policies directly in your templates using `AWS::ApplicationAutoScaling::ScalableTarget` and `AWS::ApplicationAutoScaling::ScalingPolicy`. You can scale replicas (`elasticache:replication-group:Replicas`) or shards (`elasticache:replication-group:NodeGroups`). For example:

```yaml
ScalingTarget:
  Type: 'AWS::ApplicationAutoScaling::ScalableTarget'
  Properties:
    MaxCapacity: 5
    MinCapacity: 1
    ResourceId: !Sub replication-group/${MyReplicationGroup}
    ScalableDimension: 'elasticache:replication-group:Replicas'
    ServiceNamespace: elasticache

ScalingPolicy:
  Type: 'AWS::ApplicationAutoScaling::ScalingPolicy'
  Properties:
    ScalingTargetId: !Ref ScalingTarget
    ServiceNamespace: elasticache
    PolicyName: target-tracking-cpu
    PolicyType: TargetTrackingScaling
    ScalableDimension: 'elasticache:replication-group:Replicas'
    TargetTrackingScalingPolicyConfiguration:
      PredefinedMetricSpecification:
        PredefinedMetricType: ElastiCacheReplicaEngineCPUUtilization
      TargetValue: 60
```

> **Note:** The `ScalableTarget` supports an optional `RoleARN` property. If omitted, Application Auto Scaling uses the service-linked role `AWSServiceRoleForApplicationAutoScaling_ElastiCacheRG`, which is created automatically. If the service-linked role does not yet exist in your account, either add `RoleARN` explicitly or ensure the deploying principal has `iam:CreateServiceLinkedRole` permission.

### Terraform workspaces

Use Terraform workspaces or tfvars files per environment. Define cache configuration as variables with environment-specific defaults:

```hcl
variable "node_type" {
  default = "cache.t4g.micro"  # overridden in prod.tfvars
}
```

## Pre-Deployment Checklist

* Subnets span at least 2 AZs (required for Multi-AZ on node-based)
* Security group allows inbound TCP 6379 (and 6380 for serverless read port on the same endpoint hostname)
* IAM role used by CFN/Terraform has least-privilege ElastiCache actions scoped to provisioning: `elasticache:Create*`, `elasticache:Modify*`, `elasticache:Delete*`, `elasticache:Describe*`, `elasticache:List*`, `elasticache:AddTagsToResource`, `elasticache:ListTagsForResource`, `elasticache:CopySnapshot`, and `elasticache:TestFailover`, plus `ec2:CreateVpcEndpoint`, `ec2:DeleteVpcEndpoints`, and `iam:CreateServiceLinkedRole` (with condition `iam:AWSServiceName: elasticache.amazonaws.com`). This action set covers every create/modify/delete/describe call this skill issues. See the Provisioning profile in `iam-policies.md` for the canonical list. `elasticache:*` is acceptable only for initial prototyping; do not use it in production. The `iam:CreateServiceLinkedRole` permission is required for first-time deployments or when the ElastiCache service-linked role does not yet exist in the account (see IAM.IdentityBasedPolicies Example 4). Note: for serverless caches, VPC endpoint lifecycle is managed by the ElastiCache service-linked role, but the deploying role still needs `ec2:CreateVpcEndpoint` for the initial creation call.
* For node-based: verify subnet IP capacity covers (1 primary + replicas per shard) x (shards). Each node consumes one IP address regardless of AZ placement. Spread across subnets, so ensure each AZ's subnet has enough IPs for the nodes placed there.
* For serverless: `CacheUsageLimits` set to prevent unexpected cost in non-production environments
