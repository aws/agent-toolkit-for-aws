# AWS Load Balancer Controller

## Overview

The AWS Load Balancer Controller (LBC) is a Kubernetes controller that manages AWS Elastic Load Balancers and (in recent versions) AWS Global Accelerator for an EKS cluster. As of `v3.x` it reconciles four families of resources:

1. **Kubernetes `Ingress`** → provisions an **Application Load Balancer (ALB)** (Layer 7, HTTP/HTTPS).
2. **Kubernetes `Service` of type `LoadBalancer`** with the `service.beta.kubernetes.io/aws-load-balancer-type: external` annotation → provisions a **Network Load Balancer (NLB)** (Layer 4, TCP/UDP/TLS).
3. **Kubernetes Gateway API** (`Gateway` + `*Route`) → provisions an ALB or NLB depending on the `GatewayClass`. L4 routes (`TCPRoute`, `UDPRoute`, `TLSRoute`) land on an NLB; L7 routes (`HTTPRoute`, `GRPCRoute`) land on an ALB. Mixing L4 and L7 routes on a single Gateway is not supported.
4. **`GlobalAccelerator` (CRD `aga.k8s.aws/v1beta1`)** → provisions and reconciles an **AWS Global Accelerator**, automatically discovering ELBs created by the controller's other sub-controllers (Ingress, Service, Gateway) or referenced directly by ARN.

The controller also supports `TargetGroupBinding` for adopting out-of-band target groups, an Ingress-to-Gateway migration tool, ALB target optimization, and pod readiness gates for zero-downtime rollouts. It runs as a Deployment in the cluster (typically in `kube-system`) and requires an IAM role — provisioned via [IRSA](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html) or [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html) — with permissions to manage ELBv2, EC2, WAF, ACM, and (for Global Accelerator) Global Accelerator + Resource Group Tagging APIs.

## Documentation

The authoritative documentation is published on GitHub Pages from the [kubernetes-sigs/aws-load-balancer-controller](https://github.com/kubernetes-sigs/aws-load-balancer-controller) repository. **Always check the docs for the version you have installed** — annotation names, CRD `apiVersion`s, defaults, and supported features change between minor versions.

- **Project docs:** https://kubernetes-sigs.github.io/aws-load-balancer-controller/
- **Latest release:** https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/
- **Versioned docs:** `https://kubernetes-sigs.github.io/aws-load-balancer-controller/v2.X/` or `/v3.X/` (substitute the installed minor version)
- **Ingress annotations:** https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/
- **Service annotations:** https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/service/annotations/
- **Gateway API guide:** https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/gateway/gateway/
- **Global Accelerator guide:** https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/globalaccelerator/aga-controller/
- **Ingress → Gateway migration:** https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress2gateway/
- **IAM policy JSON:** `https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/<tag>/docs/install/iam_policy.json`
- **Global Accelerator IAM policy:** `https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/<tag>/docs/install/aga_controller_iam_policy.json`
- **AWS user guide:** https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html
- **EKS Best Practices — Load Balancing:** https://docs.aws.amazon.com/eks/latest/best-practices/load-balancing.html
- **Helm chart:** https://github.com/aws/eks-charts/tree/master/stable/aws-load-balancer-controller
- **GitHub releases (use to confirm latest version):** `gh api repos/kubernetes-sigs/aws-load-balancer-controller/releases?per_page=5`

To find the installed version in a cluster:

```sh
kubectl get deployment -n kube-system aws-load-balancer-controller \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

## Version compatibility highlights

- LBC `v3.x` requires Kubernetes 1.22+.
- Gateway API support requires LBC `>=v2.13.0`; L4 routes (`TCPRoute`, `UDPRoute`, `TLSRoute`) require `>=v2.13.3`; L7 routes (`HTTPRoute`, `GRPCRoute`) require `>=v2.14.0`. The current implementation targets upstream Gateway API `v1.5.0`.
- Global Accelerator integration is built into LBC `>=v2.17.0` and requires installing the `GlobalAccelerator` CRD plus enabling the `GlobalAcceleratorController` and `EnableRGTAPI` feature gates.
- Global Accelerator is only available in the commercial AWS partition (not GovCloud or China).

Always confirm the latest tag before installing — release cadence is roughly monthly.

## Reference snippets

### Getting the latest release

It is best practice to reference a specific release of the LBC, if a specific version is not given the latest version can be retrieved like so:

```sh
TAG=$(gh api repos/kubernetes-sigs/aws-load-balancer-controller/releases/latest --jq .tag_name)
```

### Install via Helm (with EKS Pod Identity)

```sh
curl -O "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/${TAG}/docs/install/iam_policy.json"

# 2. Create the IAM policy
aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy \
  --policy-document file://iam_policy.json

# 3. Install the EKS Pod Identity Agent on the cluster (one-time; skip if already present)
eksctl create addon \
  --cluster=<cluster-name> \
  --name=eks-pod-identity-agent

# 4. Create the IAM role and Pod Identity association (eksctl creates the role with the
#    pods.eks.amazonaws.com trust policy and associates it with the service account)
eksctl create podidentityassociation \
  --cluster=<cluster-name> \
  --namespace=kube-system \
  --service-account-name=aws-load-balancer-controller \
  --permission-policy-arns=arn:aws:iam::<account-id>:policy/AWSLoadBalancerControllerIAMPolicy \
  --role-name=AmazonEKSLoadBalancerControllerRole

# 5. Install the controller (let the chart create the service account; no IRSA
#    role-arn annotation is needed — Pod Identity binds the role by namespace + SA name)
helm repo add eks https://aws.github.io/eks-charts
helm repo update eks
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=<cluster-name> \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller
```

> EKS Pod Identity requires LBC `>=v2.7.0` (uses the AWS SDK Pod Identity credential provider). The Pod Identity Agent runs as a DaemonSet and injects credentials via `AWS_CONTAINER_CREDENTIALS_FULL_URI`; unlike IRSA, no OIDC provider or `eks.amazonaws.com/role-arn` service-account annotation is required.

### Internet-facing ALB via Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP":80},{"HTTPS":443}]'
    alb.ingress.kubernetes.io/ssl-redirect: "443"
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-west-2:111122223333:certificate/abc-123
    alb.ingress.kubernetes.io/healthcheck-path: /healthz
spec:
  ingressClassName: alb
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: app
                port:
                  number: 80
```

Use `alb.ingress.kubernetes.io/group.name` (and optionally `group.order`) to merge multiple Ingress resources onto a single ALB.

### Internet-facing NLB via Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: app
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: external
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
    service.beta.kubernetes.io/aws-load-balancer-scheme: internet-facing
    service.beta.kubernetes.io/aws-load-balancer-cross-zone-load-balancing-enabled: "true"
spec:
  type: LoadBalancer
  selector:
    app: app
  ports:
    - port: 443
      targetPort: 8443
      protocol: TCP
```

### Gateway API

The AWS Load Balancer Controller has first-class support for the Gateway API (LBC `>=v2.13.0`). This supports both L4 and L7 routing.

See the [relevant documentation](https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/refs/tags/${TAG}/docs/guide/gateway/gateway.md) for more details.

In order to enable the Gateway API functionality the LBC must be appropriately installed/configured. When providing installation guidance you MUST carefully review the documentation provided above.

### Global Accelerator

The AWS Load Balancer Controller has first-class support for integrating with Global Accelerator (LBC `>=v2.17.0`).

See the [relevant documentation](https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/refs/tags/${TAG}/docs/guide/globalaccelerator/aga-controller.md) for more details.

When providing installation guidance you MUST carefully review the documentation provided above.

#### Usage

Auto-discovery of an existing Ingress (the controller infers protocol and port ranges from the discovered ALB):

```yaml
apiVersion: aga.k8s.aws/v1beta1
kind: GlobalAccelerator
metadata:
  name: web-app-accelerator
  namespace: web-app
spec:
  name: web-app-accelerator
  ipAddressType: IPV4
  tags:
    Environment: production
  listeners:
    - endpointGroups:
        - endpoints:
            - type: Ingress
              name: web-app-ingress
              weight: 200
```

Multi-region active/passive failover with an explicit cross-region endpoint by ARN:

```yaml
apiVersion: aga.k8s.aws/v1beta1
kind: GlobalAccelerator
metadata:
  name: failover
  namespace: default
spec:
  name: failover
  ipAddressType: IPV4
  listeners:
    - protocol: TCP
      portRanges:
        - { fromPort: 443, toPort: 443 }
      endpointGroups:
        - trafficDialPercentage: 100
          endpoints:
            - type: Service
              name: primary
        - region: us-west-2
          trafficDialPercentage: 0
          endpoints:
            - type: EndpointID
              endpointID: arn:aws:elasticloadbalancing:us-west-2:111122223333:loadbalancer/app/dr-lb/abc123
              weight: 128
```

Endpoint `type` accepts `Service`, `Ingress`, `Gateway`, or `EndpointID` (ELB ARN). Auto-discovery only works in the controller's own region; cross-region endpoint groups must specify `region`, `protocol`, and `portRanges` explicitly. BYOIP is supported via `spec.ipAddresses` but only on initial creation — IPs cannot be updated on an existing accelerator.

Cross-namespace endpoint references require a Gateway API `ReferenceGrant` in the target namespace, which means the upstream Gateway API CRDs must be installed even if you don't otherwise use Gateway API.

### Pod readiness gates (zero-downtime rollouts)

```sh
kubectl label namespace <ns> elbv2.k8s.aws/pod-readiness-gate-inject=enabled
```

Pods become Ready only after they pass ALB/NLB target group health checks. Requires `target-type: ip`.

## Common pitfalls

- **Subnet auto-discovery requires tags.** Public subnets need `kubernetes.io/role/elb=1`; private subnets need `kubernetes.io/role/internal-elb=1`. Without these, the controller logs `couldn't auto-discover subnets`.
- **`target-type: ip` requires the VPC CNI** — pod IPs must be routable from the load balancer. With `instance` mode, the LB targets node IPs and traffic is forwarded via NodePort.
- **Controller fails to discover region/VPC ID with IMDS hop limit 1.** On EC2-backed nodes the controller falls back to IMDS to auto-detect the AWS region and VPC ID. The default IMDS `httpPutResponseHopLimit` of `1` blocks pods (one extra network hop) from reaching IMDS, so the controller crashes on startup with errors like `failed to introspect region from EC2Metadata` or `failed to get VPC ID`. Fix by passing the values explicitly via Helm (`--set region=<region> --set vpcId=<vpc-id>`) so IMDS is never queried. **Do not suggest raising the IMDS hop limit as a fix** — it weakens the node's metadata security posture (a higher hop limit lets more containers reach IMDS); set `region`/`vpcId` instead.
- **Security groups:** The controller manages a frontend SG on the LB and (by default) modifies the cluster node SG to allow traffic. To opt out for Ingress/Service, set `--enable-backend-security-group=false`. For Gateway, disable backend SG management on the `LoadBalancerConfiguration` CRD.
- **IngressClass over annotation:** Prefer `spec.ingressClassName: alb` (with an `IngressClass` resource pointing to controller `ingress.k8s.aws/alb`) over the legacy `kubernetes.io/ingress.class: alb` annotation.
- **Gateway TLS via certificateRefs is not supported.** Configure certs through `LoadBalancerConfiguration` or hostname-based ACM discovery.
- **Mixed L4/L7 on one Gateway is rejected.** Use one Gateway per layer.
- **Global Accelerator partition limits.** Not available in `aws-us-gov` or `aws-cn`. Always check current AWS service quotas before provisioning many accelerators.
- **Version skew with EKS:** Check the [version compatibility matrix](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/deploy/installation/#supported-kubernetes-versions) before upgrading the cluster — older controller versions may not support newer Kubernetes minor versions.
