# Cost Assessment: Is an L2 KV Cache Worth It?

## Table of contents

- Measure recompute
- When L2 pays for itself
- Cost model
- Estimate with KVTrace
- Business case
- Decision framework
- Validate after deployment

## Measure recompute

The main question: **how much GPU time does the fleet spend to compute prefixes that a cache could serve?** If returning conversations already hit the GPU prefix cache (L0) and the host tier (L1), an L2 adds cost and little benefit.

**Step 1: GPU prefix cache hit rate.** Divide the increments of two samples a few minutes apart.

```bash
# vLLM: hit rate = rate(vllm:prefix_cache_hits_total) / rate(vllm:prefix_cache_queries_total)
curl -s http://<vllm-host>:8000/metrics | grep -E '^vllm:prefix_cache_(hits|queries)_total'
# SGLang (start it with --enable-metrics):
curl -s http://<sglang-host>:30000/metrics | grep cache_hit_rate     # sglang:cache_hit_rate
```

- **Above 90%:** L2 adds little, unless the fleet has several replicas without session affinity, restarts, or autoscaling (L0 is per process).
- **50-90%:** L2 catches what L0 evicts.
- **Below 50%:** L2 has the most to gain.

**Step 2: Recompute fraction.** `vllm:prompt_tokens_by_source_total` splits prompt tokens into `local_compute`, `local_cache_hit` (L0), and `external_kv_transfer` (L1 + L2). The recompute fraction, `local_compute` / all sources over all replicas, is an upper limit of what L2 can remove, not the savings. `kvtrace tiers` reads the same counters; its L1/L2 split is an estimate.

## When L2 pays for itself

L2 caching can be worth it when one or more of these are true **and** the fleet passes the break-even rule in [Cost model](#cost-model):

- **Long-context multi-turn conversations** (legal agents, coding assistants, RAG with 32K-128K tokens per turn) ([optimization.md](references/optimization.md#benchmarks)).
- **Several replicas without session affinity**, or **frequent restarts or autoscaling**: GPU prefix caches are per process.
- **TTFT targets on returning conversations**, which can decide the case when cost alone does not pay.

It is usually not worth it when **all** are true: one session-affine replica, GPU cache hit rate above 90%, short unique prompts, a low request rate, and cost first with a longer TTFT accepted on misses.

Without a trace, these factors only decide whether to run KVTrace: multi-turn history, resent RAG documents or tool definitions, and replicas without session affinity (high); restarts or autoscaling (medium); a short shared system prompt (low).

## Cost model

This section is the one home for the cost symbols and break-even rules. The cache cost is fixed per shard and the savings grow with traffic, so a small fleet with a high recompute fraction can still fail to pay for one shard.

| Symbol | Meaning | Source |
|---|---|---|
| `S` | Tokens that L2 serves and that save GPU time, per second | KVTrace beneficial saved tokens at the chosen node count / the trace window (same run) |
| `P` | Prefill tokens per second of one replica (all its GPUs) | Measured, below |
| `G` | GPUs per replica (TP × PP) | Engine config |
| `c_g` | Price per GPU-hour | Builder's price, below |
| `n` | Shards (cache nodes) | Chosen node count |
| `c_n` | Price per cache node per hour | Builder's price, below |

```
GPU savings per hour = S / P × G × c_g
Cache cost per hour  = n × c_n
Net per month        = (GPU savings per hour − cache cost per hour) × 730
Break-even rate      S* = n × c_n × P / (G × c_g)
```

- L2 pays on cost alone only when `S` is above `S*`.
- Take `S` and the token counts from the same KVTrace run. You MUST NOT multiply a KVTrace hit rate by a token rate from another source: the hit rate counts hits that save no GPU time, and the other source counts other tokens.
- **`P`:** a prefill-only benchmark on one replica at the production prompt length, with enough concurrency to keep the GPUs busy: `vllm bench serve --dataset-name random --random-input-len <prompt-len> --random-output-len 1 --max-concurrency <n> --num-prompts <m>`; `P` = input tokens / time. Use the same `P` in KVTrace and the table; a wrong `P` scales every dollar figure.
- **Prices:** the builder's effective prices first (Savings Plans, Reserved Instances, Capacity Blocks); say which. Else on-demand:
  - GPU: `c_g` = instance price / GPUs per instance. `aws pricing get-products --region us-east-1 --service-code AmazonEC2 --filters Type=TERM_MATCH,Field=instanceType,Value=<instance-type> Type=TERM_MATCH,Field=regionCode,Value=<region> Type=TERM_MATCH,Field=operatingSystem,Value=Linux Type=TERM_MATCH,Field=tenancy,Value=Shared Type=TERM_MATCH,Field=preInstalledSw,Value=NA Type=TERM_MATCH,Field=capacitystatus,Value=Used`, `OnDemand` term; or the [EC2 on-demand pricing page](https://aws.amazon.com/ec2/pricing/on-demand/).
  - Cache node: `c_n` for `cache.i8ge.48xlarge` from the [ElastiCache pricing page](https://aws.amazon.com/elasticache/pricing/), or `aws pricing get-products --region us-east-1 --service-code AmazonElastiCache --filters Type=TERM_MATCH,Field=instanceType,Value=cache.i8ge.48xlarge Type=TERM_MATCH,Field=regionCode,Value=<region> Type=TERM_MATCH,Field=cacheEngine,Value=Valkey`, `OnDemand` term.
  - Each query MUST return exactly one product (`--query 'length(PriceList)'` gives 1). For 0 or more than 1, stop and list the values of the attribute in doubt: `aws pricing get-attribute-values --region us-east-1 --service-code <code> --attribute-name <name>`.
- **Per-GB basis:** KVTrace prices L2 per GB of node DRAM (`--cache-node-gb`, default 1237 GB). The node price on that basis is `c_n / 1237` per GB-hour. You MUST NOT divide the node price by the NVMe size (120 TB): that gives a price about 100 times too low, and every case looks like it pays.
- The [shard count](references/elasticache-setup.md#shard-count-and-capacity) is fixed at create time.

## Estimate with KVTrace

[KVTrace](https://github.com/aws-samples/amazon-elasticache-samples/tree/main/kvtrace) records KV cache events of a running vLLM or SGLang fleet, simulates a shared L2 at different sizes, and reports the savings and the break-even L2 price. When its README disagrees with this section, follow the README. Install from the repository (stage it and its dependencies in the builder's private mirror first if the Network isolation rule in [SKILL.md](SKILL.md#security-considerations) applies): you MUST NOT install the unrelated `kvtrace` package from PyPI.

```bash
git clone --depth 1 https://github.com/aws-samples/amazon-elasticache-samples.git
cd amazon-elasticache-samples/kvtrace
python3 -m venv .venv && .venv/bin/pip install .     # Python 3.9 or later
KVT=$PWD/.venv/bin/kvtrace

# 1. The engine MUST publish KV events. vLLM (SGLang takes the same JSON without
#    "enable_kv_cache_events"; see the README):
vllm serve <model> --enable-prefix-caching ... \
  --kv-events-config '{"enable_kv_cache_events": true, "publisher": "zmq", "endpoint": "tcp://127.0.0.1:5557", "replay_endpoint": "tcp://127.0.0.1:5558", "topic": "kv-events"}'

# 2. Record on every node for at least one full daily traffic cycle; inspect a few minutes after start
"$KVT" record --endpoint-mode bind --endpoint tcp://127.0.0.1:5557 \
    --replay-endpoint tcp://127.0.0.1:5558 --model <model-label> --node-id <node-id> \
    --metrics-url http://127.0.0.1:8000/metrics --duration <seconds> --out traces/
"$KVT" inspect traces/

# 3. Simulate L2 sizes in cache nodes (--l1-size-gb is GiB; the chunk size is the one the LMCache log shows)
"$KVT" simulate traces/ --preset llama-3.1-70b --tp 4 --kv-cache-dtype <engine value> \
    --chunk-tokens <chunk size> --host-tier-bytes-per-node <l1-size-gb>GiB \
    --cache-node-counts 1,2,3,4,6,8 -o sim.json

# 4. Report
"$KVT" report sim.json -o report.html --markdown report.md \
    --gpu-cost-per-hour <c_g> --gpus-per-replica <G> \
    --prefill-tokens-per-sec <P> --l2-cost-per-gb-hour <c_n / 1237>
```

- **Record:** exit status 3 means no KV event within 120 seconds: check `--endpoint-mode` and `--kv-events-config`. Under one hour gives rough monthly figures. Data-parallel engines: `--dp-ranks <N>`. Bind event sockets to loopback (with `bind`, the recorder binds and vLLM connects).
- **Several nodes:** each recorder MUST have its own `--node-id`; collect all node directories before `simulate`. If traces leave the account, pass the same `--anonymize-key-file` on every node and use safe labels.
- **KV size:** `--preset` (`llama-3.1-8b`, `llama-3.1-70b`, `qwen2.5-72b`, `qwen3-32b`, `deepseek-v3`), or `--model-config <config.json>` with `--tp` and `--pp`, or `--kv-bytes-per-token` (all workers).
- **L1 hits:** vLLM reports LMCache L1 loads as GPU prefix cache stores; `--host-tier-bytes-per-node` = the `--l1-size-gb` value in GiB emulates L1, so L1 hits do not count as L2 savings.
- **Capacity:** KVTrace models node DRAM only, so its hit rate is a lower bound; use the recommended capacity as a guide, and run `--capacity` at the usable NVMe size or `inf` for an upper estimate.
- **Bandwidth:** `simulate --contention on --cache-node-counts ... --prefill-tokens-per-sec <P>` (180 Gbit/s per node by default); take the larger of the capacity and bandwidth counts.
- **Measured tier split:** with LMCache running, pass `--extra-metrics-url http://127.0.0.1:8080/metrics` to `"$KVT" record`, then run `"$KVT" tiers traces/ --preset <name> --tp <n>`. KVTrace sends no `Authorization` header, so this works only without `--api-key-file` ([lmcache-setup.md](references/lmcache-setup.md#api-key-and-metrics-endpoint)). You MUST NOT remove `--api-key-file` for this; skip `tiers` instead.

The report gives: hit rate vs L2 capacity; GPU-hours and dollars saved, from beneficial saved tokens only (monthly figures use 30 days: use hourly × 730); a modeled TTFT saved per hit, without queueing (not measured); the break-even L2 price, gross savings per hour / (nodes × 1237 GB), to compare with `c_n / 1237`; and same-node vs cross-node reuse. Keep the recorded window as the baseline.

## Business case

Use the formulas of [Cost model](#cost-model). Say which price you used and that the savings are from KVTrace beneficial saved tokens.

| Row | Value |
|---|---|
| Fleet, prices | replicas, `G`, instance type; `c_g`, `c_n`, and their source |
| `S` at `n` nodes | from KVTrace |
| GPU savings per hour | `S / P × G × c_g` (or the KVTrace hourly figure) |
| Cache cost per hour, per month | `n × c_n`, × 730 |
| Net per month | (savings − cost) per hour × 730 |
| Break-even rate `S*` | `n × c_n × P / (G × c_g)` |
| TTFT change | KVTrace modeled figure, or a measured test. Say which |

Give savings as "up to" a figure, not a minimum. Freed GPU time saves money only with fewer servers or more traffic on the same servers: say which.

## Decision framework

Ask in order. Stop at the first clear answer.

```
1. One replica with session affinity and a GPU cache hit rate above 90%?
   ─── YES → L2 is probably not needed. Check again if the fleet grows.
2. Recompute fraction low, or prompts short and unique?
   ─── YES → L2 is probably not cost-effective. Consider L1-only caching.
3. Run KVTrace. Ratio R = break-even L2 price / (c_n / 1237)
   (= GPU savings per hour / cache cost per hour).
   ─── R is 2 or more → Deploy L2.
   ─── R from 1 to 2  → Marginal. Deploy only if the TTFT gain has product value.
   ─── R below 1      → L2 does not pay on cost. Deploy only for TTFT, and say so.
```

## Validate after deployment

- **Recompute:** `vllm:prompt_tokens_by_source_total{source="local_compute"}` per second, before and after.
- **L2 share** ([optimization.md](references/optimization.md#lmcache-metrics)) vs the prediction: `"$KVT" tiers traces/ --compare sim.json` on a new recording.
- **Throughput** and **TTFT** distributions; L2 helps the tail most (p95, p99).

Think again if the L2 share stays near zero (`lmcache_mp_num_chunks_loaded_total` counts L1 and L2, so it is no L2 signal); if the L2 share falls while `Evictions` rise, or KVTrace shows the hit rate still rising at the deployed count (too small; evictions alone are normal after the cache fills); or if the fleet moves to one session-affine replica or short unique prompts.
