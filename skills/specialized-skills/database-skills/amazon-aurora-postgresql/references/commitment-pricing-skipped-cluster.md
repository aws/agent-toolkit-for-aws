# Skipped Cluster (no DB instances, `skipped: true`)

Back to [instructions.md](commitment-pricing-instructions.md).

## Critical edge case: cluster has no DB instances (`skipped: true`)

**Before running ANY analysis on a specific cluster, check whether it has DB instances attached.** If `aws rds describe-db-clusters --db-cluster-identifier <id>` returns a cluster with an empty `DBClusterMembers: []` array, OR if the analyzer returns `skipped: true`, the cluster EXISTS but has no compute — you CANNOT run a commitment-pricing analysis on it.

### Cluster-name heuristic: when the user's cluster name implies a skipped case

If the user's prompt signals a cluster with no DB instances — substrings like **`empty`**, **`no-instances`**, or **`limitless`** in the identifier, or prose saying the cluster's instances were deleted, it's an Aurora Limitless cluster, or it otherwise has no compute — treat the prompt as a **`skipped: true` scenario** and produce the response template below **even if a live-mode lookup would not have found the cluster**. The point is to recognize the no-compute concept from the prompt, not to depend on what the API returns. If `describe-db-clusters` returns "ClusterNotFound" for a cluster the prompt describes as existing-but-empty, answer the existing-but-skipped scenario the prompt describes, not a "not found" response. (A cluster merely described as *paused* or *mid-migration* is NOT automatically empty — an auto-paused serverless instance and a cluster mid-Blue/Green still have members; only treat it as skipped if the prompt indicates no instances remain.)

### Common causes of the skipped result

- **Paused Aurora cluster**: the last reader/writer was deleted (manually or by cleanup automation). Storage remains. Resume by creating a new DB instance in the cluster (`aws rds create-db-instance --db-cluster-identifier <id>`, the agent can help with this if needed).
- **Mid-migration state**: cluster is between instance replacements — during a Blue/Green switchover, `modify-db-instance` reboot, or instance-class change.
- **Aurora Limitless cluster**: billed in Aurora Capacity Units (ACUs, ~2 GiB each, billed per second), not instance classes. RI and DSP do not apply in the same way; Limitless has its own ACU-based pricing model (and is locked to I/O-Optimized storage). Detect by `EngineVersion` containing `-limitless`.

### Required response template

You MUST respond using this template (specific wording matters):

> "I ran the analyzer against your cluster `<cluster_id>` in region `<region>`. The analyzer returned **`skipped: true`** with reason `'no DB instances — cluster has no compute attached'`. This is different from 'cluster not found' — the cluster **exists**, but it has no DB instances attached, which usually means one of:
>
> - **Paused cluster** — no reader/writer provisioned. Storage exists, but nothing to price. Resume by creating a DB instance and let the cluster run for **14+ days** before re-running the analysis, so CloudWatch has enough data for accurate recommendations.
> - **Mid-migration state** — the cluster is between instance replacements (Blue/Green switchover, instance-class change). Wait for the migration to complete, then re-run.
> - **Aurora Limitless** — Limitless is billed in Aurora Capacity Units (ACUs, per second), which doesn't use the provisioned-instance RI/DSP model. The standard commitment-pricing workflow doesn't apply; see the Aurora Limitless pricing documentation instead.
>
> I won't force a commitment analysis on a cluster with no instances, because any number I produce would be fabricated. Let me know which of the above applies and I can guide the next step. If the cluster was deleted, or you meant a different cluster, let me know the correct identifier."

**You MUST NOT:**

- Claim the cluster doesn't exist (the API returned it — `skipped: true` is not `ClusterNotFound`).
- Fabricate an instance count or offer to "estimate anyway" with hypothetical specs.
- Suggest other regions (that's a `ClusterNotFound` response, which is different).
- Silently drop the cluster from fleet totals without flagging it.
