# Amazon ECS GPU sharing

Amazon ECS can share one physical NVIDIA GPU across multiple containers with NVIDIA Multi-Process Service (MPS). ECS sets up MPS, places containers onto GPUs, and enforces per-container limits. To request it, add a `sharingStrategy` with an `nvidiaMps` object to the container's `GPU` resource requirement instead of a whole-GPU `value`. The object takes a GPU `memory` limit in MiB and an optional `maxComputePercent`. ECS places tasks by GPU memory only. GPU sharing runs on ECS Managed Instances and ECS on EC2. Read the documentation for the supported instance families and the AMI that ECS on EC2 needs.

Use GPU sharing for inference and smaller models that do not need a whole GPU. Use a whole GPU (`value`) when a container runs more than one CUDA process or when you need per-task GPU metrics. GPU sharing does not work on AWS Fargate, ECS Express Mode, ECS managed daemon tasks, or G6f fractional GPU instances. On G6f fractional GPU instances, request a fractional GPU `value` instead, and read the GPU task definition documentation for the supported values. Prefer GPU sharing to the older manual method, which removes the GPU resource requirements and makes the NVIDIA runtime the default for all containers on the instance.

## Security considerations

Containers that share a GPU also share its failure domain. Recommend these defaults and confirm the details in the documentation:

- A fatal GPU error in one container, such as an illegal memory access, restarts every container on that physical GPU. Give a workload that must not be affected by its neighbors a whole GPU with `value`.
- Set `memory` for each container. It is a hard ceiling, so one container cannot take GPU memory from the others. `maxComputePercent` is a ceiling, not a reservation, so it does not guarantee compute to a container.
- Do not use the manual sharing method on new workloads. It lets every container on the instance use the GPUs.

## Documentation

Before advising or acting, the agent MUST read and cite [Share GPUs on Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu-sharing.html) at response time and answer from its published content. For GPU task definitions in general, read [Amazon ECS task definitions for GPU workloads](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu.html). Do not copy validation rules, task definition examples, or the supported instance list into this reference.
