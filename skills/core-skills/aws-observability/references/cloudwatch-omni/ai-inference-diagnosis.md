# Diagnosing self-hosted LLM inference workloads in CloudWatch Omni

How to answer "**why is time to first token high**", "**why is throughput low**", "**why are
requests queueing on my vLLM server**", "**which of my inference workloads have problems**", and
reliability questions such as restart or OOM-kill cycles and blocked rollouts, for self-hosted LLM
serving on GPUs (for example vLLM or SGLang, behind KServe or Ray Serve). It works from the engine,
GPU, and platform telemetry already in CloudWatch, and ends in a committed, quantified verdict.

This file is the *investigation method*. It does not restate:

- **Running PromQL** — the endpoint, signing, label and series discovery, gauges vs counters, and
  histogram reads are in [../cloudwatch/promql.md](../cloudwatch/promql.md), which
  [query/promql-metrics.md](query/promql-metrics.md) extends with the Omni specifics.
- **Traces and logs** — the SQL over `traces.default` and `logs.default` is in
  [query/sql-logs-traces.md](query/sql-logs-traces.md).
- **Getting the telemetry into CloudWatch** — if the workload has no engine or GPU metrics yet,
  that is first-time setup; do not set it up from here. First confirm the metrics are really
  absent rather than renamed, under other labels, or stale (section 2); an empty query alone does
  not show that. For vLLM on ECS or EKS, route to the `setting-up-cloudwatch-observability` skill,
  which has the AI Inference setup; do not write the collector or exporter setup yourself from
  this skill's OpenTelemetry references. For another engine (SGLang, Ray Serve) or platform, do not
  route there: say that the guided setup covers only vLLM on ECS and EKS, so its steps do not
  apply unchanged, and that the engine's Prometheus metrics and GPU (DCGM) metrics have to reach
  CloudWatch first. Until then, diagnose only from what already arrives (platform,
  container, and log signals) and label the verdict as limited by the missing telemetry.

**Diagnosis is read-only.** Run read-only queries and commands only, and present every change
(configuration, scaling, restart) as a recommendation for the user to apply.

Help the operator identify what limits inference latency, throughput, reliability, or cost efficiency. Use this file as a structured investigation guide across different tools, frameworks, and deployment setups. Treat KServe, Ray Serve, vLLM, SGLang, DCGM, and NCCL as examples; adapt to the stack actually deployed.

Let the model choose the investigation path and conclusions from available telemetry and context. Treat the patterns below as hypotheses to test, not deterministic diagnosis rules. Distinguish observations, likely explanations, and confirmed findings. Explain results in language an operator can act on.

Measure before you match patterns: start from the load model and the physical floors, then confirm or reject each section 6 pattern with a number. Give a committed, quantified answer: the limiter of the objective, the measurements that prove it, and levers ranked by predicted gain.

## Investigation layers

| Layer | Investigation focus |
| --- | --- |
| Orchestration | Routing, queuing, admission control, autoscaling, replica health, placement, and cold starts in tools such as KServe and Ray Serve. |
| Inference engine | Scheduler behavior, batching, prefill/decode performance, KV-cache capacity, prefix-cache efficiency, and configuration in engines such as vLLM and SGLang. |
| Host / GPU node | CPU utilization and throttling, preprocessing, memory and I/O pressure, VRAM capacity, tensor compute, device memory bandwidth (HBM or GDDR), and GPU health. |
| Network / interconnect | Request transport, PCIe, NVLink, cross-node networking, collective communication, and KV-cache transfer between serving stages. |

Follow the request path across these layers. A downstream symptom can originate upstream; low GPU activity, for example, may reflect a routing, CPU, or KV-transfer bottleneck.

## 1. Establish scope, objective, and topology

Do steps 1–3 before the first query. Steps 4–8 can run with the first pass.

1. Resolve the application, service, deployment, model, or host from the user's request. If the request names no target, or several remain plausible, ask before making a service-specific diagnosis. For a question about a set of workloads ("which workloads have problems", or what the AI Inference page lists), use Fleet triage (section 3a).
2. Identify the objective: TTFT, inter-token latency (ITL), end-to-end latency, throughput, errors, or cost efficiency. Use the requested time range; otherwise choose one that covers the symptom and a healthy baseline, and state it.
3. Identify the load model. Read the client or load-generator metadata when it is available: concurrency, think time, request rate, prompt and output limits, timeouts, retries, and any stated test intent. Classify the client:
   - **Closed loop:** each worker sends its next request when the previous one returns, so the client sets the in-flight population N.
   - **Open loop:** requests arrive at a rate that does not depend on latency.
   Without metadata, test for a closed loop: deduplicated in-flight work (waiting + running) stays flat for hours, and N ÷ completion rate ≈ measured mean end-to-end latency. State the load model, N, and whether the queue is intended.
4. Discover the actual labels and map service → replicas → engine instances → hosts/GPUs. Use PromQL label and series discovery ([query/promql-metrics.md](query/promql-metrics.md)) rather than assuming label names or pod-name patterns.
5. Read the resolved configuration, not only the launch arguments (they omit defaults and values resolved at startup): engine/version, model architecture and precision, GPU type/count, parallelism, batching/token limits, KV allocation and dtype, prefix caching, scheduler settings, routing, autoscaling limits, and the serving containers' CPU/memory requests and limits. Prefer, in order:
   - The engine startup log: version, resolved config, memory budget lines (weights, graph memory, KV size in tokens), the communication backend chosen and why, warnings, and sizing hints. Find the container start time first, then read about 30 minutes after it, filtered to the pod or task stream.
   - Engine info metrics that publish resolved config, such as a cache-config info series.
   - Deployment manifests: image tag, resources, rollout strategy, replicas, autoscaler bounds. Floating tags can run different versions in one fleet; read the version per replica.
   Treat engine sizing hints as candidates; check them against runtime free GPU memory.
   Do not repeat secrets you find in logs, launch arguments, manifests, or environment (API keys, access tokens, model-hub tokens); report that one is set, not its value.
6. Read the serving platform's own state before reasoning from metrics: readiness and status conditions (for example a KServe InferenceService's `Ready`/`IngressReady`, or a Ray Serve application's and deployment's status), pod phases and events, and the error message of any deployment or replica that failed to start. A platform error can explain a symptom that engine and GPU metrics only reflect. Where this state is not available to you, note the gap and continue with the evidence you have.
7. Check for recent changes to the target: deployment, configuration, scaling-policy, and resource-limit changes in the platform's audit or deployment history. Where available, correlate their timing with the symptom's onset before treating the symptom as structural; if no change history is accessible, note it as a gap and continue.
8. Determine whether prefill and decode share resources or run in separate instances/pools. For disaggregated serving, identify stage roles, placement, replica ratios, routing/pairing, and KV-transfer configuration. A transfer connector alone does not prove prefill/decode separation; confirm its role and use.

Apply the target selector to every query. Preserve replica, host, GPU, rank, and stage identity when comparing resources. Query fleet-wide only when the objective requires it; do not blend unrelated workloads or prefill/decode pools.

Identity labels can change inside the window. Collector relabels, restarts, and new task revisions create a second series for the same workload, and pinning a label that changed cuts history. Count series per workload before you aggregate: for gauges, take the max by workload key before any sum; for time averages, deduplicate first. If history ends suddenly, look for the same workload under another label value before reporting no baseline.

Treat configuration as evidence of the intended setup. Corroborate it with runtime state where available; configuration alone does not establish a bottleneck or guarantee that the agent can diagnose one.

## 2. Validate telemetry before interpreting values

- Discover live metric names and definitions. Names, prefixes, labels, units, and available phases vary by engine version, exporter, and collector. Do not assume `vllm:`, `vllm_`, `ray_vllm_`, or any other family is present or obsolete. Do not map engines by string substitution.
- Distinguish missing, stale, unsupported, and zero-valued signals. Inspect the latest sample timestamp and scrape/export health. Judge freshness against the collection interval; an empty query does not establish an idle or healthy service.
- If widening the range recovers older data, label it historical and state the reporting gap. Do not silently substitute it for current evidence or conclude that a missing exporter means the workload is down.
- Use rates for counters over intervals supported by the scrape cadence. Detect resets, sparse samples, and low request counts before interpreting rates or tail percentiles.
- Inspect histogram buckets when a percentile sits on a boundary. Report limited resolution; do not turn a bucket estimate into an exact measurement or universal upper bound. A percentile in the terminal `+Inf` bucket is especially unreliable. To test a tail against a timeout or SLO, read the fraction of requests above a real bucket edge rather than comparing an interpolated percentile with the threshold.
- Compare the same population and time interval. Do not add or subtract independently aggregated p99 values to decompose latency. Prefer matched request traces or phase distributions and describe their limits.
- Interpret cache-hit rates only with queries, traffic shape, and config. Nonzero cache queries demonstrate activity; a low hit ratio does not establish that caching is disabled. No queries alone does not establish it either. When caching is off, hit counters are zero by definition; estimate the reuse instead (see Prefix-cache inefficiency).
- Cross-check each derived value with an independent measurement: a histogram-count rate against a completion counter (engine histograms scraped with the Prometheus receiver are cumulative: take each series' count first, `sum(rate(histogram_count(<m>)[5m:30s]))`, because `histogram_count(rate(<m>[5m]))` can come back many times too high), a histogram mean against a counter ratio, engine log throughput against token counters, Little's law against measured latency. When they disagree, prefer the counter and report it.
- Treat engine-estimated efficiency metrics (MFU, FLOPs, bytes read) as unvalidated until they agree with a first-principles model within about 20% (FLOPs ≈ 2 × active parameters × computed tokens/s ÷ GPUs). A value far below the model is an estimator defect, not idle hardware.
- Distinguish a series at zero from an absent one. A disabled feature can export zeros; a ratio of two zero counters is undefined.
- Some metrics count only first-pass work. Preempted, retried, or recomputed requests add work and waiting that token, prefill, and queue-time metrics may not show (see Preemption churn).

Use metrics for aggregate trends and traces/logs for request paths, handoffs, errors, or unresolved ambiguity. Prefer PromQL ([query/promql-metrics.md](query/promql-metrics.md)) when metrics are exposed there, and SQL over `traces.default` / `logs.default` ([query/sql-logs-traces.md](query/sql-logs-traces.md)) for traces and logs; do not forbid relevant traces during latency analysis.

## 3. Take a small, adaptive first pass

Fetch the relevant available signals in one batch where supported, then read the results before expanding. Cover the reported symptom and representative signals from each applicable layer; do not require a fixed list of metrics that another engine or topology may not expose.

| Question | Initial evidence |
| --- | --- |
| What changed for the user? | Request rate, successful output tokens/sec, error/rejection rate, relevant latency distribution, and a healthy baseline if available. |
| Where does work wait? | Gateway/admission queues, engine waiting/running counts, scheduling limits, and per-stage queues for disaggregated serving. |
| Which phase is slow? | Queue, prefill, first-token delivery, decode/ITL, and KV handoff where applicable. |
| Is memory constraining scheduling? | KV usage, waiting reason, preemptions per completed request, KV pool size in tokens, resident tokens per sequence, VRAM usage and free memory, and configured capacity. |
| Are resources busy doing useful work? | Tensor activity, DRAM activity, GPU utilization, host CPU/throttling, and stage-specific load. |
| Is orchestration or transport limiting delivery? | Replica health and load spread, desired/ready replicas, placement failures, transfer/collective latency or errors. |

Adapt this pass to the objective. For high TTFT, prioritize the path to first-token delivery. For low decode throughput, prioritize batch size, context length, device memory bandwidth, and collectives. For errors, prioritize rejection, replica health, and correlated events.

Stop when the evidence answers the question with adequate confidence. Each follow-up query should test a named hypothesis, distinguish competing causes, or resolve a material gap. Inspect per-replica, per-rank, or per-stage detail when aggregates suggest imbalance.

## 3a. Fleet triage

Use this when the question covers a set of workloads.

1. Enumerate every serving engine with more than one discovery marker (engine metric families, workload-type and platform labels), reconciled with the orchestration inventory.
2. Run one batched screen, grouped by workload identity:
   - **Waiting:** sustained queue and its reason.
   - **Waste:** preemptions per completion, share finished by length, retries.
   - **Efficiency:** ITL as a multiple of its decode floor (section 4).
   - **Reliability:** restarts and termination reasons over several days (OOM kills), pending or failed rollouts, client errors and timeouts.
   - **Hardware:** power or thermal caps, clocks, XID, and which signals are missing.
3. Without an SLO, call a workload a problem when a screen shows a sustained queue, wasted work, a reliability event, or a value several times its floor or a comparable sibling's value. State the rule.
4. Use siblings that share a client, model family, or hardware as controls for expected values (cache-hit rate, ITL, clocks).
5. Diagnose the top problems with sections 4–7, and give every other workload one status line. Mark any screen that could not run as "not screened"; never call a workload healthy without naming the checks that cover it.

## 4. Reason from the request path and resource envelope

### Load and scheduling

- Apply Little's law to each target, using counters for the completion rate X and same-window means: in-flight ≈ X × end-to-end latency, waiting ≈ X × queue time. A match shows coherent telemetry; it does not identify a cause. A mismatch points to a queue outside the engine, hidden re-waits, or bad telemetry.
- In a closed loop, end-to-end latency = N ÷ X, so only a higher X or a lower N reduces it. Moving work between waiting and running trades TTFT against ITL and leaves end-to-end latency unchanged. When N exceeds the batch that fits, a long queue is the expected result: report it as load shape (by design when the test intent says so), then judge the engine on X, tokens/s, ITL against its floor, and wasted work.
- In an open loop, compare arrival rate with X over time. A growing queue means arrivals exceed capacity; a stable queue with arrivals ≈ X means the system runs at its limit. When arrivals exceed capacity, no tuning lever alone stops the queue growing: the plan must add capacity (replicas) alongside any lever that raises X.
- Compare offered, admitted, rejected, and completed traffic. An empty engine queue rules against sustained queuing at that engine only; it does not rule out slow service time, upstream rejection, routing bottlenecks, or queues in another stage.
- Call a scheduler cap binding only when work is waiting or being rejected because of that cap. `running == configured_limit` without this evidence is insufficient.
- Compare waiting reasons, running counts, token budgets, KV pressure, and preemptions against config. Distinguish slot limits, memory limits, policy deferral, and upstream admission limits.
- Treat low utilization under low offered load as potentially expected. Before calling capacity wasted, check burst requirements, redundancy, warm capacity, rollouts, and operator intent.
- Judge client impact from the client side: its own success and error counts, its timeout against the measured end-to-end distribution, and whether it cancels the upstream request on timeout. An engine abort count of zero does not show that clients succeeded.
- Compare the share of requests finished by length with the client's output limit and observed output lengths before calling truncation an engine or model fault.

### Throughput ceiling and lever classes

Before recommending a KV, concurrency, or batching lever, test whether throughput rises with batch size.

- Derive steps/s and tokens per step from engine iteration counters, or from generation tokens/s ÷ decoding sequences; mean step time ≈ 1 ÷ steps/s, checked against mean ITL. Fit step_time ≈ a + b × tokens_per_step across time intervals or histogram ranges.
  - **Fixed cost dominates** (a ≫ b × tokens): weight reads, launch, or synchronization set the step. More tokens per step raise X, so concurrency, KV capacity, graph capture, and batching levers can help.
  - **Per-token cost dominates** (a ≈ 0): the engine is at its token-throughput ceiling, X_max ≈ 1 ÷ (b × computed tokens per request). More running sequences lengthen each step and move time from the queue into ITL.
- Classify each lever by the term it changes, and predict its effect on X, TTFT, ITL, and end-to-end latency before ranking it:
  1. **Population (N):** client concurrency, router in-flight caps. Changes queue time in a closed loop; X does not change.
  2. **Computed tokens per request:** prefix-cache reuse, shorter prompts, lower output limits, less recompute. Raises X at a token ceiling.
  3. **Cost per token:** smaller or more quantized model, faster kernels, less communication, faster hardware.
  4. **Replicas:** raises X roughly in proportion when load spreads and GPUs are free.
  5. **Concurrency or KV capacity:** KV memory or dtype, sequence caps. Raises X only when fixed cost dominates or recompute is the waste; otherwise it trades TTFT for ITL.
- A full KV pool caps concurrency; it limits throughput only when this test says so. Name the limiter of the user's objective, not the resource that looks full.

### Latency attribution

- Follow the path to the first token: routing/admission, queueing, preprocessing, prefill, applicable KV handoff, initial token generation, and delivery. Report the measured components that explain the symptom; name unmeasured ones.
- Use ITL and decode timing for subsequent token generation. Do not attribute TTFT to steady-state decode inefficiency alone. In colocated serving, however, decode load can contend with prefill; in disaggregated serving, decode admission or KV readiness can delay the first token.
- Evaluate batching and chunked prefill against both TTFT and ITL. The direction of the trade-off depends on scheduling, load, and topology; do not assert that increasing a token budget or concurrency always worsens TTFT.
- Separate prompt length, output length, context length, model mix, and cache-hit cohorts where they explain tail behavior. A slow subset can disappear in fleet averages.

### Host / GPU efficiency

- Compute physical floors for each target and report measured values as a multiple of them. Use the deployed GPU's peak memory bandwidth (the actual memory type; many inference GPUs use GDDR, not HBM) and compute, and the model's architecture:
  - **Decode step floor** ≈ (weight bytes per GPU + KV bytes read per step) ÷ peak memory bandwidth. ITL near the floor means bandwidth-bound; several times the floor means overhead, synchronization, or compute dominates.
  - **KV bytes per token per GPU** = 2 × layers × (KV heads ÷ TP) × head_dim × KV dtype bytes; check it against the engine's KV size. Size usage with time-averaged resident tokens per sequence (prompt plus about half the output).
  - **Compute per token** ≈ 2 × active parameters FLOPs; compare a step's arithmetic intensity with the GPU's ridge point.
  - **TP collective payload per step** ≈ 2 all-reduces × layers × tokens per step × hidden size × activation bytes; compare with link bytes/s before calling a link saturated.
- An engine with no queue but ITL several times its floor has an efficiency finding; report it.
- Never infer compute saturation from GPU utilization alone. Correlate tensor activity, DRAM activity, occupancy, communication, achieved throughput, and the active phase.
- Use roofline reasoning as orientation: prefill is often compute intensive; small-batch decode is often memory-bandwidth intensive. The crossover depends on model, precision, context, batch, kernels, and hardware. Do not use universal critical-batch or activity thresholds.
- Distinguish VRAM capacity from device memory bandwidth. High allocation does not establish bandwidth saturation; high DRAM activity does not establish KV-capacity pressure.
- Investigate CPU tokenization/preprocessing, scheduler or kernel-launch overhead, CPU limits/throttling, host memory pressure, storage/model loading, and host-to-device copies when GPU activity is low or gappy under demand. Compare the serving containers' CPU usage with their CPU limits, and check throttling, before attributing an underfed GPU to engine configuration.
- Compare thermal, power, clock, ECC/XID, and link-error signals with latency and rank imbalance. When one replica, GPU, or rank is slower than comparable ones, check its clock-throttle reasons and its power limit against the default before attributing the gap to load, routing, or configuration. Activity counters alone do not establish healthy or efficient operation.

### Network / interconnect

- Distinguish intra-node PCIe/NVLink, inter-node fabric, request transport, collectives, and KV transfer. Read topology and parallelism before interpreting traffic.
- High link traffic alone does not prove a bottleneck. Corroborate with transfer/collective duration, achieved bandwidth relative to the relevant path, errors, retries, rank divergence, or compute waiting for communication.
- Consider tensor-, pipeline-, and expert-parallel communication when configured. Collective delays may reflect a slow rank or host rather than a saturated link.

## 5. Adapt to disaggregated prefill/decode serving

Apply this section only when topology supports separate prefill and decode stages. Separation can reduce interference and allow stage-specific tuning, but introduces a KV handoff and separate capacity pools. Do not assume that it improves throughput or eliminates contention.

1. **Map the handoff.** Identify where requests enter, how a decode destination is selected, which pool produces KV, which consumes it, and how transfer completion is signaled. Preserve stage identity in queries.
2. **Check pool balance.** Compare each pool's arrival/completion rates, queues, healthy replicas, batch/token load, GPU resources, and autoscaling decisions. A healthy fleet average can hide a saturated prefill pool or an underfed decode pool.
3. **Inspect KV transfer.** When available, read transfer duration, bytes/rate, buffer usage, pending transfers, retries, timeouts, load failures, and compatibility errors. Correlate with request traces, prompt lengths, placement, and fabric health.
4. **Locate the delay.** Distinguish prefill backlog, transfer/backpressure, decode admission/KV readiness, and steady-state decode latency. Name the missing phase measurement if end-to-end data cannot separate them.
5. **Tune the limiting stage.** Recommend prefill capacity/batching for prefill pressure, decode capacity/KV/batching for decode pressure, or placement/transport/buffer changes for a measured handoff bottleneck. Rebalance pools only after identifying which one constrains the objective.

Do not recommend chunked prefill as a universal fix for interference between already separated pools. Do not treat idle decode GPUs as proof of insufficient client load when prefill or transfer is restricting arrivals. Explain when the available configuration reveals the setup but telemetry is insufficient to identify its failure mode.

## 6. Use diagnostic patterns as evidence-based hypotheses

### Orchestration

- **Routing or replica imbalance:** Uneven queues/load across comparable healthy replicas. Check affinity, prefix-aware routing, stage pairing, and uneven request sizes before recommending redistribution.
- **Autoscaling/placement limits:** Desired capacity exceeds healthy ready capacity with queues or rejections. Inspect pending resources, quotas, GPU placement, fragmentation, startup times, and scaling policy.
- **Cold starts or scaling oscillation:** Latency/errors correlate with model loading, replica churn, or repeated scale transitions. Consider warm capacity, loading improvements, and policy stabilization.
- **Unhealthy replica serving traffic:** Correlate health failures with actual routing and request errors. Recommend correcting eviction/readiness or repairing the replica according to the platform.
- **Platform not ready or failing to start:** The service or a replica reports not-ready, or fails to start or restart. Read the platform's condition and error messages first; the cause can be configuration or an external dependency, such as an ingress class or a model artifact that can no longer be downloaded, rather than capacity.
- **Unallocated or underused GPUs:** Check allocation and placement per node, sustained utilization, pending work, and intentional headroom. Missing pod labels are not proof of unclaimed GPUs unless exporter mapping is verified.

### Inference engine

- **Scheduler limit:** Waiting/rejected work coincides with a configured sequence or token cap while other resources have headroom. Test a supported limit adjustment against latency and memory pressure.
- **KV-capacity pressure:** KV occupancy, preemptions/retractions, and workload lengths align with latency or throughput loss. Consider allocation headroom, concurrency/token budgets, supported KV precision, or capacity changes. Size it: sequences that fit ≈ KV pool tokens ÷ time-averaged resident tokens per sequence; compare with running and with N. A sequence or admission cap above the worst-case fit does not stop preemption, and a smaller batch also lowers tokens per step, so compare useful tokens/s before and after.
- **Preemption churn:** Preemptions per completed request are well above zero. In recompute mode each preemption repeats the prefill and the wait, which queue-time and prompt-token metrics may not count. Quantify it: recompute tokens/s ≈ an independent work meter (FLOPs counters, engine log throughput) − modeled useful work; re-wait per request ≈ (prefill + decode time) − running ÷ X. Report it as a share of GPU time.
- **Prefix-cache inefficiency:** Reusable prefixes are present but reuse remains low. Check enabled state, cache eligibility, eviction, and routing before recommending a configuration change. When caching is off, estimate the reuse it would get from the client's prompt structure (shared system prompts, templates, repeated prompts) and from siblings that receive the same traffic with caching on. Use token counts and shared-prefix length; do not quote prompt or completion text. Hits count only in full KV blocks: cached tokens per request ≈ floor(shared prefix tokens ÷ block size) × block size. Predict the gain as the drop in computed tokens per request; at a token-throughput ceiling, X rises by about the same ratio.
- **Prefill pressure:** Prompt processing or its queue explains slow first-token delivery. Consider supported batching/chunking, cache reuse, traffic separation, or prefill capacity.
- **Long-context or long-generation pressure:** Latency/cache pressure tracks actual context/output lengths. Consider workload limits or isolation with product trade-offs stated.
- **Launch/scheduler overhead:** Eager execution or CPU overhead coincides with gappy GPU work and slow token delivery. Check backend support and the reason graph execution was disabled before suggesting a change.
- **Other configured features:** Inspect speculative acceptance, adapter-pool pressure, model multiplexing, or expert imbalance only when enabled and relevant to the symptom.

### Host / GPU and network

- **Memory-bandwidth pressure:** Phase-specific throughput and device memory activity support a bandwidth ceiling. Consider batch efficiency, supported precision changes, or hardware bandwidth, while checking latency and accuracy requirements.
- **Compute pressure:** Tensor/compute activity and workload throughput support the hardware limit. Consider prefill reuse, scheduling, supported precision, or capacity; do not declare efficiency from an activity threshold.
- **Host bottleneck or hardware degradation:** CPU/throttling/I/O or hardware errors correlate with underfed GPUs or a slow replica/rank. Address the evidenced host or device issue.
- **Communication pressure or straggler:** Collective/KV-transfer timing and topology explain compute stalls. Distinguish excessive parallelism, poor placement, fabric problems, and rank imbalance before choosing a lever.
- **Mixed or transitional:** Several causes coexist, or load/scaling/rollout is changing. Report separate findings or uncertainty rather than forcing a single bottleneck label.

## 7. Validate recommendations and try to refute the diagnosis

Before presenting a recommendation:

- Check a plausible alternative and report the evidence that supports or weakens it. If the evidence cannot distinguish causes, label the conclusion as a hypothesis and name the next discriminating check.
- Verify knob names, supported values, and behavior against the deployed engine/version/backend. Examples such as vLLM `max_num_seqs`, `max_num_batched_tokens`, `gpu_memory_utilization`, `kv_cache_dtype`, or SGLang memory/scheduler settings are not interchangeable.
- For parallelism changes, check model/backend constraints, topology, placement, and GPU allocation. Recalculate weight, KV, activation, and runtime memory needs; fitting weights alone is insufficient. State whether freed GPUs can be reused or intentionally remain spare.
- Do not call a non-default KV block size misconfigured without backend constraints and measured overhead/fragmentation. Do not prescribe a universal block size.
- Distinguish limiting actual context/concurrency from changing a configured maximum. In engines with on-demand paged KV allocation, reducing `max_model_len` alone need not enlarge the KV pool or reduce present usage.
- Include memory/accuracy consequences of quantization, TTFT/ITL consequences of batching, and availability/startup consequences of scaling or restarting.
- Prefer a small supported change, one variable at a time, with before/after comparison at comparable load. Recommend actions; never apply them. Diagnosis runs read-only queries and commands only. Present every configuration, scaling, or restart change for the user to apply.
- Check that the change can land: the rollout strategy against free GPUs and nodes, the restart and availability cost, and any pending rollout. A reliability event (restart cycle, OOM kills, blocked rollout) outranks a latency finding on the same workload.

Order the tuning path by the predicted change in the user's objective, then by risk and cost. Give the prediction as a number with its basis, for example "computed tokens per request 78 → 30 at a fixed ~510 tok/s, so X 6.6 → ~17 req/s". List levers that do not move the objective in one line, with the reason. Name the validation signal for each step and the possible next limiter. Do not invent a tuning action when the evidence only justifies collecting missing data.

## Output format

Commit to a verdict for each target, and label each finding:

- **Confirmed:** two independent measurements agree (for example Little's law and counters, or the step-time fit and DCGM), and data refutes the main alternative.
- **Likely:** one measurement plus consistent configuration; the alternative is not refuted.
- **Hypothesis:** configuration or a model only. Name the check that settles it.

Missing telemetry in an unrelated layer does not lower a Confirmed finding; list the gap in Watch next.

Use these four Markdown headings in order. Aim for roughly 250–400 words for one target. For a fleet question, start with a triage table and stay under about 600 words:

| Workload | Status | Limiter (confidence) | First change |
| --- | --- | --- | --- |

Add the queries you used after Watch next only when the user asks for them.

### Verdict

State the dominant limiter of the objective, affected layer/stage, target, load model (open or closed loop, N, intended or not), confidence label, and time window. Use “most likely” or “insufficient evidence” when appropriate; name independent secondary findings separately.

### Why

Cite specific values and configuration, relevant phase/replica comparisons, and the alternative checked. State freshness, resolution, or missing-signal limitations that materially affect confidence. Avoid implying causation from correlation alone.

### Tuning path

Give an ordered list, at most four, by predicted gain on the objective: **lever or next diagnostic check** (lever class) — predicted change in X and in the objective, with numbers and basis; trade-off; restart or availability cost. *Re-check:* signal and success criterion. Then one line: `Not recommended: <lever> — <reason>.` State the likely next limiter only when supported.

### Watch next

Name the key regression/validation signal or the evidence needed to settle the diagnosis. Do not claim “nothing else of concern” when coverage is incomplete.

## Implementation references

Use the deployed version's documentation when translating this framework into exact metrics or settings. These references are examples, not runtime assumptions:

- [vLLM optimization and tuning](https://docs.vllm.ai/en/latest/configuration/optimization/)
- [vLLM disaggregated prefilling](https://docs.vllm.ai/en/latest/features/disagg_prefill/)
- [NVIDIA DCGM profiling metrics](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/feature-overview.html)
