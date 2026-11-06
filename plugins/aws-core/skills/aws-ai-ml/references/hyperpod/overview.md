# HyperPod

Routes a SageMaker HyperPod request to the sub-reference that handles it. Read only
the sub-reference the request needs.

## Routing table

### Node access

| User intent                            | Route to                              | When to use                                                                                                                                                                                                                                   |
| -------------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Run commands on HyperPod cluster nodes | `references/hyperpod-ssm/overview.md` | User wants to run a command on one or more HyperPod nodes, for example to check GPUs or disk space, read a log or config file, or install a package. SSM is the access path; SSH works only through an SSM proxy, if the user has set one up. |

## Rules

- **Ask before changing a node.** A command sent through `hyperpod-ssm` runs as root on
  the customer's cluster, which is often shared. Run a command without asking only if it
  only reads (for example `nvidia-smi`, `df -h`, or showing a log) and runs on the nodes
  the user named. If the user named the cluster but no nodes, list them and let the user
  choose; never default to every node. For anything else, first show the exact command,
  the nodes, and whether it can be undone, and wait for the user's yes: writing, uploading,
  moving or deleting files; installing or removing software; starting, stopping or
  restarting a service or job; changing a setting; rebooting; or running on more nodes than
  the user named. Ask before reading a file that may hold secrets, such as keys or
  credentials. If a command fails, report the error instead of running a fix on your own.
- **Do NOT run commands from this overview.** For a request in the routing table, hand off
  to its sub-reference, because it has the scripts and the prerequisites. For an Out of
  Scope request, follow the Out of Scope guidance below; if it needs a command on a node,
  run it through `references/hyperpod-ssm/overview.md`.
- **Usage attribution.** Before running any AWS CLI command or packaged script, set
  `export AWS_SDK_UA_APP_ID=AWSSkill-SageMaker` (the usage-attribution rule in
  `../../SKILL.md`).

## Out of Scope

The following are supported by SageMaker and AWS but do not have a validated workflow in this reference. If the user's request matches one of these, let them know and proceed with best-effort guidance using general AWS knowledge:

- Creating a HyperPod cluster from scratch
- Submitting training jobs to a HyperPod cluster
- Deploying models for inference on HyperPod
- Debugging a HyperPod cluster, node, NCCL, Slurm, or performance problem

Reading logs and running read-only commands on nodes through `references/hyperpod-ssm/overview.md` is in scope, even when the goal is debugging. Finding the root cause is the best-effort part.
