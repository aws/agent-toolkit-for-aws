# EC2 Instance Selection

## Overview
Choosing the right instance type, CPU architecture, burstable mode, and storage.

## Pick a family by workload

| Workload | Family | Notes |
|----------|--------|-------|
| Balanced web/app servers, dev | General purpose: M (steady), T (bursty) | T is cheapest for spiky/idle workloads |
| CPU-bound: batch, transcoding, HPC, game servers, ML inference | Compute optimized: C | Highest vCPU:memory ratio among the general/compute/memory (M/C/R) families |
| In-memory DBs, caches, big-data analytics | Memory optimized: R (X = extreme) | High memory:vCPU |
| High random IOPS: NoSQL, OLTP, disk-based caches | Storage optimized: I | Local NVMe SSD; see instance-store caveat below |
| Dense sequential throughput: data warehouses, HDFS, log processing | Storage optimized: D | Local HDD; see instance-store caveat below |
| Training / graphics | Accelerated: P, G (GPU) | P for training, G for graphics/inference |
| ML inference / training on AWS silicon | Inf (Inferentia), Trn (Trainium) | Lower cost per inference/training |
| Tightly coupled HPC | Hpc | Best price-performance at scale |

Within a family, size (`.large`, `.xlarge`, …) scales vCPU and memory together. Prefer current generation over previous. New families and generations ship regularly, so confirm the current roster with `aws ec2 describe-instance-types --filters Name=current-generation,Values=true` or the EC2 instance-types documentation rather than treating this table as exhaustive.

## Graviton (Arm64) vs x86
AWS Graviton instances — the `g` suffix denotes Graviton/Arm64 (e.g. `m7g`, `c7g`, `t4g`; additional generations ship over time, so discover current ones with `aws ec2 describe-instance-types --filters Name=processor-info.supported-architecture,Values=arm64 Name=current-generation,Values=true`) — run the Arm64 architecture and generally deliver better price-performance than comparable x86 instances, with each generation improving on the last. Check the current Graviton generation and its published price-performance figures in the AWS documentation before sizing.

**Decision:** Use Graviton when your language/runtime and all dependencies support Arm64 (Go, Java, Python, Node, .NET, most containers do). Stay on x86 (Intel/AMD) for software with x86-only binaries or drivers.

**Gotcha:** Graviton requires an **Arm64/aarch64 AMI** and Arm64-compiled binaries. An x86 AMI won't launch on a `*g` type (the type appears disabled at launch). You can't change architecture in place — rebuild.

## Burstable T instances and CPU credits
T instances provide a **baseline** CPU percentage and earn **CPU credits** while below baseline, spending them to burst above it (1 credit = 1 vCPU running at 100% for 1 minute).

| Mode | Behavior when credits run out | Default on |
|------|-------------------------------|-----------|
| `standard` | Throttled down to baseline | T2 |
| `unlimited` | Keeps bursting; bills **surplus credits** if 24h-avg CPU > baseline | **T3, T3a, T4g** (also T2 opt-in) |

Defaults can differ on newer burstable generations — confirm a given type with `aws ec2 describe-instance-types --instance-types <type>` (and the credit-specification default) rather than assuming from this table.

- **Cost trap:** T3/T3a/T4g default to unlimited, so a sustained-high-CPU workload silently accrues surplus charges (watch `CPUSurplusCreditsCharged`). For steady high CPU, move to a fixed-performance family (M/C/R) or set `standard`.
- Set mode at launch or with `aws ec2 modify-instance-credit-specification --instance-credit-specification InstanceId=<id>,CpuCredits=standard`.
- Credit persistence on stop: T2 Standard loses all accrued credits (balance reset to zero, fresh launch credits on restart); T3, T3a, and T4g keep their CPU credit balance for 7 days after stop, after which the credits are lost. Restart within 7 days and no credits are lost.
- T3 on a Dedicated Host is standard-only.

## Instance store vs EBS
Instance store = physically attached ephemeral disk (families with the `d` suffix and I/D families).

**Instance store data is lost on stop, hibernate, terminate, instance-type change, and underlying host failure; it survives only a reboot.** It's also attach-at-launch-only. Use it for scratch/cache/replicated data. For anything durable, use EBS (persists independently), EFS, or S3. Encrypt EBS volumes by default.

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Instance type disabled/greyed out at launch | AMI architecture ≠ instance architecture (x86 AMI on Graviton) | Use an Arm64 AMI for `*g` types; rebuild app for Arm64 |
| Unexpected CPU surplus charges on T3/T4g | Unlimited mode + sustained CPU above baseline | Switch to `standard`, or right-size to M/C/R |
| Scratch data gone after resize/stop | Instance store wiped on stop/type-change | Store durable data on EBS/EFS/S3 |
| Sudden throttling to baseline (standard T2) | CPU credit balance depleted | Enable unlimited (mind cost) or use fixed-performance family |

## Security Considerations

- **Graviton (Arm64) needs Arm64 builds** — before migrating, confirm all security-critical software (TLS libraries, IDS/endpoint agents, compliance tooling) ships Arm64 binaries, not just your app.
- **Instance store is ephemeral** — never place cryptographic keys, certificates, or secrets on it; they're lost on stop/terminate and can't be reliably wiped. Keep secrets in Secrets Manager / SSM Parameter Store and durable data on encrypted EBS.
- **Choose EBS-capable, encryptable types for production** — enable EBS encryption by default and detailed monitoring on the chosen family.

## Related

- [provisioning.md](provisioning.md) to bake the choice into a launch template
- [auto-scaling.md](auto-scaling.md) for mixed instance types and Spot
