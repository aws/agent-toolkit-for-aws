# Aurora I/O-Optimized — Worked Examples

Companion to [instructions.md](io-optimized-instructions.md). Pricing constants, cost formulas, the data-quality table, and `skipped: true` handling are in [pricing-tables.md](io-optimized-pricing-tables.md).

## Worked example — offline assessment

User: 2× db.r6g.2xlarge, 800 GiB storage, 1.2 billion I/O requests per month, region us-east-1 (assumed), no AWS credentials.

Agent response pattern:

1. Announce reference: "Loading `references/io-optimized-instructions.md`."
2. Print the script command as text:

    ```bash
    python3 scripts/io_optimized_analyzer.py offline \
      --instance db.r6g.2xlarge --num-instances 2 \
      --storage-gib 800 --monthly-io-millions 1200
    ```

3. Compute inline (db.r6g.2xlarge Standard rate $1.038/hr):
    - **Standard compute**: $1.038/hr × 730 × 2 = **$1,515/mo**.
    - **Standard storage**: 800 × $0.10 = **$80/mo**.
    - **Standard I/O**: 1,200 × $0.20 = **$240/mo**.
    - **Standard total**: $1,515 + $80 + $240 = **$1,835/mo**.
    - **I/O-Optimized compute**: $1.038 × 1.30 × 730 × 2 = **$1,970/mo**.
    - **I/O-Optimized storage**: 800 × $0.225 = **$180/mo**.
    - **I/O-Optimized total**: $1,970 + $180 + $0 = **$2,150/mo**.
    - **I/O as % of Standard**: $240 / $1,835 = **13.1%**. Below 25% threshold.
    - **Switch cost**: +$315/mo ($2,150 − $1,835).
4. Recommendation: **Standard** (stay). I/O is ~13% of total, below the 25% breakeven. Switching would cost ~$315/mo more (+17%). Revisit only if monthly I/O exceeds ~2.5 billion requests at this storage size.

## Worked example — insufficient data

User: cluster `new-cluster-2026` only 4 days old. Should I use I/O-Optimized?

Agent response pattern:

1. Announce reference: "Loading `references/io-optimized-instructions.md`."
2. State the data-quality finding: **4 days of data is `insufficient` for a decision.** The 25% breakeven rule depends on a representative sample of monthly I/O, and 4 days does NOT capture:
   - **Weekday vs weekend variance** — weekend I/O is commonly 40–60% lower than weekday; a 4-day window starting Tuesday would over-estimate monthly I/O by ~20%.
   - **End-of-month / end-of-period spikes** — reporting loads, batch windows, month-close jobs.
3. Surface the **30-day storage-type switch cooldown** (Standard → I/O-Optimized direction only): switching to I/O-Optimized is limited to once every 30 days, while reverting to Standard is allowed at any time — so a decision to move to I/O-Optimized on thin data is a month-long commitment.
4. Recommend the user **wait at least 14 days** (minimum) before re-evaluating; **ideally 30 days** to capture at least one full monthly cycle.
5. Print the re-evaluation command for when they're ready:

    ```bash
    python3 scripts/io_optimized_analyzer.py \
      --cluster new-cluster-2026 --region <their-region> --days 30
    ```

6. Mention the specific CloudWatch metrics to watch in the meantime: `VolumeReadIOPs` and `VolumeWriteIOPs` under `AWS/RDS` with dimension `DBClusterIdentifier=new-cluster-2026`. Also monitor `VolumeBytesUsed` for storage-growth trends.

## Worked example — `skipped: true` for an empty cluster

User: "Run the commitment pricing analyzer on my Aurora cluster `paused-cluster-1` in us-east-1."

Though this is a commitment-pricing prompt, the same `skipped: true` semantics apply — and if the cluster has no instances, **both** commitment-pricing AND I/O-Optimized analyzers skip it.

Agent response pattern:

1. Announce reference: "Loading `references/commitment-pricing-instructions.md` (also relevant: `references/io-optimized-instructions.md` §`skipped: true`)."
2. After describe-db-clusters returns `DBClusterMembers: []`, surface: **`skipped: true, reason: "no DB instances — likely last writer/reader deleted, paused, or mid-migration"`**.
3. Explain common causes: last reader/writer instance deleted (no compute attached), a paused cluster, or a cluster mid-migration. Note: a Blue/Green switchover or `modify-db-instance` reboot does NOT empty `DBClusterMembers` and will not trigger this skip.
4. Next steps:
   - If **last instance deleted / paused**: resume the cluster (create a DB instance in it), let it run for 14+ days, then re-run the assessment.
5. Do NOT suggest the cluster does not exist; it exists, just without compute.
