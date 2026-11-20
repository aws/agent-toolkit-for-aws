# KV Cache Inference Optimization — Skill Handoff

This workflow is handled by a dedicated skill: **`distributed-kv-caching`**.

The `distributed-kv-caching` skill guides builders through setting up a shared
distributed KV cache with Amazon ElastiCache and LMCache to reduce self-hosted LLM
inference costs and time-to-first-token. It covers sizing, creating an ElastiCache
cluster with the valkey-large-object module, configuring LMCache, connecting vLLM
or SGLang, and tuning for cost or latency goals.

## When to hand off

Hand off when **all** of these are true:

- The user self-hosts open-weight models on GPUs (EC2, EKS, or equivalent — not
  SageMaker managed endpoints or Bedrock)
- The user asks about reducing inference cost, improving TTFT, sharing computed KV
  state across replicas, or adding a cache tier to their inference fleet
- The workload uses vLLM, SGLang, or TensorRT-LLM as the inference engine

> **Note:** The skill provides full engine setup for vLLM and SGLang only. TensorRT-LLM users benefit from the LMCache server and ElastiCache steps, but the skill gives no TensorRT-LLM engine steps — for those, follow the TensorRT-LLM release notes.

## When NOT to hand off

Stay in the AI-ML skill when:

- The user asks about **SageMaker endpoint optimization** (benchmarking, instance
  selection, inference recommendations) → route to `references/model-deployment/`
- The user asks about **Bedrock inference** → best-effort guidance from this skill
- The user asks about **traditional application caching** (session stores, database
  query caching) → the `amazon-elasticache` skill handles that, not this handoff

## How to load the skill

Use an already available local skill or the AWS MCP server. Loading a skill through
either method does not require user consent — it is not software installation and does
not authorize any AWS resource change.

### 1. Local skills directory

If `distributed-kv-caching` is already installed locally, it will activate
automatically. Check whether the skill is already available before attempting other
methods.

### 2. AWS MCP server (if available)

If the skill is not installed locally and the AWS MCP server is connected, call
`aws___retrieve_skill` with skill name `distributed-kv-caching`. You already have
the authoritative skill name — do not call `aws___search_documentation` first.

## If the skill is not available

If the skill cannot be loaded by either method above, advise the user that installing
the `distributed-kv-caching` skill is the recommended path. Tell them they can find
it in the official [aws/agent-toolkit-for-aws](https://github.com/aws/agent-toolkit-for-aws) GitHub
repository, or by searching [skills.sh](https://skills.sh) for `distributed-kv-caching` and
verifying the source is `aws/agent-toolkit-for-aws`. Ask for consent before providing or running installation steps.

If the user declines to install the skill, provide best-effort guidance using general
AWS knowledge and documentation tools (`aws___search_documentation`,
`aws___read_documentation`). The key concepts are:

- ElastiCache for Valkey with the `cache.i8ge.48xlarge` node type provides a
  distributed KV tensor store with EFA RDMA transport
- LMCache is the caching middleware between inference engines and ElastiCache
- The setup requires same-AZ placement of GPU instances, LMCache, and the
  ElastiCache cluster

Do NOT attempt to replicate the full skill workflow from this fallback — it covers
sizing, configuration, tuning, and troubleshooting that require the skill's reference
files.
