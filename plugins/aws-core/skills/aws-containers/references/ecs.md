# Amazon Elastic Container Service

## Overview

Domain expertise for managing ECS clusters and deploying workloads to them. Covers various topics.

## When to Load Reference Files

Load the appropriate reference file based on what the user is working on:

- **cluster compute**, **managing nodes**, **managed instances**, **fargate**, or **amis** -> see [ecs-managing-compute.md](ecs-managing-compute.md)
- **task definitions**, **task/execution IAM roles**, **secrets injection**, **volumes**, **managed daemons**, **daemon tasks**, or **agents on instances** -> see [ecs-workloads.md](ecs-workloads.md)
- **Action Logs**, **control-plane troubleshooting**, **deployment rollback / circuit-breaker**, **task placement failures**, **scaling / task replacement visibility**, or **enabling or reading ECS Action Logs** -> see [action-logs.md](action-logs.md)
- **ECS Gateway**, **service ingress**, **shared HTTP/HTTPS endpoints for services**, or **choosing between ECS Gateway, Express Mode, and a load balancer** -> see [ecs-gateway.md](ecs-gateway.md)
- **GPU sharing**, **NVIDIA MPS**, **sharing one GPU across containers or tasks**, or **`sharingStrategy` in a GPU resource requirement** -> see [ecs-gpu-sharing.md](ecs-gpu-sharing.md)

## Resources

- [Amazon ECS Documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/Welcome.html)
- [Amazon ECS Best Practices Guide](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-best-practices.html)
- [IAM Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonelasticcontainerservice.html)
