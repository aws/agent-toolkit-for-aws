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

## Lazy-Load Container Images with SOCI

For container image functions, Lambda downloads and unpacks the image on each instance before it starts an execution environment. For large images this pull dominates the time from publishing a version or scaling out to the first invocation. With Seekable OCI (SOCI), Lambda uses an index that maps each file to its location in the image layers, starts the execution environment early, and fetches only the files the function reads. Startup becomes much less sensitive to total image size; the benefit is largest for images of several GB or more (for example, ML frameworks).

How it works:

1. Create a SOCI index for the image and push it to Amazon ECR. The result is an OCI image index that references the original image manifest and the SOCI index.
2. Create or update the function with an image URI pointing at that image index, then publish a version. Lambda detects the SOCI index and enables lazy loading. No other configuration change.
3. Files read by init code are fetched during initialization; files the handler reads for the first time are fetched during that invocation. Lambda does not download the rest of the image in the background.

Create and push the index (Amazon Linux 2023; replace the placeholder values):

```bash
sudo yum install -y soci-snapshotter containerd nerdctl
sudo systemctl start soci-snapshotter
sudo systemctl restart containerd

ACCOUNT_ID="111122223333"
REGION="us-east-2"
REPOSITORY_NAME="my-function"
ORIGINAL_IMAGE_TAG="v1"
SOCI_IMAGE_TAG="v1-soci"
REGISTRY="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
# Must match the function's architecture: linux/arm64 (Graviton) or linux/amd64 (x86_64)
PLATFORM="linux/arm64"

aws ecr get-login-password --region "$REGION" | sudo nerdctl login -u AWS --password-stdin "$REGISTRY"

sudo nerdctl pull --platform "$PLATFORM" "$REGISTRY/$REPOSITORY_NAME:$ORIGINAL_IMAGE_TAG"
sudo nerdctl image convert --soci --platform "$PLATFORM" "$REGISTRY/$REPOSITORY_NAME:$ORIGINAL_IMAGE_TAG" "$REGISTRY/$REPOSITORY_NAME:$SOCI_IMAGE_TAG"
sudo nerdctl push --platform "$PLATFORM" "$REGISTRY/$REPOSITORY_NAME:$SOCI_IMAGE_TAG"
```

Then use `$REGISTRY/$REPOSITORY_NAME:$SOCI_IMAGE_TAG` as the function's image URI and publish a version. For other ways to build and push an index, see [Getting started with the SOCI snapshotter](https://github.com/awslabs/soci-snapshotter/blob/main/docs/getting-started.md).

Requirements and limitations:

| Requirement | Detail |
|-------------|--------|
| Index version | SOCI Index Manifest v2 only (`application/vnd.amazon.soci.index.v2+json`); v1 indexes are not supported. `nerdctl image convert --soci` produces v2. |
| Image index format | Exactly two entries: the SOCI index and one OCI image manifest. Multi-architecture image indexes are not supported. |
| Image URI | Point at the SOCI-indexed tag (e.g. `my-function:v1-soci`), not the original tag. To change the image or index, push a new SOCI-indexed tag and update the image URI. |
| Availability | All container image functions on LMI. Not available for Lambda Event Functions on-demand. |

Best practices:

- Import all libraries and read all files the function needs in init code, not the handler, so first invocations do not pay for on-demand fetches.
- Test with and without SOCI and compare startup time and invocation duration for the workload.

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
