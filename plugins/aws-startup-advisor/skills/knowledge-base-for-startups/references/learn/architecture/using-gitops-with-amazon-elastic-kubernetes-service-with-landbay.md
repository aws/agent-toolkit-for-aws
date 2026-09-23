---
source_url: https://aws.amazon.com/startups/learn/using-gitops-with-amazon-elastic-kubernetes-service-with-landbay
title: "Using GitOps with Amazon Elastic Kubernetes Service with Landbay"
---

## Using GitOps with Amazon Elastic Kubernetes Service with Landbay

In the evolving landscape of digital lending, [Landbay](https://landbay.co.uk/), an award-winning mortgage lender in the UK's buy-to-let market, is revolutionizing its digital infrastructure. With a best-in-class broker platform supporting its underwriting operations, Landbay's platform is built on AWS services and comprises approximately 60 microservices, following a three-tier architecture, combining web servers, Amazon Elastic Kubernetes Service (Amazon EKS), and a multi-layered data layer. By combining the power of AWS Cloud Services with open-source projects, Landbay was able to leverage this new approach to spin up a best in-class architecture based on Amazon Elastic Kubernetes Service.

## The GitOps Advantage

As microservices architectures gain prominence, [GitOps](https://www.gitops.tech/#what-is-gitops) has emerged as a new standard for this deployment mechanism. Two noteworthy products have emerged within the Cloud Native Computing Foundation (CNCF): [Flux](https://fluxcd.io/) & [ArgoCD](https://github.com/argoproj/argo-cd). Landbay selected Flux for its native integration with Kubernetes by exposing custom resource definitions (CRDs) to define deployments, helm releases, Kustomizations, and more. This, in turn, empowered software engineers to master Kubernetes, thereby more seamlessly understanding how Flux fits within the ecosystem.

## Solution Overview

To provide a comprehensive understanding of Landbay's GitOps implementation, let's review the key architectural components and their relationships within the AWS ecosystem:

- [Amazon Elastic Container Registry](https://aws.amazon.com/ecr/) (ECR): Landbay leverages Amazon ECR for storing Helm charts, as well as Docker images.
- External DNS & [AWS Elastic Load Balancing](https://aws.amazon.com/elasticloadbalancing/) Controllers: These controllers are used to configure Route53 and load balancers, ensuring external access into Kubernetes ingresses.
- [AWS Secrets Manager](https://aws.amazon.com/secrets-manager/) Integration: For architectural and security reasons, Landbay has opted for direct integration with AWS Secrets manager, rather than use external tools such as external secrets controller, which aligns with AWS's shared responsibility model and enhances the overall security posture of the solution.
- [Terraform Configuration Management](https://docs.aws.amazon.com/prescriptive-guidance/latest/choose-iac-tool/terraform.html): Terraform can be used to bridge the gap by providing a ConfigMap and summarizing key configuration items (endpoints, subnets CIDRs, etc.). Flux can then use the config-map through [its post-build feature](https://fluxcd.io/flux/components/kustomize/api/v1/#kustomize.toolkit.fluxcd.io/v1.PostBuild) (see figure 2).

## Landbay's Kubernetes Environment and Data Architecture

Landbay is a keen adopter of Terraform and all its infrastructure is codified with infrastructure-as-code (IAC). This approach ensures synchronicity across test and production environments and ensures all infrastructure changes go through the standard software development lifecycle process.

To ensure zero downtime during Amazon EKS upgrades, Landbay employs the use of [EKS managed node groups](https://docs.aws.amazon.com/eks/latest/userguide/managed-node-groups.html) with three managed node groups, each targeting a specific availability zone. This configuration allows them to make use of persistent volumes, facilitated by the [Amazon Elastic Block Store (EBS) CSI driver](https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html). Additionally, Landbay uses [topologySpreadConstraints](https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/) (DoNotSchedule) to ensure that StatefulSets are spread across availability zones.

For critical services, custom priority classes are used to evict lower priority deployments.

To lower costs in the test environment, Landbay harnesses the power of [Amazon EC2 Spot Instances](https://aws.amazon.com/ec2/spot/) through Terraform and Amazon EKS managed node groups.

Finally, Landbay has embraced [Bottlerocket](https://aws.amazon.com/bottlerocket/) by presenting a much-reduced attack surface. Its Kubernetes operator is used to gradually upgrade nodes in a cluster using the concept of [waves](https://github.com/bottlerocket-os/bottlerocket/tree/develop/sources/updater/waves). While access to the root filesystem is locked down, the integration with IAM and Systems Manager (SSM) satisfies Landbay's fundamental requirements.

## Amazon EKS Add-Ons

In addition to the [Amazon Virtual Private Cloud](https://aws.amazon.com/vpc/) (Amazon VPC) CNI plugin, Landbay runs the following add-ons:

1. CoreDNS: Ensures DNS service resolution within the cluster
2. [KubeProxy](https://kubernetes.io/docs/reference/command-line-tools-reference/kube-proxy/): Underpins service discovery and networking within Kubernetes.
3. Amazon VPC CNI with _enableNetworkPolicy_: Allows the enforcement of network policies helping Landbay secure various access to namespaces and pods.
4. [Amazon EBS CSI Driver](https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html): Enables the use of persistent volumes.

## Access Management Configuration

Landbay uses [AWS IAM Identity Center](https://aws.amazon.com/iam/identity-center/) to control all access to AWS APIs. Amazon EKS allows the mapping of SSO roles into Kubernetes groups, enabling indirect mapping to Azure Entra ID groups through the IT Admin team. This approach ensures a separation of concerns between the IT Admin team and the rest of the organization.

To avoid a proliferation of roles, Kubernetes provides a mechanism to roll up permissions from other Helm Releases into existing groups using 'aggregate-to-admin'.

## AWS Load Balancer Controller

To enhance the integration between services, Landbay has leveraged [AWS Load Balancer Controller](https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html) (LBC) and External DNS Controller.

[AWS Load Balancer Controller](https://github.com/kubernetes-sigs/aws-load-balancer-controller) enables the provisioning of Load Balancers directly from Ingresses as well as the ability to re-use [externally managed Load Balancers](https://github.com/kubernetes-sigs/aws-load-balancer-controller/blob/main/docs/guide/targetgroupbinding/targetgroupbinding.md) and assign target pods. By separating the provisioning of Load Balancers into a separate project, DevOps teams can have greater privileges on one source code repository while still giving tools for the job to engineers managing the targets.

The controller also manages security groups as necessary on the backend between the Load Balancer and its targets. Additionally, by using the _group.name_ annotation, the same Load Balancer can be shared with multiple target groups behind the scenes.

Landbay also uses AWS Load Balancer Controller to provision Network Load Balancers to allow ingress from AWS Lambda functions running within the VPC into the EKS infrastructure.

Complementing this, the [External DNS controller](https://github.com/kubernetes-sigs/external-dns) allows Kubernetes pods limited write-access to Route53. This feature facilitates the automatic exposure of external services with friendly DNS names automatically, enhancing the overall user experience.

From a security standpoint, the [Application Load Balancer](https://aws.amazon.com/elasticloadbalancing/application-load-balancer/) (ALB) controller and the external DNS controller require a limited set of IAM permissions, which can be locked down tightly. For example, the DNS controller simply requires write access to specific Route 53 zones (_route53:ChangeResourceRecordSets_) as well as a handful of _List_ permissions.

## Secrets Management within Kubernetes

While most solutions address issues around secret management, such as rotation of secrets and integration, using Kubernetes secret storage or syncing external secrets into Kubernetes will result in secrets being stored in clear-text in the Kubernetes' underlying etcd. Although the use of '[encrypted secrets in EKS](https://docs.aws.amazon.com/eks/latest/userguide/enable-kms.html)' helps mitigate physical attack vectors, access via the Kubernetes API exposes the raw values of the secret, as per AWS's shared responsibility model.

Using the AWS-provided Container Storage Interface (CSI) driver provides benefits but also moves the architecture away from native Kubernetes management. Considering that both the CSI driver and an external provider solution require direct integration with the external secrets provider, Landbay decided to integrate its microservices directly against [AWS Secret Manager](https://aws.amazon.com/secrets-manager/).

The direct integration option avoids introducing more complexity in the environment which could otherwise lead to higher maintenance and support costs. It also avoids having clear-text secrets present in container volumes, further enhancing security.

## Provisioning Flux in the AWS Environment

Flux, Landbay's chosen GitOps solution, provides a Terraform provider for bootstrapping EKS clusters. At regular configurable intervals, Flux ensures that all Kubernetes manifests defined in the Git Repository reconcile against the existing resources deployed on Kubernetes, reverting any detected drift. Once Flux is bootstrapped, it can perform its first reconciliation, installing configured services, pods, stateful sets, and more onto the Kubernetes cluster.

Flux can leverage [AWS Elastic Container Registry](https://aws.amazon.com/ecr/) (ECR) as a Helm Repository as [ECR has first class support for OCI artifacts](https://docs.aws.amazon.com/AmazonECR/latest/userguide/push-oci-artifact.html). This allows Flux to act as the glue between ECR and EKS, using [Kustomizations](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/) to apply environment specific configurations.

One key advantage of this approach is the logical separation between the Continuous Integration **(CI)** part of the deployment pipeline (build, test & package) and the Continuous Deployment **(CD)** part (delivery into the environment). From a security perspective, Flux pulls the changes, allowing access permissions to be locked down significantly for daily deployments. To avoid deployment delays, the only permission required is for the build tool to 'notify' Flux of an early reconciliation, which can be done through a locked down _kubeconfig_, with a restricted user.

As a result, deploying, reverting or promoting a new microservice becomes as simple as updating a semantic versioning (semver) fragment in a YAML file, or reverting a commit. Upon observing a Git change, Flux triggers a reconciliation with Kubernetes and updates the relevant service accordingly.

## Flux Repository Structure and Shared Components

Flux provides comprehensive documentation on [recommended repository structures](https://fluxcd.io/flux/guides/repository-structure/). Landbay's approach is relatively straight forward and follows these best practices.

Cluster configurations are defined in their own dedicated folders, each referencing shared components. Within these cluster folders, extensive use of _Kustomizations_ ensures isolation between clusters. This allows for environment-specific configurations, such as versioning and memory.

The structure illustrated above strikes a balance between sharing code and retaining the declarative and explicit nature of the GitOps paradigm, allowing an engineer to read a Git repository and ascertain which components, versions, or packages have been installed on the cluster.

By separating the components, Landbay can streamline the process of building new clusters. From here, cluster configuration becomes a matter of choosing "LEGO bricks" and assembling them with some environment-specific configuration.

Furthermore, while some clusters operate in the cloud and require extra components, other clusters can be targeted at DevOps engineers working locally. This local development approach provides a faster feedback loop and does not include components directly related to AWS services.

## Local Development as a Stepping Stone

This local development approach is also the stepping stone for fast deployments of cloud-based ephemeral development environments. By using Kubernetes namespaces and removing dependencies on AWS managed services, Landbay is able to use Flux to quickly bootstrap new self-contained environments.

In this case, Landbay's development environment might replace Amazon Relational Database Service (RDS) with a simple MariaDB container, Amazon OpenSearch Service with the equivalent OpenSearch container. While this approach keeps development environments architecturally "in step" (e.g. similar namespacing, service discovery, networking), the trade-off is a lack of operational resilience – which may be acceptable for some development environments.

## Integrating EKS, GitOps and AWS Services

At Landbay, AWS infrastructure is managed entirely by [Terraform](https://www.terraform.io/). It is therefore imperative to bridge the gap between Terraform-provisioned elements (RDS, OpenSearch, etc.) and other pods running within the cluster. The native way to access configuration in Kubernetes in microservices is through ConfigMaps.

The first Terraform project is responsible for setting up all basic networking, internet-facing load balancers and AWS managed services. The second project establishes the EKS cluster, bootstraps Flux into the cluster, secures the EKS cluster, sets up any IAM roles, and manages low level concerns like managed node groups running Bottlerocket. This project creates an _environment ConfigMap_ that queries AWS for all environmental variables and injects them into Kubernetes.

The final project is a dedicated Flux project. This defines the cluster configuration for the environment, links to a set of shared components, and then _kustomizes_ Helm releases and Kubernetes manifests to fit the relevant environment. The _environment ConfigMap_ can then be used as part of kustomizations within the Flux repository. Flux also offers a [post-build variable substitution feature](https://github.com/drone/envsubst), allowing for the use of variable substitutions with a rich set of well-defined [bash string replacement functions](https://github.com/drone/envsubst).

For example, within a Helm chart, the values can use post build variable substitution. This approach enhances the GitOps repository so that shared components can be environment-agnostic.

## Conclusion

Landbay's decision to adopt GitOps through Flux, tightly integrated with both Amazon EKS and the broader AWS ecosystem, has proven to be a game-changer. By embracing this cutting-edge approach, Landbay has unlocked a myriad of benefits that have streamlined their operations and elevated its security posture. Perhaps one of the most significant advantages has been the realization of engineering efficiencies across the board. From faster deployments and reduced waiting times to seamless leveraging of third-party solutions, the integration of GitOps with EKS and AWS services has revolutionized Landbay's development processes.

Moreover, Landbay's security landscape has been fortified, becoming more robust and cost-effective to maintain. By leveraging Bottlerocket, segregating duties via SCM/Git permissions and enabling effortless upgrades through Helm, Landbay has solidified its commitment to security while optimizing operational costs.

The most profound impact of this transformative journey lies in the increased visibility and transparency of the EKS workload's state and changes. With GitOps, the configuration is declared using YAML, and all modifications are stored as Git commits. This paradigm shift has yielded significant advantages for Landbay's Support, Risk, Compliance, and Audit teams, empowering them with unprecedented insight and control over their mission-critical systems.

_If you're ready to transform your startup like Landbay, [join AWS Activate](https://aws.amazon.com/startups) to get access to deployable templates, AWS credits, and learning opportunities._

---

## Authors

### Chris Burrell

Chris is the Chief Technology Officer at Landbay. He joined Landbay in 2015 after working with BAE Systems on a variety of projects within Government & large Telco organisations. With over 20 years of experience in software engineering, Chris has been involved in a variety of engineering activities, including microservices architecture design & development, IaC, DevOps, performance testing and project management. Outside of work, Chris is involved with his local church, a keen pianist and enjoys fine dining.

### Ravikant Sharma

Ravikant Sharma is a Startup Solutions Architect at Amazon Web Services (AWS) based out of London. He helps Fintech Startups design and run their workloads on AWS. He specializes in cloud security and is a Security Guardian within AWS. Outside of work, he enjoys running and listening to music.

### Tsahi Duek

Tsahi Duek is a Principal Specialist Solutions Architect for Containers at Amazon Web Services. He has over 20 years of experience building systems, applications, and production environments, with a focus on reliability, scalability, and operational aspects. He is a system architect with a software engineering mindset.
