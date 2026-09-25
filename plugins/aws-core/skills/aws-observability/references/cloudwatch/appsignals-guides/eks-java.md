# Enable AWS Application Signals for Java Applications on Amazon EKS

This guide shows how to modify existing CDK and Terraform infrastructure code to enable AWS Application Signals for Java applications running on Amazon EKS.

## Prerequisites

- Application Signals enabled in your AWS account (see [Enable Application Signals in your account](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable.html))
- Existing EKS cluster deployed using CDK or Terraform code
- Java application containerized and pushed to ECR
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

### 2. Add Java Instrumentation Annotation

```typescript
template: {
  metadata: {
    labels: { app: config.appName },
    annotations: {
      'instrumentation.opentelemetry.io/inject-java': 'true'
    }
  },
}
```

## Terraform Implementation

### 1. Add CloudWatch Agent IAM Permissions

> **Neither path in this guide confines `CloudWatchAgentServerPolicy` to the agent.** Attaching to
> `node_role` grants it to **every pod scheduled on those nodes**, since any pod can reach the node's
> instance credentials unless IMDS access is blocked. The CDK path above uses an IRSA-style role
> instead of the node role, but as written its trust policy has **no `:sub` condition** —
> `new iam.OpenIdConnectPrincipal(cluster.openIdConnectProvider)` with no `conditions` lets any pod
> holding a projected service-account token call `AssumeRoleWithWebIdentity` on it. To actually scope
> it, add a `:sub` condition naming the addon's service accounts (the addon installs two —
> `cloudwatch-agent` and `cloudwatch-agent-cluster-scraper`) plus `:aud sts.amazonaws.com`. Tell the
> customer which of the three states the change leaves them in.

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

### 3. Add Java Instrumentation Annotation

```hcl
template {
  metadata {
    labels = {
      app = var.app_name
    }
    annotations = {
      "instrumentation.opentelemetry.io/inject-java" = "true"
    }
  }
}
```

## Important Notes

- The Java instrumentation annotation will cause pods to restart automatically
- Java applications typically have faster startup times with Application Signals compared to other languages
- It may take a few minutes for data to appear in the Application Signals console after deployment

## Completion

> **Before reciting the summary below (guidance for you, not for the user):** say which role the
> policy actually landed on, because the two paths differ in blast radius. The CDK path puts it on an
> IRSA-style role; the Terraform path attaches it to the **node** role, which extends it to every pod
> scheduled on those nodes. Also state that the CDK role's trust policy has no `:sub` condition
> unless one was added, so as written neither path confines the policy to the agent. The summary
> bullet has a ``your-node-role`` slot — fill it in with the role this change actually used before reciting.

**Tell the user:**

"I've completed the Application Signals enablement for your Java application. Here's what I modified:

**Files Changed:**

- IAM role: Added CloudWatchAgentServerPolicy to `your-node-role`
- CloudWatch Observability EKS add-on: Added to the EKS Cluster
- Kubernetes Deployment: Instrumentation annotation added with inject-java set to true

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
