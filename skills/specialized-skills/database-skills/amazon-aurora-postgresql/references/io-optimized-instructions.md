# Aurora I/O-Optimized Workflow

Assess whether Aurora I/O-Optimized storage is cheaper than Aurora Standard for a cluster or a region's fleet, using the AWS-documented 25% breakeven rule (I/O ≥ 25% of total cluster cost → I/O-Optimized wins). Can execute the storage switch after user confirms.

Execute commands via the AWS MCP server when connected (sandboxed, audit-logged). Fall back to the AWS CLI or shell otherwise.

## When This Applies

User mentions: I/O-Optimized, `aurora-iopt1`, "should I switch storage type", "is I/O-Optimized worth it", "how much would I/O-Optimized save", or storage-configuration cost comparison.

## Tasks

### 1. Acquire Target Parameters

Three modes: **live single-cluster** (cluster id, region, optional `--days`; default 14, min viable 7); **live fleet** (region, optional `--days`); **offline** (instance type, num instances, storage GiB, monthly I/O in millions).

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST NOT guess a cluster identifier — ask the user explicitly
- You MUST confirm the captured parameters before running the analyzer
- You SHOULD default to live mode when AWS credentials are available

### 2. Run the Analyzer

**Constraints:**

- You MUST use the script rather than hand-computing; the script fetches live CloudWatch I/O data and Pricing API rates, applies extrapolation, and handles data-quality flags
- You MUST pass `--region` matching the cluster's region
- You SHOULD prefer `--format json` when post-processing and `--format table` for direct user display

```bash
python scripts/io_optimized_analyzer.py --cluster my-cluster-id --region us-east-1   # single cluster
python scripts/io_optimized_analyzer.py --all --region us-east-1                      # whole fleet
python scripts/io_optimized_analyzer.py offline \
  --instance db.r6g.2xlarge --num-instances 2 \
  --storage-gib 800 --monthly-io-millions 1200                                        # offline
```

Add `--days 30` to change the lookback window (default 14).

### 3. Handle Skipped Clusters

The analyzer returns `skipped: true` for clusters with no DB instances (Aurora Limitless, or a cluster whose last writer/reader was deleted) — no compute to price.

**Constraints:**

- You MUST surface skipped clusters to the user with the script's `reason` string
- You MUST NOT include skipped clusters in fleet dollar totals (the script already excludes them)
- You MUST NOT attempt to force a comparison on a skipped cluster

### 4. Interpret Data Quality

The script tags results by lookback-window coverage: `insufficient` (<3d, no switch), `short` (3–7d, tentative), `adequate` (7–14d, reliable), `good` (14+d, high-confidence). Full table and reasoning in [pricing-tables.md](io-optimized-pricing-tables.md).

**Constraints:**

- You MUST surface the `data_quality` tag when presenting a recommendation
- You MUST NOT give a confident switch recommendation when the tag is `short` or `insufficient` because weekly patterns (weekday vs weekend) can shift the result
- When the tag is `short` or `insufficient`, You MUST explicitly mention the 30-day switch cooldown as an additional reason to wait — switching Standard → I/O-Optimized is limited to once every 30 days, so acting on thin data is a 30-day commitment in that direction (reverting to Standard is allowed at any time)
- You MUST NOT describe a Standard → I/O-Optimized switch as freely reversible when the data_quality is short — that direction carries a 30-day commitment, making it a meaningful one-way door on thin data (the reverse, I/O-Optimized → Standard, can be done at any time)
- You SHOULD offer to rerun with a longer window once more data is available

### 5. Present Results

Every assessment MUST include: (1) side-by-side monthly cost table (Standard vs I/O-Optimized) with compute, storage, I/O line items; (2) I/O cost as a percentage of Standard total — the deciding factor; (3) recommendation: `standard` or `io_optimized`; (4) one-sentence reason tied to the 25% threshold and the dollar delta; (5) fleet runs: per-cluster table plus total "optimal mix" savings; (6) skipped clusters: explanation.

**Constraints:**

- You MUST cite the 25% breakeven rule in your reasoning so the user understands it
- You MUST show the dollar delta, not just the percentage
- Storage-type switch is online (no downtime) for most instance classes; clusters using NVMe/Optimized Reads instances (r6gd, r6id, r8gd) require a restart with brief unavailability — check instance classes before advising on impact. Switching Standard → I/O-Optimized is limited to once every 30 days; switching back to Standard can be done at any time.
- You MUST warn the user about the 30-day cooldown on the Standard → I/O-Optimized direction and confirm instance class before executing. If NVMe instances are present, warn about restart.
- After user confirms, execute `aws rds modify-db-cluster --storage-type aurora-iopt1` via MCP tools. Alternatively, provide the full CLI command for the user to run.

## Troubleshooting

See [pricing-tables.md §Troubleshooting](io-optimized-pricing-tables.md#troubleshooting) for the full list (cluster-not-found, zero I/O data, pricing-fetch failures, skipped/Limitless, near-25%-threshold cases).

## Deep-Dive References

- [pricing-tables.md](io-optimized-pricing-tables.md) — pricing-constant & data-quality detail tables, monthly cost formulas, `skipped: true` handling. Use for inline computation when you can't run the script.
- [worked-examples.md](io-optimized-worked-examples.md) — three worked examples (offline with the $1.038/hr db.r6g.2xlarge math, insufficient-data, empty-cluster).
- [pricing.md](io-optimized-pricing.md) — breakeven math derivation, switch mechanics, commitment-pricing interaction
- [data-collection.md](io-optimized-data-collection.md) — CloudWatch metrics, extrapolation methodology, short-window handling

## 25% breakeven rule (the single most important fact)

**Aurora I/O-Optimized** trades a 30% compute premium for **zero I/O charges** and a ~125% higher storage rate ($0.225 vs $0.10 per GiB-month). It wins when **I/O cost ≥ 25% of the Standard total** (compute + Standard storage + Standard I/O). Tiers: **< 20%** → stay Standard (confident); **20–25%** → stay Standard (marginal, monitor); **25–30%** → borderline, re-check monthly (could flip with growth); **> 30%** → switch to I/O-Optimized (confident).

Run `python3 scripts/io_optimized_analyzer.py ...` if shell is available; otherwise compute inline using [pricing-tables.md](io-optimized-pricing-tables.md) (constants + formulas) and [worked-examples.md](io-optimized-worked-examples.md).

**One-directional cooldown** (canonical guidance is in the verbatim Task 4 and Task 5 MUST/MUST-NOT constraints above): the 30-day cooldown applies to the **Standard → I/O-Optimized direction only**; reverting to Standard is allowed at any time. Lookback-window detail is in [pricing-tables.md](io-optimized-pricing-tables.md).
