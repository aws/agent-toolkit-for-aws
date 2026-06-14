# Aurora serverless Workflow

Size Aurora Capacity Units (ACU), estimate monthly cost, and plan provisioned-to-serverless migrations for Aurora MySQL serverless. Can modify ACU scaling configuration when the user confirms.

Execute commands via AWS MCP server tools when connected (sandboxed, audited, observable); fall back to the AWS CLI or shell otherwise.

## When This Applies

User mentions: Aurora serverless, ACU sizing, min/max ACU, scale-to-zero, auto-pause, `provisioned to serverless`, serverless cost comparison, or "how many ACUs do I need".

## Tasks

### 0. Vague-Workload Guard (FIRST CHECK — BEFORE ANYTHING ELSE)

**Before producing any ACU number, dollar figure, or specific recommendation, check whether the user supplied real metrics.**

A vague-workload prompt describes the workload qualitatively without the inputs the calculator needs. Examples:

- "small app", "light/low traffic", "a few connections", "medium-sized workload", "low usage", "occasional spikes"
- "new project", "side project", "internal tool"
- Any "how many ACUs do I need" / "what ACU settings should I use" prompt that names no instance type, P95 CPU, max CPU, or storage size

**If the prompt is vague, you MUST do all of the following — and ONLY these — in your reply:**

1. State explicitly that you cannot recommend specific ACU numbers without real metrics. Name the missing inputs (instance type, CPU P95, CPU max, storage GiB).
2. Point the user to CloudWatch (`CPUUtilization`, `DatabaseConnections` under the `AWS/RDS` namespace) and Performance Insights as the CPU-metric sources.
3. Offer the simplest path: ask for metrics, or — if this is a brand-new cluster with no production traffic yet — tell the user to start with the AWS-default Aurora serverless ACU range and tune after observing CloudWatch for a few days.
4. **Do NOT provide specific ACU numbers in this reply, even as a "safe starting point" or "typical range".** Do NOT cite specific dollar figures. Do NOT include a "however, here's a default..." paragraph. Do NOT state numbers like "Min 0.5, Max 2-4" even with caveats.

The "no specific numbers" rule is absolute. Hedged numbers ("a safe default would be 0.5–2 ACU") are still numbers and count as a violation. Customers act on confident-sounding numbers even when framed as defaults, and ACU numbers fabricated from vague input are the #1 source of field misconfiguration.

Only if the user returns with real metrics, proceed to Task 1.

### 1. Acquire Workload Parameters

Required (acquire only AFTER passing Task 0):

- **instance type** (string, `db.<family>.<size>`, e.g. `db.r6g.xlarge`)
- **CPU P95** (float, 0–100)
- **CPU max** (float, 0–100)
- **storage GiB** (number)

Optional:

- **region** (string, default `us-east-1`)
- **CPU average** (float, 0–100; estimated as 60% of P95 if omitted)
- **peak connections** (integer, default 0)
- **working set GiB** (float; improves min-ACU accuracy)
- **number of instances** (integer, default 1; for HA comparisons)

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST support parameters as plain text, JSON, or values from a CloudWatch screenshot
- You MUST confirm the captured values back to the user before running the calculator
- You SHOULD guide the user to CloudWatch or Performance Insights for CPU metrics they lack

### 2. Run the Calculator

Invoke `scripts/acu_calculator.py` with the step-1 parameters.

**Constraints:**

- You MUST use the calculator rather than hand-estimating; it handles family ratios, memory floors, and min/max rounding consistently
- You MUST pass `--region` when the user's region is not `us-east-1`
- You SHOULD prefer `--format json` for post-processing, `--format table` when presenting
- You MAY add `--offline` only when AWS credentials are unavailable

```bash
# Basic run
python scripts/acu_calculator.py estimate \
  --instance db.r6g.xlarge --cpu-p95 35 --cpu-max 72 --storage 500

# List supported instances
python scripts/acu_calculator.py list-instances
```

A full invocation using every optional flag is in [worked-examples.md](serverless-advisory-worked-examples.md).

### 3. Present Results

Every recommendation MUST include:

1. Recommended **min / max / typical / peak ACU** values
2. Side-by-side monthly cost table: provisioned vs serverless (compute, storage, total)
3. A clear label: `recommended`, `consider`, `more_expensive`, or `not_recommended`
4. A one-sentence reason tied to the numbers (savings %, peak vs 256 ACU ceiling, utilization pattern)
5. If the working set needs more memory than min ACU provides, the memory advisory verbatim

**Constraints:**

- You MUST state the label plainly; do not soften it to "maybe"
- You MUST cite a concrete dollar figure and percentage when comparing costs
- You SHOULD offer a migration path when the label is `recommended` — see [migration.md](serverless-advisory-migration.md)

### 4. Migration Planning (when applicable)

See [migration.md](serverless-advisory-migration.md) — in-place with a serverless reader, Blue/Green, or snapshot restore.

**Constraints:**

- You MUST recommend testing on a snapshot-restored cluster before production
- You MUST mention that `innodb_buffer_pool_size` is auto-managed (resized with ACU) so don't hard-code it, and that `max_connections` is derived from the cluster's **maximum** ACU (static; reboot to change), not current capacity
- ACU scaling (min/max changes) is non-disruptive and allowed after user confirmation. Deletion is blocked — see SKILL.md Safety guidance.
- You SHOULD offer a CloudFormation or CDK snippet when the user's stack is IaC-managed

## Troubleshooting

**Calculator reports "exceeds capacity".** Projected peak ACU > 256; Aurora serverless cannot service this cluster. Recommend staying on provisioned or splitting across multiple serverless clusters.

**Live pricing fetch fails with ExpiredToken.** Refresh credentials (`aws sts get-caller-identity`) or rerun with `--offline` for static us-east-1 pricing.

**Calculator returns $0 compute for the provisioned comparison.** Instance type missing from the static catalog. Run `list-instances`.

**Scale-to-zero questions.** Incompatible with RDS Proxy, binary logging (binlog) enabled, Global Database primary, Zero-ETL. See [concepts.md](serverless-advisory-concepts.md) for the full list and supported versions.

**256 ACU + HA failover.** Aurora has exactly one writer per cluster; readers can be serverless or provisioned. Two writers is not valid.

## Deep-Dive References

- [formulas-and-examples.md](serverless-advisory-formulas-and-examples.md) — Inline ACU sizing/pricing formulas and pricing tables. Use when you can't run `scripts/acu_calculator.py`.
- [worked-examples.md](serverless-advisory-worked-examples.md) — Worked examples (basic sizing; migration with CFN/CDK snippets) and scale-to-zero/auto-pause rules.
- [concepts.md](serverless-advisory-concepts.md) — ACU fundamentals, scaling, scale-to-zero requirements, pricing
- [migration.md](serverless-advisory-migration.md) — Migration approaches, parameter group rules, CFN/CDK examples
