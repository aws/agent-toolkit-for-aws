---
_fragment: eks-generate
_of_phase: generate
_contributes:
  - terraform/eks.tf
  - kubernetes/
---

# EKS Generate Phase

> Conditional generation fragment. Fires (gate in its prose) only when
> `aws-design.json` contains `aws_service: "EKS"`. When active, it produces the EKS
> Terraform + kubernetes/ manifests; otherwise the Fargate generation path applies
> and this fragment is skipped.

---

## Generated Artifacts

### 1. `terraform/eks.tf`

Generate EKS cluster Terraform:

**Node group selection:**

- If `design.eks_cluster.node_group_type == "managed"` → emit ONLY the `aws_eks_node_group` resource block below. Do NOT emit the self-managed resources.
- If `design.eks_cluster.node_group_type == "self-managed"` → emit ONLY the `aws_launch_template` + `aws_autoscaling_group` + `aws_security_group` blocks below. Do NOT emit `aws_eks_node_group`.
- **Never emit both.** The design specifies exactly one node group type.

```hcl
# EKS Cluster
resource "aws_eks_cluster" "main" {
  name     = "<cluster_name>"
  role_arn = aws_iam_role.eks_cluster.arn
  version  = "<kubernetes_version>"

  vpc_config {
    subnet_ids         = [<subnet references from VPC design>]
    security_group_ids = [aws_security_group.eks_cluster.id]
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy,
    aws_iam_role_policy_attachment.eks_vpc_resource_controller,
  ]
}

# IAM Role for EKS Cluster
resource "aws_iam_role" "eks_cluster" {
  name = "<cluster_name>-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.eks_cluster.name
}

resource "aws_iam_role_policy_attachment" "eks_vpc_resource_controller" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSVPCResourceController"
  role       = aws_iam_role.eks_cluster.name
}

# IAM Role for Node Group
resource "aws_iam_role" "eks_nodes" {
  name = "<cluster_name>-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_worker_node_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_iam_role_policy_attachment" "eks_cni_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_iam_role_policy_attachment" "eks_container_registry" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.eks_nodes.name
}

# Managed Node Group (when node_group_type = "managed")
resource "aws_eks_node_group" "general" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "general"
  node_role_arn   = aws_iam_role.eks_nodes.arn
  subnet_ids      = [<subnet references>]

  instance_types = [<from design>]

  scaling_config {
    desired_size = <from design>
    max_size     = <from design>
    min_size     = <from design>
  }
}

# Self-Managed Node Group (when node_group_type = "self-managed")
# Use this path when design specifies eks-managed preference (full K8s control)

resource "aws_launch_template" "eks_nodes" {
  name_prefix   = "<cluster_name>-node-"
  instance_type = <from design instance_types[0]>
  image_id      = data.aws_ssm_parameter.eks_ami.value

  user_data = base64encode(<<-EOF
    #!/bin/bash
    /etc/eks/bootstrap.sh ${aws_eks_cluster.main.name}
  EOF
  )

  # IMDSv2 enforcement — security baseline, always applied (generate-terraform.md Step 1.5, EKS launch-template rider).
  # Hop limit 1 is intentionally stricter than the account default 2 in baseline.tf.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
    instance_metadata_tags      = "enabled"
  }

  network_interfaces {
    security_groups = [aws_security_group.eks_nodes.id]
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      "kubernetes.io/cluster/${aws_eks_cluster.main.name}" = "owned"
    }
  }
}

data "aws_ssm_parameter" "eks_ami" {
  name = "/aws/service/eks/optimized-ami/<kubernetes_version>/amazon-linux-2/recommended/image_id"
}

resource "aws_autoscaling_group" "eks_nodes" {
  name                = "<cluster_name>-nodes"
  desired_capacity    = <from design desired_size>
  max_size            = <from design max_size>
  min_size            = <from design min_size>
  vpc_zone_identifier = [<subnet references>]

  launch_template {
    id      = aws_launch_template.eks_nodes.id
    version = "$Latest"
  }

  tag {
    key                 = "kubernetes.io/cluster/${aws_eks_cluster.main.name}"
    value               = "owned"
    propagate_at_launch = true
  }
}

resource "aws_security_group" "eks_nodes" {
  name_prefix = "<cluster_name>-nodes-"
  vpc_id      = <vpc_id reference>

  # Allow all traffic from the cluster security group
  ingress {
    from_port       = 0
    to_port         = 0
    protocol        = "-1"
    security_groups = [aws_security_group.eks_cluster.id]
  }

  # Allow node-to-node communication
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# OIDC Provider for IRSA
data "tls_certificate" "eks" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

# AWS Load Balancer Controller
resource "helm_release" "aws_lb_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"
  version    = "1.8.0"

  set {
    name  = "clusterName"
    value = aws_eks_cluster.main.name
  }

  set {
    name  = "serviceAccount.create"
    value = "true"
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.aws_lb_controller.arn
  }
}

# Security Group for EKS cluster API endpoint
resource "aws_security_group" "eks_cluster" {
  name_prefix = "<cluster_name>-cluster-"
  vpc_id      = <vpc_id reference>

  # Restrict API access to VPC CIDR (tighten further for production)
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [<vpc_cidr_block>]  # e.g. "10.0.0.0/16" from VPC design
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

**If data stores exist in the design**, add security group rules for pod-to-service communication:

- Pod → RDS: port 5432
- Pod → ElastiCache: port 6379
- Pod → MSK: port 9092

### 2. `kubernetes/` Directory

Generate Kubernetes manifests:

**`kubernetes/namespace.yaml`** (one per unique heroku_app):

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: <heroku-app-name>
  labels:
    app.kubernetes.io/managed-by: heroku-migration
```

**`kubernetes/<app>-<process-type>-deployment.yaml`** (one per formation):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <process-type>
  namespace: <heroku-app-name>
  labels:
    app: <process-type>
    app.kubernetes.io/name: <process-type>
    app.kubernetes.io/part-of: <heroku-app-name>
spec:
  replicas: <quantity>
  selector:
    matchLabels:
      app: <process-type>
  template:
    metadata:
      labels:
        app: <process-type>
    spec:
      containers:
      - name: <process-type>
        image: <placeholder-image>
        resources:
          requests:
            cpu: "<from aws-design.json: aws_config.resources.requests.cpu>"
            memory: "<from aws-design.json: aws_config.resources.requests.memory>"
          limits:
            cpu: "<from aws-design.json: aws_config.resources.limits.cpu>"
            memory: "<from aws-design.json: aws_config.resources.limits.memory>"
        env:
        - name: PORT
          value: "8080"  # Heroku injects $PORT dynamically; 8080 is the default here. If your app binds to a different port, update this value and the containerPort/targetPort to match.
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: <heroku-app-name>-config
              key: DATABASE_URL
              optional: true
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: <heroku-app-name>-config
              key: REDIS_URL
              optional: true
        ports:
        - containerPort: 8080  # Matches PORT env var; only for web processes
```

**`kubernetes/<app>-web-service.yaml`** (only for web process types):

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web
  namespace: <heroku-app-name>
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: "external"
    service.beta.kubernetes.io/aws-load-balancer-scheme: "internet-facing"
    service.beta.kubernetes.io/aws-load-balancer-target-type: "ip"
    alb.ingress.kubernetes.io/target-type: "ip"
spec:
  type: LoadBalancer
  selector:
    app: web
  ports:
  - port: 80
    targetPort: 8080
    protocol: TCP
```

### 3. MIGRATION_GUIDE.md — EKS Sections

Add these sections after Prerequisites, before Data Migration:

````markdown
## EKS Cluster Setup

1. Apply EKS Terraform:
   ```bash
   cd terraform/
   terraform init
   terraform apply
   ```

2. Configure kubectl access:
   ```bash
   aws eks update-kubeconfig --name heroku-migration-cluster --region <region>
   ```

3. Verify node group readiness:
   ```bash
   kubectl get nodes
   # All nodes should show STATUS: Ready
   ```

4. Verify AWS Load Balancer Controller:
   ```bash
   kubectl get deployment -n kube-system aws-load-balancer-controller
   # Should show AVAILABLE: 1+
   ```

## Deploy Workloads to EKS

1. Create namespace:
   ```bash
   kubectl apply -f kubernetes/namespace.yaml
   ```

2. Deploy all workloads:
   ```bash
   kubectl apply -f kubernetes/
   ```

3. Verify pods are running:
   ```bash
   kubectl get pods -n <namespace>
   # All pods should show STATUS: Running
   ```

4. Verify load balancer (web services):
   ```bash
   kubectl get svc -n <namespace>
   # EXTERNAL-IP should be provisioned within 2–5 minutes
   ```

## Configure Pod-to-Service Access

> Include this section ONLY when EKS services coexist with data stores (RDS, ElastiCache, MSK).

1. **IAM Roles for Service Accounts (IRSA):**
   ```bash
   # The OIDC provider was created by Terraform. Create a service account:
   kubectl create serviceaccount <app>-sa -n <namespace>
   kubectl annotate serviceaccount <app>-sa -n <namespace> \
     eks.amazonaws.com/role-arn=arn:aws:iam::<account>:role/<app>-pod-role
   ```

2. **Verify security group rules** (created by Terraform):
   - Pods → RDS on port 5432
   - Pods → ElastiCache on port 6379
   - Pods → MSK on port 9092

3. **Store connection strings in Kubernetes Secrets:**
   ```bash
   kubectl create secret generic db-credentials -n <namespace> \
     --from-literal=DATABASE_URL='postgres://user:pass@rds-endpoint:5432/db'
   ```

4. **Reference secrets in Deployments** (update container env):
   ```yaml
   env:
   - name: DATABASE_URL
     valueFrom:
       secretKeyRef:
         name: db-credentials
         key: DATABASE_URL
   ```
````

**Omit all EKS sections** when the design contains only Fargate-only compute (no EKS services).

### Post-Deployment Enhancements (recommended but not generated)

Include this note at the end of the "Deploy Workloads to EKS" section:

```markdown
> **Recommended next steps (not auto-generated):**
>
> - Add **liveness and readiness probes** to each Deployment. Heroku performs health checks automatically; Kubernetes requires explicit probe configuration for reliable restarts and traffic routing.
> - Consider adding a **Horizontal Pod Autoscaler (HPA)** if your workloads need dynamic scaling. The generated manifests use fixed `replicas` matching your Heroku formation quantity. HPA can replace or supplement this for traffic-driven scaling.
> - Review **resource limits** — the generated limits allow CPU bursting (2× request). Tune after observing actual usage in production.
```

---

## Terraform Validation

After generating `eks.tf`, the combined Terraform in `terraform/` must pass `terraform validate`. If validation fails, log the error to `generation-warnings.json` and continue.

## Helm Provider Requirement

When `eks.tf` is generated, add the Helm provider to `main.tf`:

```hcl
terraform {
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12"
    }
  }
}

provider "helm" {
  kubernetes {
    host                   = aws_eks_cluster.main.endpoint
    cluster_ca_certificate = base64decode(aws_eks_cluster.main.certificate_authority[0].data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      args        = ["eks", "get-token", "--cluster-name", aws_eks_cluster.main.name]
      command     = "aws"
    }
  }
}
```
