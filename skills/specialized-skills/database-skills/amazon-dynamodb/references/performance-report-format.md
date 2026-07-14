# performance_report.md — structure

`${SKILL_DIR}/scripts/generate_perf_report.py` consumes a `perf_summary.json` (emitted by `${SKILL_DIR}/scripts/benchmark_model.py`) plus the original `dynamodb_data_model.json` and writes a Markdown report at the path passed via `--output`. It also writes `design_findings.json` — a machine-readable extraction that the agent uses to author the Design Reflection section. (`${SKILL_DIR}` is defined in SKILL.md "Resolving the skill's own paths" — substitute the absolute path of the directory containing SKILL.md.)

This document specifies the structure of `performance_report.md` so the agent can read it consistently and so alternative report generators (a dashboard, a different template) can match shape without re-deriving it from the script.

## Top-of-report matter (always present)

1. **Heading:** `# DynamoDB Live Performance Report`.
2. **Disclaimer block.** A blockquote paragraph stating: this is a scaled-down benchmark (duration, scale factor); capacity numbers come from `ReturnConsumedCapacity`; monthly costs extrapolate linearly (observed per-op capacity × declared peak RPS × on-demand public unit price; confirm against the AWS pricing page); the benchmark does **not** prove the design sustains declared peak RPS; what is **not** measured (stream consumers, TTL sweep, autoscaling, cross-region replication, long-tail bursts, non-DDB services).
3. **Headline numbers.** Four bold lines:
   - `Extrapolated Monthly Cost (measurement-based): $X` *(from steady-state measurement only)*
   - `Calculator Monthly Cost (expected):              $Y`
   - `Delta:                                           Δ%`
   - `This benchmark consumed: ~$Z in actual AWS charges` *(seed + warmup + measurement)*
4. **Source-by-source comparison table.** Columns: `Source | Measured Monthly | Calculator | Δ%`. Rows: `Storage (not measured)`, `Read/write requests`.

## `## Deployment`

One paragraph, fact-only:

```
Account: <n>   Region: <r>   Run ID: <uuid>
Resource prefix: `ddb-skill-bench-<ts>-<uuid8>-`
Window: completed <iso8601-UTC>, <N>s wall, <M> measured rows.
Resources: <n> tables, <n> GSIs. Manifest: created_resources.json.
Teardown: teardown.sh (run manually; the skill does NOT auto-delete).
```

The **`Window:`** line is sourced from the freshness markers `benchmark_model.py`
stamps into `perf_summary.json` after every invocation returns:
`benchmark_completed_at` (UTC ISO-8601), `benchmark_wall_seconds`, and
`total_rows`. They are written only on a completed run, so a killed/backgrounded
benchmark never produces them — making `benchmark_completed_at` a reliable
"this summary is from a real, completed run" marker. The agent confirms it
post-dates the time it launched the benchmark before trusting the report (the
defense against interpreting a stale prior summary). Older summaries without the
fields render `Window: completed <not recorded> UTC`.

## `## Storage (not benchmarked)`

## `## Seed verification`

Present whenever `perf_summary.json` carries `seed_verification` (every live
run). A per-table table — `Table | Expected | Seeded (observed) | Status` —
sourced from `verify_seed`'s bounded-pagination COUNT. Each table record carries
`{expected, actual, sampled, passed, seed_shortfall_ratio}`: `actual` is the
items counted (suffixed `+` and `sampled:true` when counting stopped at the
`SEED_VERIFY_CAP`), `passed` is true when `actual ≥ 50%` of the capped target.
A real shortfall (`passed:false AND sampled:false` — counted to exhaustion, not
just to the cap) emits a high-severity `seed_shortfall` correctness finding and
flips `no_significant_findings` to false: measurements on an under-seeded table
ran against the wrong data shape and must not be trusted.

Short prose paragraph plus the storage columns from `cost_report.md` reproduced verbatim. Storage is not measured in a short-window benchmark; it is reproduced here for context only so the report is self-contained.

## `## Access Pattern Measurements`

Steady-state only (warmup excluded). One paragraph intro pointing at `## Cold start` for warmup numbers, then a table:

| Column | Source |
|---|---|
| `Pattern` | `pattern_id` |
| `Operation` | `operation` |
| `Table/Index` | `table` (and `index` if set) |
| `Peak RPS` | declared `peak_rps` from design JSON |
| `Bench RPS` | post-clamp, post-scale RPS actually driven |
| `Observed RCU/WCU` | mean from `phase: "measure"` rows only |
| `Expected RCU/WCU` | from `calculate_costs.pattern_monthly_cost(...)` — matches the calculator exactly |
| `Δ` | `(observed − expected) / expected` as percent |
| `p50 ms` | from `phase: "measure"` latency samples |
| `p99 ms` | from `phase: "measure"` latency samples |
| `Throttles` | count from steady state (not warmup) |
| `Errors` | non-throttle (structural) error count and rate from steady state, rendered `count (rate%)`; suffixed `*` when the rate is at/above the structural threshold (≥50%), marking the pattern as structurally broken. Feeds the Correctness section below. |
| `Extrapolated Monthly` | observed CU × declared `peak_rps` × seconds/month × unit price |

Footnotes below the table:

- `¹ GSI write amplification observed: <r>× (expected <r>× for <projection>)` — one line per pattern with GSI writes, only if observed and expected differ by >15%.
- `² <pattern_id>: <n> throttles during ramp — see Axiom Findings.` — one line per pattern that tripped the ramp-throttle flag.

## `## Cold start`

Prose intro naming `table_settle_seconds` and `warmup_seconds` from the config, plus a table:

| Column | Source |
|---|---|
| `Pattern` | `pattern_id` |
| `Warmup p50 ms` | `phase: "warmup"` rows |
| `Warmup p99 ms` | `phase: "warmup"` rows |
| `Steady p99 ms` | `phase: "measure"` rows (same value as in the previous section) |
| `Warmup throttles` | count of `throttled: true` rows in `phase: "warmup"` |
| `Elevated?` | `cold_start_elevated` flag (true when warmup p99 > 2 × steady p99) |

One-paragraph explanation: an "Elevated" pattern means callers hitting it immediately after deploy will see materially worse latency than steady-state numbers suggest — characteristic of on-demand baseline capacity on a fresh table, not a design defect, but worth noting for deploy-time UX expectations.

## `## Supporting services (designed, not benchmarked)`

Bullet list, one per non-DDB service the design references. Each bullet says what the design called for and that it was not deployed:

- `Lambda <fn-name>: configured as stream consumer in design; not deployed.`
- `EventBridge Pipe <p>: design-only.`
- `OpenSearch zero-ETL: design-only.`

If the design references no non-DDB services, the section is a single sentence stating so.

## `## Axiom Findings`

Three subsections with headings exactly as written below.

### `**Validated by this run**`

Bulleted list. Each line cites the axiom and the observation that confirms it. Examples:

- `Mechanics #18: RCU/WCU formulas reproduced within tolerance for all patterns.`
- `Mechanics #7 (projections): GSI <name> with INCLUDE observed <r>× amp — matches projected-attribute size.`
- `Mechanics #15 (eventual vs strong 2:1): <pattern_a> vs <pattern_b> observed ratio <r> — matches 2:1 expectation.`
- `Mechanics #8 (mutable GSI key double-write): observed on <pattern>, confirms prediction.`
- `Data Modeling #14 (auth-aligned PK): cross-tenant query returned no items, as expected.`

### `**Deviations**`

Bulleted list for every pattern where `|observed − expected| / expected > 0.1` (with an absolute floor for very small expected values). Each line:

- `<pattern_id>: observed <x> vs expected <y> (Δ <%>). Likely: <RPS off | item size off | conditional fail rate | other>.`

The "Likely:" clause is authored by the script from the `large_expected_observed_delta_patterns` signal if possible, falling back to "other" when no clear cause is inferrable.

### `**Not validated by this run**`

Bulleted list of axioms the benchmark deliberately cannot exercise. Standard entries:

- `Mechanics #3 (per-partition ceilings 1000 WCU / 3000 RCU): bench did not push to ceilings by design.`
- `Mechanics #12 (TTL eventual delete): sweep cadence is hours; short window cannot observe.`
- `Data Modeling #3, #5 (Streams/PITR/recovery granularity): configuration-level, not traffic-observable.`
- `Data Modeling #13 (Global Tables LWW / MRSC): single-region deploy.`
- `Patterns #1 (idempotency middleware): application layer, not DDB alone.`
- `Integration #1 (consumer idempotency): consumers not deployed.`

## `## Cost-estimate validation`

Short paragraph. For each pattern where `|observed − expected| > 10%`: flag and explain. If all within tolerance: one line:

> Calculator unit-cost formulas reproduce live DynamoDB billing within tolerance for this design; any remaining cost risk lies in the RPS / item-size assumptions fed to the calculator.

## `## Design reflection`

Authored by the **agent** from `design_findings.json` and the axioms — not by the script. The script writes a placeholder heading and a pointer at the design findings file; the agent fills the two subsections below.

### `### Input-accuracy findings (update the inputs, not the design)`

One bullet per pattern classified `category: "input-accuracy"` in `design_findings.json`. Format:

- `<pattern_id>: observed <x>, expected <y>. Likely cause: <declared RPS / item size / consistency / conditional_fail_rate> was off. Proposed JSON diff and re-run calculator only.`

### `### Design findings (the structure itself is the source)`

One bullet per finding classified `category: "design"`. Format:

- `<signal>: <plain-language explanation>. Axioms implicated: <list>. Alternative: <one concrete design change expressed as a JSON diff>. Expected effect: <cost / throttle / amp delta>. Cost of change: <schema migration impact, runtime complexity, etc.>.`

If `design_findings.json` reports `no_significant_findings: true`, this section consists of a single line:

> Measurements support the current design. No alternative is argued for by this run.

…and the Iteration offer section below is omitted.

## `## Iteration offer`

Generated **only when at least one design finding is present.** Three bullets — the three-level choice from SKILL.md `## Live validation`:

- **Calculator-only re-eval** — update the JSON with `<proposed changes>` and re-run `${SKILL_DIR}/scripts/calculate_costs.py`. No AWS calls.
- **Full re-eval** — calculator + a second live validation against the revised design. Requires re-consenting to AWS deployment and running the prior `teardown.sh` first unless the change is additive-only (e.g. adding a GSI).
- **No changes** — record the decision as a deviation per Artifact #5 with the user's stated reason.

Each bullet is rendered as-is; the agent does not re-phrase or collapse the three choices.

## `design_findings.json` schema

Written alongside `performance_report.md`. The agent reads this file to author the two Design reflection subsections above.

```json
{
  "classified_findings": [
    {
      "id": "finding-1",
      "category": "design",
      "signal": "high_gsi_amplification",
      "pattern_ids": ["U10"],
      "evidence": { "observed_amp": 2.1, "projection_implied_amp": 1.0, "projection": "ALL" },
      "axioms": ["Mechanics #7", "Mechanics #8"],
      "severity": "high"
    }
  ],
  "top_cost_drivers": [
    { "pattern_id": "U1", "monthly": 22680.0, "share": 0.41 }
  ],
  "no_significant_findings": false
}
```

Categories and signals:

| `signal` | Typical `category` | Source |
|---|---|---|
| `dominant_cost_patterns` | `design` | extrapolated monthly > 20% of total |
| `persistent_throttles` | `design` | throttles outside warmup on a pattern whose `abort_on_throttle_rate` guard did not fire |
| `high_gsi_amplification` | `design` | observed amp > projection-implied by >15%, or amp × base write rate > 1.5× |
| `strong_read_overhead` | `design` | `consistency: "strong"` pattern whose extrapolated cost > 2× the eventual equivalent |
| `page_cap_hits` | `design` | Query pattern whose observed items/request hit the 900 KB cap |
| `cold_start_elevated_patterns` | `design` | `warmup_p99 > 2 × steady_p99` |
| `key_skew_patterns` | `design` | `steady_state.key_distribution.stddev_over_mean > 0.5` AND hot-partition distress — **either** steady-state throttles > 0 **or** the hottest partition's p99 > 1.8× the cold partitions' p99 (a baseline-free, within-pattern latency comparison via `key_distribution.hot_partition_p99_ms` / `cold_partition_p99_ms`). Axiom: Mechanics #3. **Emitted only for representative/zipf runs** that carry `key_distribution`; uniform runs omit the field so it never fires spuriously. `evidence.evidence_kind` is `"throttles"` (severity high — a hard ceiling breach, typical on provisioned) or `"elevated_latency"` (severity medium — adaptive capacity absorbing a hot key as latency, typical on on-demand). Both point to the same fix: write-shard the partition key or re-aggregate. |
| `large_expected_observed_delta_patterns` | `input-accuracy` | \|observed − expected\| / expected > 0.1 with likely input-mismatch cause. **Throttled patterns are excluded** — a throttled write reports low observed CU because calls were rejected, not because the item size was overstated; labeling it `item_size_off` would contradict the throttle finding. |
| `seed_shortfall` | `correctness` | a table whose `seed_verification` is `passed:false AND sampled:false` — the bounded-pagination COUNT reached exhaustion below 50% of the (capped) expected seed. Severity high; flips `no_significant_findings`. Means measurements ran against far less data than declared. |

The top-level `design_findings.json` also carries **`coverage_incomplete`** (bool): true when the run measured fewer than all declared patterns (or every pattern recorded zero calls). When true the report prints a prominent ⚠️ banner at the very top and `no_significant_findings` is forced false — a half-finished benchmark never reads as a clean result.

The script does **not** hardcode prescriptions. It surfaces facts; the agent decides what to do about them using the axioms listed in the `axioms` field.

### Representative-mode additions

When the run's `mode` is `"representative"`. The mode is surfaced at the `perf_summary.json` **top level** (`summary["mode"]`) by `benchmark_model.py`, echoed back from the Lambda — the report reads `summary["mode"]` first and falls back to `summary["config"]["mode"]` for older summaries.

- The **disclaimer block** gains a second paragraph: throttle/latency numbers are *load-risk* signals collected under deliberate hot-key skew at bounded scale, scale **nonlinearly**, and must not be extrapolated to peak; the cost figures stay valid because they use declared peak and scale-invariant per-op CU.
- A **`## Load-risk signals (representative mode only)`** section appears after `## Access Pattern Measurements`: a per-pattern table of `throttles`, `p99 ms`, observed `amp`, `top-key share`, and `distinct keys`, with a nonlinear-extrapolation caption. Throttled patterns are split by a **skew-vs-starvation test**: a throttled pattern is called a hot partition (write-shard / re-aggregate) **only** when its hot-partition p99 is ≥ 1.3× the cold-partition p99. When hot p99 ≈ cold p99, the section instead reports **uniform capacity starvation, not key skew** — the whole table/GSI was under-provisioned for the driven load, the run did not isolate a hot-partition effect, and the advice is to re-run with capacity set above uniform demand. This prevents reading "I starved the table" as "I found a hot partition."
- The **`## Not validated by this run`** Mechanics #3 line flips from "did not push to ceilings by design" to "PROBED under zipf skew at bounded scale — see Load-risk signals," and notes that throttles indicate a hot partition **only** when hot p99 ≫ cold p99; throttles with hot p99 ≈ cold p99 are uniform starvation, not skew.
- `perf_summary.json` carries `steady_state.key_distribution = {n_distinct_keys, top_key_share, stddev_over_mean, hot_partition_p99_ms, cold_partition_p99_ms}` per pattern. **Emitted only for zipf sampling** (representative mode, or an explicit `read_pattern_key_sampling: "zipf"` config). Uniform runs (quick/standard) record the per-row `key_idx` but `_aggregate` omits the `key_distribution` block, because a uniform round-robin distribution is flat by construction (`stddev_over_mean ≈ 0`) and the `key_skew_patterns` signal could never fire usefully — so it is gated on the config, keeping the signal strictly representative-mode.

## Invariants callers can rely on

- Every table in `## Access Pattern Measurements` uses steady-state numbers only. Warmup rows are excluded. Cold-start numbers appear only in `## Cold start`.
- `Expected RCU/WCU` in the Access Pattern Measurements table comes from `calculate_costs.pattern_monthly_cost(ap, table_def, entity_attr_sizes)["cap"]` — i.e. the identical helper that powers `cost_report.md`. The numbers match `cost_report.md` exactly.
- `Extrapolated Monthly Cost (measurement-based)` uses the same `WRU_PRICE`, `RRU_PRICE`, and `SECONDS_PER_MONTH` constants as `calculate_costs.py`. Unit-cost drift is not a failure mode — the calculator and the extrapolator share the pricing module.
- `design_findings.json` is always written, even when `no_significant_findings: true`. The agent checks the flag rather than checking file existence.
- The Iteration offer section is emitted only when at least one finding has `category: "design"`. Input-accuracy-only runs do not produce an iteration offer — the fix is to update the JSON and re-run the calculator, and the Input-accuracy subsection already names that.
