---
name: distributed-kv-caching
description: "Sets up a shared L2 KV cache for self-hosted LLM inference on Amazon ElastiCache for Valkey, so GPU servers load prefill KV state over EFA RDMA instead of recomputing it. Checks fit, estimates savings with KVTrace, builds a business case, creates the cache, connects vLLM or SGLang (also as NVIDIA Dynamo or llm-d workers) through an LMCache server, tunes for cost or latency, and troubleshoots. Use when a builder serves open-weight models on GPUs (for example H100 or B200, on Amazon EC2 or Amazon EKS) for multi-turn chat, agents, RAG, or long contexts and asks about KV cache offloading, prefix cache sharing, prompt caching for self-hosted models, LMCache with Valkey, or lower TTFT or GPU cost. Not for Bedrock prompt caching, LLM response or semantic caching, or general application caching."
version: 1
---

# Distributed KV Caching

## Overview

During prefill, an inference engine computes attention key-value (KV) tensors for every prompt token. A shared L2 KV cache on Amazon ElastiCache keeps these tensors, so any GPU server in the fleet can load a returning prefix instead of computing it again. This decreases time-to-first-token (TTFT) and frees GPU time. The cache runs on `cache.i8ge.48xlarge` nodes with the valkey-large-object module; an LMCache server on each GPU server connects it to vLLM or SGLang over RDMA on Elastic Fabric Adapter (EFA).

> The AWS MCP server is recommended for sandboxed execution and audit logging. Every step also works with the AWS CLI directly. Secret steps MUST NOT go through an AWS API tool ([Security considerations](#security-considerations)).

## When this skill applies

- Self-hosted open-weight LLMs on GPUs (EC2, EKS, or similar) with vLLM or SGLang, directly or as vLLM workers under NVIDIA Dynamo or llm-d
- Long shared prompt prefixes (system prompts, RAG context, tool definitions, multi-turn history)
- Several GPU servers, changing routing, or GPU and host memory that evict prefixes before reuse
- A goal of lower TTFT, more requests per GPU, or lower cost per request

**TensorRT-LLM:** No final TensorRT-LLM release includes the LMCache MP connector; pre-release builds do, and they work with this setup. This skill gives no TensorRT-LLM engine steps; the LMCache server and ElastiCache steps are the same for every engine. For the engine side, follow the [TensorRT-LLM release notes](https://github.com/NVIDIA/TensorRT-LLM/releases) and the [LMCache docs](https://docs.lmcache.ai/getting_started/quickstart.html). KVTrace records only vLLM and SGLang.

## When this skill does not apply

- Amazon Bedrock managed inference (no self-hosted GPUs): point the builder to Bedrock prompt caching.
- Application caching (session stores, database query caching), LLM response caching, or semantic caching: route to the `amazon-elasticache` skill.
- Short or never-repeated prompts (classification, translation, moderation), output-dominated work, or diffusion models.

## Architecture

```
GPU Fleet                         Caching Layer                    Shared KV Store
┌─────────────┐                  ┌──────────────┐                ┌────────────────────────┐
│ vLLM/SGLang  │──ZMQ/gRPC──────▶│ LMCache MP   │──EFA RDMA────▶│ ElastiCache             │
│ Replica A    │                  │ Server       │   (or TCP)     │ cache.i8ge.48xlarge     │
├─────────────┤                  │              │                │ Valkey 9.1+ large-obj   │
│ vLLM/SGLang  │──ZMQ/gRPC──────▶│ L1: CPU RAM  │                │ DRAM + NVMe tiers       │
│ Replica B    │                  │ L2: Valkey   │                │ per shard               │
└─────────────┘                  └──────────────┘                └────────────────────────┘
```

**Write path:** after prefill, KV chunks go to LMCache L1 (CPU RAM), then asynchronously to L2. **Read path:** LMCache looks up L1, then L2, and loads hits into L1; the engine copies them to GPU memory.

## Transports

The `transport` field of the LMCache Valkey L2 adapter selects the transport. Every reference uses this definition.

| Transport | Data commands | Key type | Uses the NVMe tier | Needs EFA | LMCache build needs | TTL write | Use for |
|---|---|---|---|---|---|---|---|
| `tcp` (default) | `SET`, `GET`, `EXISTS`, `DEL` over TLS | Plain Valkey string | No | No | The Valkey L2 adapter (any build) | In the same `SET ... EX` | Functional tests. Works with any ElastiCache Valkey cluster. |
| `blob-tcp` | `BLOB.TCP_SET`, `BLOB.TCP_GET` over TLS | Module object | Yes | No | `blob_tcp_worker_pool.py` in `lmcache/v1/distributed/l2_adapters/valkey/` | Separate `EXPIRE`, not atomic | Tests of the module path on hosts without EFA |
| `rdma` | `BLOB.RDMA_SET`, `BLOB.RDMA_GET`, zero-copy over EFA. Control commands use TLS. | Module object | Yes | Yes, with RDMA write on the `efa-direct` fabric | `rdma_worker_pool.py` in the same folder, and `valkey-glide-sync` with RDMA | Separate `EXPIRE`, not atomic | Production |

`blob-tcp` and `rdma` write the same key type and can share a `key_prefix`. `tcp` MUST NOT share a `key_prefix` with either: a plain `GET` cannot read a module key, and the module cannot read a plain string.

## Reference loading

Load only the references for the current step: the [Typical workflow](#typical-workflow) names them. Do not preload all references. Before you run a command block from any reference, run "Shell setup and helpers" in [references/elasticache-setup.md](references/elasticache-setup.md): every reference uses its variables and helpers.

| Reference | Load when |
|-----------|-----------|
| [references/cost-assessment.md](references/cost-assessment.md) | Is L2 worth it? Measure recompute, run KVTrace, build the business case |
| [references/elasticache-setup.md](references/elasticache-setup.md) | Create, check, or delete the cluster, users, ACLs, eviction; before any command block (shell helpers) |
| [references/client-setup.md](references/client-setup.md) | Prepare a GPU server (EFA, memlock, security groups, Availability Zone) |
| [references/lmcache-setup.md](references/lmcache-setup.md) | Install, start, or tune LMCache; connect vLLM or SGLang |
| [references/optimization.md](references/optimization.md) | Size, choose what to cache, tune, benchmarks, hybrid models, monitoring |
| [references/troubleshooting.md](references/troubleshooting.md) | An error or unexpected behavior |

## Typical workflow

1. **Assess fit and cost** with KVTrace; if the savings do not exceed the cluster cost, stop ([cost-assessment.md](references/cost-assessment.md)).
2. **Size the cache** ([optimization.md](references/optimization.md)).
3. **Create the cluster** after the builder approves the shards, node type, hourly price, and monthly estimate ([elasticache-setup.md](references/elasticache-setup.md) ("Create the cluster")).
4. **Prepare the GPU servers** ([client-setup.md](references/client-setup.md), with the security group of [elasticache-setup.md](references/elasticache-setup.md)).
5. **Start LMCache, connect the engine, and prove L2 reads** ([lmcache-setup.md](references/lmcache-setup.md), with "Verify the cluster" in [elasticache-setup.md](references/elasticache-setup.md)).
6. **Tune for cost or latency** ([optimization.md](references/optimization.md)).
7. **Validate the investment** ([cost-assessment.md](references/cost-assessment.md)).

## Rules

- **Ephemeral data.** No durability, replicas, or snapshots; node replacement and patching empty the cache.
- **Same Availability Zone.** The cluster, the LMCache servers, and the GPU servers MUST be in one Availability Zone, in the GPU servers' subnet. EFA does not cross an Availability Zone or a Local Zone boundary; plan one cache per Availability Zone.
- **Transport.** Production SHOULD use `rdma`; `tcp` and `blob-tcp` are for functional tests ([Transports](#transports)).
- **Key prefix.** Every LMCache adapter MUST set a non-empty `key_prefix` that matches `^[A-Za-z0-9._:-]+$`, one per model, model version, TP layout, and key type. Reject any value with glob characters, spaces, or other special characters before creating the ACL user.
- **Versions.** Install the latest release of each component; the minimum is the first release with the feature. Run the feature checks after each install or upgrade; if they fail, follow the authoritative docs ([lmcache-setup.md](references/lmcache-setup.md) ("Software requirements")). The cluster MUST run Valkey 9.1 or later. The LMCache server and the engine image MUST have the same LMCache version (the multiprocess protocol changes between versions).
- **Stable cache keys.** Every engine and LMCache process MUST run with `PYTHONHASHSEED=0`. Every LMCache server MUST use the same `--hash-algorithm` (`sha256_cbor`), never `builtin`.
- **Security group.** One group with a self-referencing all-traffic rule in both directions MUST be on the cache and every GPU server interface; revoke its default `0.0.0.0/0` egress rule.
- **Host tier size.** Start `--l1-size-gb` at about half of the DRAM on the NUMA node of LMCache, below the pinned-memory limit; it MUST hold the prefetch of the longest prompt plus pending writes. Start with the default watermark (0.8) and eviction ratio (0.2).
- **Registered memory on RDMA.** On 4 KiB pages, (`num_workers` / EFA devices) × `--l1-size-gb` MUST stay below the device `max_mr_size` (`ibv_devinfo -v`). For a larger tier, back L1 with 2 MiB hugepages ([lmcache-setup.md](references/lmcache-setup.md) ("Registered memory and hugepages")).
- **One L2 adapter.** Pass one `--l2-adapter`; LMCache writes every chunk to every adapter.
- **Eviction.** Choose before the create; the module obeys `maxmemory-policy`. **Option A**, default group (`volatile-lru`): set `ttl_seconds`, so every LMCache key can be evicted (keys with no TTL are never evicted, and writes fail when full). **Option B**, custom group (`allkeys-lru`, `cluster-enabled yes`): no TTL needed; dedicated cluster. After the cache fills, `evicted_keys` MUST grow and `largeobj_disk_capacity_exceeded` MUST stay 0 on every primary ([elasticache-setup.md](references/elasticache-setup.md) ("Eviction policy and TTL")).
- **Shard count.** Fixed at create time; a new cluster starts empty ([elasticache-setup.md](references/elasticache-setup.md) ("Shard count and capacity")).
- **Costly actions.** Before you create or delete the cluster, you MUST list what changes, give the cost, and get explicit approval.
- **Attribution.** Before any AWS CLI block, set `AWS_SDK_UA_APP_ID=AWSSkill-ElastiCache`. Every resource this skill creates MUST carry `Key=created_by,Value=distributed-kv-caching-skill Key=generation_model,Value=<your-model-id>` and the `Project` tag, appended to the builder's tags. "Shell setup and helpers" in [elasticache-setup.md](references/elasticache-setup.md) sets both.
- **Authoritative docs.** When the LMCache, valkey-glide, vLLM, SGLang, TensorRT-LLM, or ElastiCache docs disagree with this skill about versions, flags, or limits, follow the docs ([Additional resources](#additional-resources)).

## Inside NVIDIA Dynamo, llm-d, or Kubernetes

- **Dynamo.** Run `lmcache server` beside each `python -m dynamo.vllm` worker, with the `--kv-transfer-config` from [lmcache-setup.md](references/lmcache-setup.md) ("Connect vLLM"). Do not pass the example's `--disable-hybrid-kv-cache-manager` for hybrid models ([optimization.md](references/optimization.md) ("Hybrid models (attention + recurrent layers)")).
- **llm-d.** Replace the in-process `LMCacheConnectorV1` overlay of its tiered prefix cache guides with the multiprocess connector and server.
- **KServe, Ray Serve, NVIDIA NIM.** The setup applies only when the layer runs vLLM or SGLang, takes the engine's LMCache flags (vLLM `--kv-transfer-config`, SGLang `--enable-lmcache --lmcache-config-file`; Ray Serve LLM: `engine_kwargs`; the KServe Hugging Face vLLM runtime: container `args`), and can run `lmcache server` beside each replica. For NIM, check its docs for a way to pass engine arguments; if there is none, say that this skill does not support it.
- **Kubernetes.** Request EFA devices through the EFA device plugin. The node container runtime MUST give unlimited memlock ([client-setup.md](references/client-setup.md) ("Memlock limits")).
- **Routers.** The Dynamo KV router and the llm-d prefix cache scorer do not count blocks in this cache. Keep the current routing.

## Not supported

- NVIDIA Dynamo's KV Cache Runner (KVCR) and NIXL storage plugins, Mooncake, and engine connectors that do not use LMCache.
- Amazon SageMaker, serverless caches, replicas, snapshots, Multi-AZ, and Global Datastore.

Say so plainly, and do not invent workarounds.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled
files from different places. Determine how the skill was loaded before reading
a reference or running a script:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not
  installed on the local filesystem. You MUST fetch each reference or script
  via `retrieve_skill` with the `file` parameter (e.g.
  `file="references/elasticache-setup.md"`), and run the script from the returned
  content. Do NOT `file_read` these paths locally — they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/distributed-kv-caching/` or
  `~/.claude/skills/distributed-kv-caching/`): Read and run files from the
  local skill directory.

In both modes, a link inside a reference gives the path from the skill folder
(for example `references/elasticache-setup.md#teardown` or `SKILL.md#rules`):
resolve it against the skill folder, not the folder of the reference. Through
`retrieve_skill`, pass the part before `#` as `file`.

This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory. Never fetch or write customer data through `retrieve_skill`.

## Security considerations

The cache holds KV tensors derived from prompts. Tell the builder about these controls.

- **Secret steps.** Commands that create, read, or use a secret (the cache password or the LMCache API key) MUST run only in a shell where the secret goes to a pipe or a 0600 file, never through `call_aws` or another AWS API tool that returns the response. You MUST NOT print a secret or add `--debug`. If no such shell is available, stop and ask the builder ([elasticache-setup.md](references/elasticache-setup.md) ("Secret steps")).
- **Redaction.** Before you show or share any log, config, `INFO` output, or support material, redact passwords, API keys, cache endpoints, account IDs, `cache_salt` values, and prompt-derived content. This applies to `journalctl` output, LMCache HTTP API responses, CloudWatch Logs excerpts, and any text collected for a support case.
- **Encryption in transit (required).** Mode `required`. Control traffic and `tcp`/`blob-tcp` data use TLS. RDMA data transfers bypass TLS and the module does not encrypt them; on supported Nitro instance types (`cache.i8ge`, P5, P5e, P5en, and others listed in the [EC2 encryption-in-transit table](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/data-protection.html)), the Nitro System automatically encrypts all traffic between instances in the same VPC with AEAD 256-bit keys, which covers the EFA RDMA path. The engine-to-LMCache request channel (ZMQ or gRPC) has no TLS; bind it to loopback when the engine is on the same host, or to the private IP with `--api-key-file` when it crosses hosts — in both cases, Nitro encryption protects the wire between supported instances.
- **Encryption at rest.** You SHOULD pass `--at-rest-encryption-enabled`. ElastiCache encrypts the NVMe tier with LUKS and a KMS-derived data key.
- **Password authentication.** The LMCache adapter does not support IAM authentication, so LMCache MUST use a password user. The password stays in AWS Secrets Manager and MUST NOT be in a config file, on a command line, or in a log ([elasticache-setup.md](references/elasticache-setup.md) ("Cache password secret")); LMCache starts through the [launcher](references/lmcache-setup.md) ("Launcher (password from Secrets Manager)"). The instance role gets only `secretsmanager:GetSecretValue` on the secret, plus `kms:Decrypt` through Secrets Manager for a customer managed key.
- **Least-privilege ACLs.** A Valkey user group turns off the `default` user; put only the LMCache user in it, limited to `~<key_prefix>@*` and the commands of its transport. You MUST NOT grant `+@all` or `~*` ([elasticache-setup.md](references/elasticache-setup.md) ("Users and ACL setup")).
- **Scoped security group.** Only the cache, the GPU servers, and the LMCache servers are members. You MUST NOT open it to `0.0.0.0/0` or to unrelated workloads.
- **Network isolation.** Private subnets only; the cache has no public endpoint. For installs, use a private mirror or staged artifacts first (for example CodeArtifact and S3), then VPC endpoints, then a NAT gateway only if the builder's policy allows internet egress.
- **LMCache server exposure.** Use `--api-key-file`, and keep the HTTP API on loopback. Bind the request port as [lmcache-setup.md](references/lmcache-setup.md) ("API key and metrics endpoint") says. You MUST NOT pass `--run-script-api-enabled` (it runs caller code). Bind KVTrace event sockets to loopback. Run LMCache only on hosts dedicated to inference.
- **Trust domain.** Every principal that can write to the cluster (the cache user, a holder of an LMCache API key) can write KV that every reader of that `key_prefix` loads with no check. Use one cluster per trust domain.
- **Tenant isolation.** A shared tier lets one tenant infer from TTFT that another sent the same prefix: isolate such tenants on separate caches. Tenants that share a cache MUST send different `cache_salt` values (a vLLM request field that LMCache puts in the key; at most 128 characters, no `@`, `/`, or `\`).
- **Logging and monitoring.** CloudTrail logs API calls. Deliver the slow and engine logs to a CloudWatch Logs group encrypted with a customer managed key; alarm on authentication failures and cluster health.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `BLOB.RDMA_HELLO` works, the first RDMA transfer fails | A self-referencing rule is missing | [troubleshooting.md](references/troubleshooting.md) ("RDMA transfer fails after successful HELLO") |
| `WRONGPASS` although the password is correct | The build passes the user name first, by position, to `ServerCredentials` | [troubleshooting.md](references/troubleshooting.md) ("WRONGPASS when LMCache connects"); swap only for that build |
| Writes fail when the cache is full, `evicted_keys` stays flat | `volatile-lru` and LMCache keys with no TTL | "Eviction policy and TTL" in [elasticache-setup.md](references/elasticache-setup.md) |
| `Registering the L1 arena ... failed` | Over `max_mr_size`, or memlock limited | [lmcache-setup.md](references/lmcache-setup.md) ("Registered memory and hugepages") |

For other symptoms, load [references/troubleshooting.md](references/troubleshooting.md).

## Additional resources

Use these sources for current versions, flags, prices, and limits.

- [What is Amazon ElastiCache?](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/WhatIs.html)
- [ElastiCache supported node types](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/CacheNodes.SupportedTypes.html)
- [ElastiCache role-based access control (RBAC)](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Clusters.RBAC.html)
- [ElastiCache in-transit encryption](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/in-transit-encryption.html) and [at-rest encryption](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/at-rest-encryption.html)
- [ElastiCache parameter groups](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/ParameterGroups.html)
- [ElastiCache CloudWatch metrics](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/CacheMetrics.html)
- [ElastiCache pricing](https://aws.amazon.com/elasticache/pricing/)
- [Elastic Fabric Adapter (EFA) user guide](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa.html)
- [AWS Secrets Manager user guide](https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html)
- [LMCache installation guide](https://docs.lmcache.ai/getting_started/installation.html), [LMCache Valkey L2 adapter](https://docs.lmcache.ai/mp/l2_storage/valkey.html), and [LMCache releases](https://github.com/LMCache/LMCache/releases)
- [valkey-glide releases](https://github.com/valkey-io/valkey-glide/releases)
- [vLLM documentation](https://docs.vllm.ai/en/latest/), [SGLang documentation](https://docs.sglang.ai/), and [TensorRT-LLM releases](https://github.com/NVIDIA/TensorRT-LLM/releases)
- [KVTrace](https://github.com/aws-samples/amazon-elasticache-samples/tree/main/kvtrace)
