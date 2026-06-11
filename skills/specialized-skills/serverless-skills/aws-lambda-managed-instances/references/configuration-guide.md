# LMI Configuration Guide

## Instance Type Decision Tree

- **CPU-intensive** (encoding, ML, compression) → C-series, 2:1 ratio, concurrency=1/vCPU
- **Memory-intensive** (caching, large datasets) → R-series, 8:1 ratio
- **Network-intensive** (streaming, data transfer) → Use AllowedInstanceTypes for n-suffix types, 4:1 ratio
- **General/balanced** (web APIs, microservices) → M-series, 4:1 ratio, default concurrency

Architecture: ARM (Graviton, g-suffix) for price-performance. x86 (i=Intel, a=AMD) when dependencies require it.

## Memory-to-vCPU Ratios

| Ratio | Profile | When to use | Memory examples |
|-------|---------|-------------|-----------------|
| 2:1 | Compute | CPU-bound work | 2GB/1vCPU, 4GB/2vCPU |
| 4:1 | General | Most workloads (default) | 4GB/1vCPU, 8GB/2vCPU |
| 8:1 | Memory | Caching, data, Python apps | 8GB/1vCPU, 16GB/2vCPU |

Min: 2 GB / 1 vCPU. Max: 32 GB. Memory must align with ratio multiples.

## Memory Sizing from Existing Lambda

| Current Lambda | LMI memory | Ratio | Rationale |
|---------------|------------|-------|-----------|
| 128-512 MB | 2048 MB | 4:1 | LMI minimum; multi-concurrency shares memory |
| 512 MB-1 GB | 2048 MB | 4:1 | Room for concurrent requests |
| 1-2 GB | 4096 MB | 4:1 | Standard upgrade path |
| 2-4 GB | 4096-8192 MB | 4:1 or 8:1 | Depends on memory vs CPU bottleneck |
| 4-10 GB | 8192-16384 MB | 8:1 | Likely memory-heavy workload |

## Concurrency Tuning

| Runtime | Default per EE | I/O-bound | CPU-bound |
|---------|-------------|-----------|-----------|
| Node.js | 64 | Keep or increase | 1 per vCPU |
| Java | 32 | Keep | 1 per vCPU |
| .NET | 32 | Keep | 1 per vCPU |
| Python | 16 | Keep | 1 per vCPU |

Total capacity = MinExecutionEnvironments × PerExecutionEnvironmentMaxConcurrency

## Capacity Provider Scaling Controls

| Control | Default | Guidance |
|---------|---------|----------|
| MinExecutionEnvironments | 3 | Increase for baseline capacity; never below 3 |
| MaxExecutionEnvironments | — | Set based on cost budget |
| MaxVCpuCount | 400 | Optional but recommended — set explicitly to control cost ceiling |
| TargetResourceUtilization | ~50% headroom | Raise for cost savings (less burst tolerance) |
| AllowedInstanceTypes | All | Restrict only for specific hardware needs |
| ExcludedInstanceTypes | None | Exclude expensive types in dev/test |

## Monitoring Thresholds

- **CPU > 80%**: reduce concurrency or add vCPUs
- **CPU < 20%**: increase concurrency for better utilization
- **Throttle rate (429s) > 1%**: increase MinExecutionEnvironments or reduce utilization target
- **Memory > 90%**: increase memory or reduce concurrency
- **ExecutionEnvironmentConcurrency near limit**: saturation — reduce concurrency or scale out

## CloudWatch Metrics Dimensions

LMI metrics are split across two CloudWatch dimensions:

- **Alias (live)**: Invocations, Errors, Throttles, Duration
- **Version ($LATEST or numbered)**: CPUUtilization, MemoryUtilization, ExecutionEnvironmentConcurrency, ExecutionEnvironmentCount

Create a unified dashboard combining both views to monitor LMI performance effectively.
