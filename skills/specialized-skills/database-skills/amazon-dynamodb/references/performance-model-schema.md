# Benchmark config JSON schema

The live-validation scripts (`${SKILL_DIR}/scripts/deploy_model.py`, `${SKILL_DIR}/scripts/benchmark_model.py`, `${SKILL_DIR}/scripts/generate_perf_report.py`) read `dynamodb_data_model.json` — the same design JSON consumed by `${SKILL_DIR}/scripts/calculate_costs.py` (see `${SKILL_DIR}/references/cost-model-schema.md`) — plus a **separate** `benchmark_config.json` that carries per-run knobs. Keeping them separate preserves the design JSON as the single source of truth for the design itself; the benchmark config is short-lived and run-specific. (`${SKILL_DIR}` is defined in SKILL.md "Resolving the skill's own paths" — substitute the absolute path of the directory containing SKILL.md.)

This document specifies the JSON shape of `benchmark_config.json`, what each knob does, and how the defaults relate to measurement quality.

## Minimal working example

```json
{
  "aws_profile": "dev-sandbox",
  "region": "us-east-1",
  "resource_prefix": "ddb-skill-bench-20260512-abc12345",
  "_comment_resource_prefix": "optional — omit it and deploy_model.py generates ddb-skill-bench-<date>-<uuid8> for you",
  "tags": { "owner": "me@example.com", "purpose": "ddb-skill-bench", "ttl_hours": "4" },
  "mode": "standard",
  "table_settle_seconds": 30,
  "warmup_seconds": 10,
  "duration_seconds": 90,
  "ramp_seconds": 10,
  "scale_factor": 0.01,
  "max_rps_per_pattern": 50,
  "min_rps_per_pattern": 1,
  "concurrency_per_pattern": 32,
  "seed_items_per_table": 500,
  "abort_on_throttle_rate": 0.2,
  "read_pattern_key_sampling": "uniform",
  "dry_run": false
}
```

## Mode presets

`mode` (optional, default `"standard"`) picks a preset for the timing/seed knobs. Explicit values in the config always win; the preset only fills fields the user did not set.

| `mode` | Behavior |
|---|---|
| `"standard"` | Use the defaults documented in the tables below. The benchmark's statistical claims (p99 stability, extrapolated cost within tolerance) assume this mode. |
| `"quick"` | Short per-pattern window for a cheap smoke test — `table_settle_seconds: 10`, `warmup_seconds: 3`, `duration_seconds: 15`, `ramp_seconds: 3`, `seed_items_per_table: 100`. Useful when the user wants to confirm "does this design deploy and run at all?" without committing to a full validation. Percentiles are less stable and extrapolated cost is less trustworthy than `"standard"` — the report header labels this a smoke test. Per-pattern `scale_factor`/`min_rps`/`max_rps`/`concurrency_per_pattern` are unchanged by the preset, so driven RPS still reflects the design. |
| `"representative"` | **Scale-risk mode for the iterative design loop.** Drives proportionally higher load with hot-key skew and realistic item-collection cardinality to surface what `quick`/`standard` cannot: hot-partition throttling, throttle-under-load, GSI amplification at volume, and Query-at-realistic-cardinality. Preset: `scale_factor: 0.15` (in the 0.10–0.25 band), `max_rps_per_pattern: 1800` (the honest ceiling — one in-region Lambda with `concurrency_per_pattern: 32` threads tops out near 1,500–2,000 RPS/pattern), `min_rps_per_pattern: 5`, `concurrency_per_pattern: 32`, `seed_items_per_table: 2000`, `items_per_partition: 40`, `duration_seconds: 120`, `warmup_seconds: 15`, `table_settle_seconds: 45`, `ramp_seconds: 20`, `read_pattern_key_sampling: "zipf"`, `zipf_s: 1.1`. **Honest scope:** representative mode is BOUNDED — it surfaces hot-partition/throttle risk at bounded cost; it does NOT prove the design sustains declared peak. Cost extrapolation stays linear and valid (per-op CU is scale-invariant, extrapolated against *declared* peak, never the driven bench RPS); throttle/latency are load-risk signals and must not be linearly extrapolated. This is the mode `iterate_design.py` runs by default. |

Unknown `mode` values are rejected at script startup (so a typo like `"quik"` can't silently fall back to defaults).

## Fields

### Required

| Field | Purpose |
|---|---|
| `aws_profile` | AWS CLI profile name for all boto3 clients. Must resolve to valid credentials before any script runs; the preflight in `deploy_model.py` prints caller identity and refuses if the resolved account alias or ARN contains `prod`, `production`, `prd`, or `live`. |
| `region` | AWS region. Used consistently for DynamoDB and for the `sts` identity check. Single-region deploy — `global_tables: true` on a table is noted but not exercised. |

### Resource naming

| Field | Default | Purpose |
|---|---|---|
| `resource_prefix` | *(auto-generated)* | String that every created resource gets prefixed with. **Optional** — omit it and `deploy_model.py` generates `ddb-skill-bench-<YYYYMMDD>-<uuid8>` from the run's clock, prints the value it chose, and writes it into the manifest. If you DO supply one it must start with `ddb-skill-bench-` (so teardown can scope deletions safely); any other value is refused. Supply your own only when you need a recognizable, stable prefix; otherwise leave it out and let the deploy name the run. |

### Tagging

| Field | Default | Purpose |
|---|---|---|
| `tags` | `{}` | Extra tags merged onto every `CreateTable`. Always joined with the built-in tags `{purpose: ddb-skill-bench, run_id: <uuid>, created_at: <iso>, prefix: <prefix>}`. Use this to attach an owner, a cost-allocation tag, or a TTL expectation for cleanup tooling. |

### Cold-start discipline

These three knobs control how bias from fresh-table capacity, client warmup, and partition priming is excluded from steady-state numbers. Tightening them trades measurement quality for total runtime. See SKILL.md `## Live validation` — "Cold-start discipline" for the rationale.

| Field | Default | Effect |
|---|---|---|
| `table_settle_seconds` | `30` | Time to wait after `table_exists` returns before any measurement or seed call. On-demand tables start at baseline capacity (~2,000 WCU / ~4,000 RCU) and need a short window for adaptive capacity to stabilize. Setting to `0` will show throttles on fresh-table traffic that steady-state would not produce — useful as a one-off diagnostic, never trustworthy as a default. |
| `warmup_seconds` | `10` | Per-pattern warmup window run at measurement RPS *before* the measurement window. Rows are tagged `phase: "warmup"` and excluded from percentiles and the extrapolation. Reported separately as a cold-start snapshot: patterns where `warmup_p99 > 2 × steady_p99` are flagged `cold_start_elevated: true` in the report. |
| `seed_items_per_table` | `500` | Synthetic items written via `BatchWriteItem` (25-item batches) before measurement starts, for each table targeted by a read pattern. Seeds warm partitions the benchmark will later hit. Rows tagged `phase: "seed"` and excluded from measurement aggregation. Set to `0` to skip seeding entirely (reads will hit missing keys, flagging GetItem `non_existent_rate` as 100% — diagnostic but not representative). |

### Measurement window

| Field | Default | Effect |
|---|---|---|
| `duration_seconds` | `90` | Measurement-phase length per pattern. Short windows (under 60s) give statistically unstable percentiles on low-RPS patterns. Longer windows (over 180s) cost more and rarely move the numbers materially for a unit-cost benchmark. |
| `ramp_seconds` | `10` | Portion of the measurement window during which the abort guard is armed. Throttles concentrated in the first `ramp_seconds` often mean the warmup window was insufficient, not that the design is bad. After `ramp_seconds`, throttles feed `measurement_tainted: true` and stop the pattern. |
| `scale_factor` | `0.01` | Multiplier applied to each pattern's declared `peak_rps` before clamping. `0.01` means benchmark at 1% of declared load — cheap, single-digit cents for a typical run, still adequate for per-op unit-cost validation. The report extrapolates linearly using the declared `peak_rps`. |
| `min_rps_per_pattern` | `1` | Lower clamp on post-scale RPS. Ensures every pattern produces at least a handful of samples even when `peak_rps × scale_factor` would round to zero. Raise this if low-traffic patterns are producing percentile columns marked "insufficient samples." |
| `max_rps_per_pattern` | `50` | Upper clamp. Caps the bill on extremely-high-RPS patterns and keeps the run inside shared-account throttle budgets. Patterns that hit this cap are flagged in the report so the user knows the extrapolation assumes linear scaling. |
| `concurrency_per_pattern` | `32` | Threads per pattern in the `ThreadPoolExecutor`. Each thread issues one `DescribeTable` on startup to force TLS handshake + credential refresh off the critical path. At the unit-cost `scale_factor 0.01` default the pool is far larger than the driven RPS needs, so most threads idle — it matters in `"representative"` mode, where 32 threads are what let one in-region Lambda sustain ~1,500–2,000 RPS/pattern (the honest single-Lambda ceiling). Drop to 4 or 2 for patterns that are bursty under contention. |

### Safety

| Field | Default | Effect |
|---|---|---|
| `abort_on_throttle_rate` | `0.2` | Fraction of calls throttled at which a pattern's measurement is aborted and flagged `measurement_tainted: true`. Armed through warmup + the first `ramp_seconds` of measurement. Throttles confined to warmup do not taint the run (`cold_start_elevated: true` instead). Lower this value on a shared account; raise it (up to `0.5`) only as a deliberate probe. |
| `dry_run` | `false` | When `true`, `deploy_model.py` prints intended `CreateTable` kwargs and exits without creating any resources or writing a manifest. Useful for reviewing what would be deployed before committing. |
| `cost_guardrail_usd` | `0.50` | **Pre-spend gate.** Before invoking the Lambda, `benchmark_model.py` estimates the actual AWS charge (driven-load CU + seeding writes, priced with the calculator's own per-op CU). If the estimate exceeds this value the run is REFUSED unless `--allow-spend` is passed (the orchestrator forwards it after user consent). Distinct from `abort_on_throttle_rate`, which is a *runtime* guard once the run is underway. Raise it for deliberately larger representative runs. |
| `provisioned_capacity` | *(unset → on-demand)* | Optional `{"read": N, "write": M}`. When set, `deploy_model.py` creates tables (and their GSIs) as **PROVISIONED** at that capacity instead of PAY_PER_REQUEST. Bench-only — production designs default to on-demand (Mechanics #19). Purpose: a low provisioned ceiling is a HARD per-table limit with no adaptive-capacity absorption, so hot-partition **throttling** (Mechanics #3) is observable — on on-demand, adaptive capacity absorbs a hot key as latency and a single load generator rarely throttles. Also the way to validate a *planned* provisioned capacity. A per-table `table.provisioned_capacity` overrides this global value. Note a fresh provisioned table carries ~5 min of burst capacity; use a longer `duration_seconds` or lower capacity so the burst drains and the sustained window throttles. |

### Read-pattern sampling

| Field | Default | Effect |
|---|---|---|
| `read_pattern_key_sampling` | `"uniform"` | How reads pick a target partition. `"uniform"` round-robins over the seeded partitions (even distribution). `"zipf"` (implemented) draws partition ranks with P(rank r) ∝ 1/r^`zipf_s`, concentrating load on a few hot partitions so one partition approaches the per-partition ceiling (Mechanics #3) and hot-partition throttling becomes observable. Auto-enabled by `"representative"` mode. Use `"zipf"` when probing hot-partition behavior; leave `"uniform"` for unit-cost runs. |
| `zipf_s` | `1.1` | Zipf skew exponent (higher = more concentrated). At `1.1` over ~50 partitions the hottest partition absorbs ~25% of traffic and dwarfs the tail ~70×. |
| `items_per_partition` | `1` | Collection cardinality per partition. `1` (quick/standard) means singleton partitions — every partition holds one item, so a Query reads one item and is indistinguishable from a GetItem. `> 1` (representative sets `40`) seeds that many distinct sort keys under each partition, so Query patterns read realistic multi-item pages and GSI collections are observable. The seeded partition count is `seed_items_per_table // items_per_partition`, and that partition count is the space the read-key sampler draws over. A table with no sort key cannot hold a collection and falls back to one item per partition. The size of the distinct-key sample pool is `seed_items_per_table` itself — there is no separate key-space knob. |

## How the knobs interact with measurement quality

- **Bias removal is cumulative.** The settle → seed → warmup sequence each removes a different class of bias. Skipping any one of them does not sum to "just a bit noisier" — the result is that the corresponding class of bias silently contaminates the steady-state numbers. Cold-start discipline is strongest when all three run.
- **Sample size matters for percentiles.** `p99` over 60 samples is not a `p99`. If `clamp(peak_rps × scale_factor, min, max) × duration_seconds < 100`, the report flags that pattern as "percentiles are not statistically meaningful" and widens to `p50`/`p95` only. Raise `min_rps_per_pattern` or widen `duration_seconds` to address.
- **Extrapolation assumes linearity.** Extrapolated monthly cost = mean observed CU × declared `peak_rps` × seconds-per-month × unit price. This is valid for per-op unit cost and GSI amplification; it is **not** valid for throttle behavior (throttles scale nonlinearly with partition-key skew — Mechanics #3). Patterns that hit `max_rps_per_pattern` and had throttles are flagged so the user does not read the extrapolation as a capacity-sustain claim. **`"representative"` mode deliberately surfaces this nonlinearity:** it drives hot-key skew to make throttles appear, and the report quarantines those throttle/latency numbers in a "Load-risk signals" section with an explicit "do not extrapolate" caption. The cost figure stays linear and valid because it uses *declared* peak and scale-invariant per-op CU — never the elevated driven RPS.
- **Shared-account throttle sensitivity.** If the sandbox account has other workloads running, raise `abort_on_throttle_rate` only if you've verified there's no external contention. The abort guard exists so a bad run stops instead of silently producing corrupted numbers.

## Environment preconditions (not config knobs, but scripts will refuse without them)

- `boto3 >= 1.34` installed. `deploy_model.py` and `benchmark_model.py` refuse with `pip install boto3>=1.34` on import failure.
- Valid AWS credentials resolvable via `aws_profile`. Expired SSO / missing token produces a specific remediation message (`aws sso login --profile <p>`) before any resource creation.
- Account identity does not contain prod markers. Even with `--yes-deploy`, `deploy_model.py` aborts if `sts get-caller-identity` returns an ARN or alias containing `prod`, `production`, `prd`, or `live`.
- `dynamodb_data_model.json` has non-empty `access_patterns` and every pattern has `peak_rps > 0`. Unknown RPS is a design gap (Mechanics #2), not a benchmark input.

## Tuning guide

| Goal | Adjust |
|---|---|
| Cheaper, quicker smoke test | `duration_seconds: 30`, `warmup_seconds: 5`, `seed_items_per_table: 100` |
| Sharper percentiles on low-RPS patterns | Raise `min_rps_per_pattern` or `duration_seconds` |
| Probe fresh-table cold-start behavior | `table_settle_seconds: 0`, `warmup_seconds: 0` — then read the Cold Start section of the report as the primary artifact |
| Avoid blowing the shared-account throttle budget | Lower `max_rps_per_pattern` and `concurrency_per_pattern`; raise `abort_on_throttle_rate` only if you've verified no external contention |
| Dry-run review before committing | `dry_run: true` on a first pass; then set `false` for the real run |
