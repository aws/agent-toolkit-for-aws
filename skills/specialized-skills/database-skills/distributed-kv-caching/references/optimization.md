# Optimization: What to Cache, Sizing, and Tuning

## Table of contents

- Workload patterns and caching benefit
- Benchmarks
- Hybrid models (attention + recurrent layers)
- Sizing the L2 cache
  - KV bytes per token
  - Shard count
- Tuning what gets written to L2
- Tuning presets
- Cache-aware routing
- Monitoring cache effectiveness

## Workload patterns and caching benefit

The benefit grows with **prefix overlap** (the share of request tokens that match a cached prefix), but L2 serves only the reuse that the GPU prefix cache (L0) and host tier (L1) miss: prefixes back after eviction, on another server, or after a restart. A short prefix that every request uses stays in L0 and L1.

| Pattern | Prefix overlap | L2 benefit | Why |
|---------|---------------|------------|-----|
| Long system prompt + user query | High | Low to medium | Every server holds it in L0 or L1; L2 helps after restarts, scale-out, evictions |
| RAG context + question | Medium to high | Only for the same documents in the same order right after the shared prefix | A hit needs identical tokens from the start |
| Agentic tool preamble + tool call | High | Medium to strong | Resent tool definitions and turns; sessions move between servers |
| Multi-turn conversations | High | Strong | Cached up to the last full chunk of the previous prompt. Generated tokens are not stored by default (the reply is recomputed); to store them, set `"lmcache.mp.save_decode_cache": true` in `kv_connector_extra_config` |
| Unique long documents | Low | Minimal | Seen once; the write is wasted |
| Short unique prompts | None | None | Recompute is faster than an L2 round trip |

The prompt layout decides the overlap more than any setting: static content first; no timestamps, request IDs, or user names before shared content; a fixed tool order and chat template; the same `cache_salt` for requests that may share KV, different salts for tenants that must not.

## Benchmarks

Amazon ElastiCache ran these benchmarks; every time is the TTFT of one request.

| Prompt size | KV size (TP4) | TTFT, no cache | TTFT, L2 hit | TTFT, GPU prefix hit |
|-------------|---------------|--------------|------------|----------------|
| 32K tokens | 2.6 GB | 6.5 s | 0.61 s | 0.51 s |
| 64K tokens | 5.1 GB | 13.3 s | 0.86 s | 0.68 s |
| 123K tokens | 9.5 GB | 26.7 s | 0.87 s | 0.58 s |

The L2 cost is the difference to the GPU-hit column (0.10 s to 0.29 s) and grows with the KV bytes. TTFT with no cache grows about linearly with prompt length; long prompts gain the most, because the L2 cost is small compared with their prefill.

You MUST NOT give these numbers to the builder as a forecast: they depend on the model, KV dtype, instance type, shard count, transport, and concurrency. Use KVTrace for the builder's workload ([cost-assessment.md](references/cost-assessment.md#estimate-with-kvtrace)).

## Hybrid models (attention + recurrent layers)

For validated models, see the [LMCache hybrid models guide](https://docs.lmcache.ai/mp/hybrid_models.html).

- **Sliding-window + full attention** (for example Gemma or gpt-oss): no extra setting.
- **Mamba, Gated DeltaNet, or other linear-attention hybrids:** LMCache stores the recurrent state in its own cache objects, separate from the attention KV. Start LMCache with `--separate-object-groups` (where it is the default, do not pass `--no-separate-object-groups`), and vLLM with `--enable-prefix-caching --mamba-cache-mode align`. Do not pass `--disable-hybrid-kv-cache-manager`.
- **Chunk size.** The connector raises `--chunk-size` to a multiple of the vLLM block size. Give KVTrace the chunk size that the LMCache log shows.
- **Accuracy check.** Cached and fresh runs are not bit-exact: validate with a score-level evaluation, not a token compare.
- **KV size.** The formula below covers attention only. Measure the stored bytes per token (KVTrace README), and pass the total to `kvtrace simulate --kv-bytes-per-token` (per worker: `kvtrace tiers --worker-kv-bytes-per-token`).

## Sizing the L2 cache

### KV bytes per token

```
KV bytes per token (L2, all workers) = layers × kv_heads_per_worker × head_dim × kv_dtype_bytes × 2 × tp
kv_heads_per_worker = max(1, kv_heads // tp)     # vLLM copies heads when TP > KV heads
kv_dtype_bytes      = 2 for bf16/fp16, 1 for fp8;  2 = one K and one V tensor per layer
```

With pipeline parallelism, each worker holds `layers / pp` layers and writes its own part, so the formula is the same.

- **TP above the KV head count** stores each head more than once: Qwen3-235B-A22B (94 layers, 4 KV heads, head_dim 128, fp8 KV) at TP8 stores 192,512 bytes per token against 96,256 distinct, twice the capacity and read bandwidth of TP4.
- **Multi-head latent attention (MLA)** (for example DeepSeek): every TP rank stores the full latent, so L2 holds `tp` copies. Use `kvtrace simulate --preset deepseek-v3` or `--model-config`.
- **KV dtype:** only `--kv-cache-dtype fp8` halves the bytes; FP8 weights alone do not. A dtype change needs a new `key_prefix` and an accuracy check ([lmcache-setup.md](references/lmcache-setup.md#connect-vllm)).
- **Object size:** one object is one chunk of one worker, `--chunk-size` × per-worker bytes per token (per object group on hybrid models). It MUST stay at or below 536,870,912 bytes (512 MiB).

Examples (bf16 KV, TP=1):

| Model | Layers | KV heads | Head dim | Bytes/token | 10K tokens |
|-------|--------|----------|----------|-------------|------------|
| Llama-3.1-8B | 32 | 8 | 128 | 131 KB | 1.3 GB |
| Llama-3.1-70B | 80 | 8 | 128 | 328 KB | 3.3 GB |
| Llama-3.1-405B | 126 | 8 | 128 | 516 KB | 5.2 GB |
| Qwen3-8B | 36 | 8 | 128 | 147 KB | 1.5 GB |

### Shard count

Capacity, bandwidth per node, and the fixed shard count: [elasticache-setup.md](references/elasticache-setup.md#shard-count-and-capacity). Hit rates per node count: KVTrace ([cost-assessment.md](references/cost-assessment.md#estimate-with-kvtrace)). Take the larger of the capacity need and the read need:

```
Cluster read need (GB/s) = L2 hit tokens per second × KV bytes per token / 1e9
Read need of one request  = KV bytes of the hit / the TTFT budget
Shards for bandwidth      = cluster read need (GB/s) × 8 / (per-node bandwidth in Gbit/s × 0.6)
```

Use the peak L2 hit rate (KVTrace, or `lmcache_mp_lookup_hit_l2_tokens_total`). The 0.6 factor keeps headroom for writes and bursts. The per-node bandwidth is the network value on the I8g page, in Gbit/s. Example: a returning 20K-token conversation on a 70B bf16 model is about 6.6 GB; in a 1 s TTFT budget it needs 6.6 GB/s (about 52 Gbit/s). A cluster read need of 30 GB/s on nodes of `B` Gbit/s needs 30 × 8 / (`B` × 0.6) shards, rounded up.

## Tuning what gets written to L2

- **`--chunk-size`** is the smallest unit that LMCache stores or loads. 256 is the default and a minimum (the connector can raise it); you MUST NOT use 1,024 ([lmcache-setup.md](references/lmcache-setup.md#flag-and-adapter-reference)). Smaller (for example 64) gives finer hits but more operations; larger (for example 512) loses more tokens at the boundary, because KV is reused only in whole chunks. Give KVTrace the value that the server logs.
- **`ttl_seconds`** is required under Option A and optional under Option B. For the value, the TTL write on each transport, and when not to set one, see [elasticache-setup.md](references/elasticache-setup.md#eviction-policy-and-ttl).
- **Store and prefetch policies:** see [lmcache-setup.md](references/lmcache-setup.md#l2-store-and-prefetch-policies).

## Tuning presets

The lowest L2 cost is the fewest shards that meet the capacity and read needs. `--eviction-policy` is the L1 policy, not `maxmemory-policy`.

| Goal | Settings | Reason |
|------|----------|--------|
| **Lowest TTFT or highest throughput** (most shared fleets) | `--chunk-size 256 --eviction-policy LRU --l2-store-policy default --l2-prefetch-policy default`, large L1 | Hot data in L1 and L2; L2 serves the long-prefix hits that L1 misses |
| **Small host DRAM** (L2 is the main store) | `--eviction-policy noop --l2-store-policy skip_l1 --l2-prefetch-policy skip_l1` | L1 is only a buffer; hits come from L2 |

## Cache-aware routing

Prefix- or session-affinity routing gives more L0 and L1 hits and fewer L2 reads. This skill does not validate a router; L2 serves misses wherever a request lands.

## Monitoring cache effectiveness

### LMCache metrics

Read with `lmc_metrics | grep '^lmcache_mp_'` (endpoint, authentication, and exposure: [lmcache-setup.md](references/lmcache-setup.md#api-key-and-metrics-endpoint)). Labels carry `model_name` and `cache_salt` (which can name a tenant). Counters appear after their first increment.

| Question | Prometheus query or metric |
|---|---|
| L2 share of prompt tokens | `rate(lmcache_mp_lookup_hit_l2_tokens_total[5m]) / rate(lmcache_mp_lookup_prompt_tokens_total[5m])` |
| Engine + LMCache share of prompt tokens | `rate(lmcache_mp_lookup_request_hit_tokens_total[5m]) / rate(lmcache_mp_lookup_prompt_tokens_total[5m])` |
| Chunks stored to L2, loaded from L2 | `lmcache_mp_l2_store_completed_objects_chunks_total`, `lmcache_mp_l2_prefetch_load_completed_chunks_total` |
| Keys that L2 had at lookup (loads can still fail) | `lmcache_mp_lookup_hit_l2_keys_total` (one key per object group, TP rank, and chunk) |
| L2 load failures | `lmcache_mp_l2_prefetch_failure_chunks_total` (`reason`), `lmcache_mp_timeouts_total` |
| L2 read throughput | `lmcache_mp_l2_load_throughput_GBs` |
| L1 pressure | `lmcache_mp_l1_usage_ratio`, `lmcache_mp_l1_allocation_failure_chunks_total{during="l2_prefetch"}` |
| L2 operations in flight | `lmcache_mp_num_inflight_l2_stores`, `lmcache_mp_num_inflight_l2_loads` |

`lmcache_mp_num_chunks_loaded_total` and `lmcache_mp_num_finished_stores_total` count L1 and L2 transfers: you MUST NOT use them for the L2 hit rate. An L2 share near zero while L2 stores grow means wasted L2 writes.

### ElastiCache metrics (CloudWatch)

For current names, see [ElastiCache CloudWatch metrics](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/CacheMetrics.html). If a name below is not on that page, use the `INFO largeobj` fields in [elasticache-setup.md](references/elasticache-setup.md#verify-the-cluster).

| Metric | Meaning |
|--------|---------|
| `LargeObjectBasedCmds` | BLOB command throughput (TCP and RDMA) |
| `LargeObjectBasedCmdsLatency` | Engine time per command. It can stay flat when the node is bandwidth-bound |
| `LargeObjectDRAMHitRate` | Share of GETs from DRAM, not NVMe. Low: the hot set exceeds the DRAM read cache; only more shards add DRAM |
| `LargeObjectDiskUsedBytes`, `LargeObjectDiskUtilization` | NVMe tier usage. If the percentage reads 0 while the bytes grow, use the bytes |
| `EFABytesIn` / `EFABytesOut` | RDMA payload throughput (no `blob-tcp` traffic) |
| `NetworkBandwidthOutAllowanceExceeded` | Packets dropped because the node is over its bandwidth |
| `Evictions` | Rising evictions after the cache fills are normal |

Alarm on a sustained drop of the L2 share, and on `AuthenticationFailures`, `CommandAuthorizationFailures`, and `KeyAuthorizationFailures`.

**More shards needed:** `NetworkBandwidthOutAllowanceExceeded` above 0, EFA or network bytes near the node limit on the [I8g page](https://aws.amazon.com/ec2/instance-types/i8g/), or on the GPU servers a falling `lmcache_mp_l2_load_throughput_GBs` with a high `lmcache_mp_num_inflight_l2_loads`. Create a new cluster with more shards and move the fleet; it starts empty ([elasticache-setup.md](references/elasticache-setup.md#shard-count-and-capacity)).
