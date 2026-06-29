# Enable AWS Application Signals for .NET Applications on Amazon EKS

This guide shows how to modify existing CDK and Terraform infrastructure code to enable AWS Application Signals for .NET applications running on Amazon EKS.

## Prerequisites

- Application Signals enabled in your AWS account (see [Enable Application Signals in your account](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable.html))
- Existing EKS cluster deployed using CDK or Terraform code
- .NET application containerized and pushed to ECR
- AWS CLI configured with appropriate permissions

## Critical Requirements

**Do NOT:**

- Run deployment commands automatically (`cdk deploy`, `terraform apply`, etc.)
- Remove existing application startup logic
- Skip the user approval step before deployment

## CDK Implementation

### 1. Install CloudWatch Observability Add-on

```typescript
import * as eks from 'aws-cdk-lib/aws-eks';
import * as iam from 'aws-cdk-lib/aws-iam';

const cloudwatchRole = new iam.Role(this, 'CloudWatchAgentAddOnRole', {
  assumedBy: new iam.OpenIdConnectPrincipal(cluster.openIdConnectProvider),
  managedPolicies: [
    iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchAgentServerPolicy')
  ],
});

new eks.CfnAddon(this, 'CloudWatchAddon', {
  addonName: 'amazon-cloudwatch-observability',
  clusterName: cluster.clusterName,
  serviceAccountRoleArn: cloudwatchRole.roleArn
});
```

### 2. Add .NET Instrumentation Annotation

```typescript
template: {
  metadata: {
    labels: { app: config.appName },
    annotations: {
      'instrumentation.opentelemetry.io/inject-dotnet': 'true'
    }
  },
}
```

## Terraform Implementation

### 1. Add CloudWatch Agent IAM Permissions

```hcl
resource "aws_iam_role_policy_attachment" "cloudwatch_agent_policy" {
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
  role       = aws_iam_role.node_role.name
}
```

Add to node group's `depends_on`:

```hcl
resource "aws_eks_node_group" "app_nodes" {
  depends_on = [
    aws_iam_role_policy_attachment.node_policy,
    aws_iam_role_policy_attachment.cloudwatch_agent_policy
  ]
}
```

### 2. Install CloudWatch Observability Add-on

```hcl
resource "aws_eks_addon" "cloudwatch_observability" {
  cluster_name = aws_eks_cluster.app_cluster.name
  addon_name   = "amazon-cloudwatch-observability"

  depends_on = [
    aws_eks_node_group.app_nodes
  ]
}
```

### 3. Add .NET Instrumentation Annotation

```hcl
template {
  metadata {
    labels = {
      app = var.app_name
    }
    annotations = {
      "instrumentation.opentelemetry.io/inject-dotnet" = "true"
    }
  }
}
```

## Important Notes

- The .NET instrumentation annotation will cause pods to restart automatically
- .NET applications require .NET 6.0 or later for Application Signals support
- It may take a few minutes for data to appear in the Application Signals console after deployment

## Completion

**Tell the user:**

"I've completed the Application Signals enablement for your .NET application. Here's what I modified:

**Files Changed:**

- IAM role: Added CloudWatchAgentServerPolicy
- CloudWatch Observability EKS add-on: Added to the EKS Cluster
- Kubernetes Deployment: Instrumentation annotation added with inject-dotnet set to true

**Next Steps:**

1. Ensure that [Application Signals is enabled in AWS account](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable.html).
2. Review the changes using `git diff`
3. Deploy your infrastructure
4. After deployment, wait 5-10 minutes for telemetry data to start flowing

**Verification:**

- Open AWS CloudWatch Console → Application Signals → Services

**Troubleshooting**
Refer to the [CloudWatch APM troubleshooting guide](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable-Troubleshoot.html).

Let me know if you'd like me to make any adjustments before you deploy!"
