# Amazon ECS isolated and confidential tasks

Amazon ECS can run each task in its own lightweight VM, an AWS Nitro Sandbox, on ECS Managed Instances. Several isolated tasks share one instance, so you get VM-level isolation between tasks and keep bin-packing. To request it, set `trustedExecutionConfiguration.isolationMode` in the task definition to `ISOLATED_SANDBOX` or `CONFIDENTIAL_SANDBOX`. `SHARED` is the default and gives no VM boundary. The tasks must run on a Managed Instances capacity provider whose `InstanceLaunchTemplate` sets `nitroEnclavesEnabled` to `true`.

Use `ISOLATED_SANDBOX` to separate tasks from each other, for example tasks from different tenants on one instance. The parent instance stays trusted, so ECS Exec and log streaming keep working. Use `CONFIDENTIAL_SANDBOX` when the data must stay confidential even from the instance operator. It also requires an `attestationPolicy`. Attestation enforces nothing by itself: AWS KMS withholds keys from a task only when the KMS key policy requires attestation and the task's measurements do not match. Generate the policy with the `ecs-nitro-sandbox-genpolicy` tool instead of writing it by hand, and regenerate it whenever a container image or pinned task definition field changes.

Isolated and confidential tasks run only on ECS Managed Instances, not on AWS Fargate or ECS on EC2. They need the `awsvpc` network mode and do not support GPUs, ECS Service Connect, or EBS volumes with `configuredAtLaunch`. `nitroEnclavesEnabled` cannot be combined with local storage on the capacity provider. Read the documentation for the supported instance types and the full list of limitations.

Avoid these mistakes:

- In a KMS key policy for confidential tasks, use the `kms:RecipientAttestation:PCR8:ServiceName` condition key, not `kms:RecipientAttestation:PCR8`. ECS rotates the certificate that PCR8 measures, so a raw PCR8 condition starts denying every task after a rotation.
- If a confidential task or its service sets `enableExecuteCommand`, generate the policy with `ecs-nitro-sandbox-genpolicy --allow-exec-command`. Without it, the task is denied at startup.
- On instances with two threads per physical core (most Intel and SMT-enabled AMD types), two sandboxes never run on the same core at the same time, so sandboxed tasks get about half the advertised vCPUs. Request CPU in multiples of 2 vCPUs, or use Graviton instances.

## Documentation

Before advising or acting, the agent MUST read and cite [Isolated and confidential tasks](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/isolated-confidential-tasks.html) at response time and answer from its published content. Do not copy attestation policy examples, full KMS key policies, or the supported instance list into this reference.
