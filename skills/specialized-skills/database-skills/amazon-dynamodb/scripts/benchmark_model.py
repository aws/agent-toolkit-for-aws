#!/usr/bin/env python3
"""Orchestrate the in-region benchmark Lambda — invoke, stitch, aggregate.

This script runs on the user's machine. It does NOT issue any DynamoDB
data-path calls itself — that would measure the user's local network instead
of the design. All data-path work happens inside the benchmark Lambda
deployed by deploy_model.py, which lives in the same region as the tables.

Responsibilities:

  1. Budget check + split. If settle + seed + warmup + duration exceeds
     ~90% of the Lambda timeout, split measurement across N sequential
     invocations. Settle/seed/warmup run once in the first invocation only.
  2. Invoke the Lambda one or more times, passing patterns + manifest + config.
  3. Concatenate raw rows from every invocation response.
  4. Aggregate into perf_summary.json (per-pattern steady-state + cold-start +
     coverage + seed verification).

Usage:
    python3 benchmark_model.py \\
        --model dynamodb_data_model.json \\
        --config benchmark_config.json \\
        --manifest created_resources.json \\
        --raw-out perf_raw.jsonl \\
        --summary-out perf_summary.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Import the sibling calculator for exact per-op CU parity in the spend
# estimate — same module generate_perf_report.py uses, so the guardrail's
# numbers match the calculator the user already trusts.
_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
try:
    import calculate_costs as cc  # noqa: E402
except Exception:  # pragma: no cover - calculator is a sibling; should import
    cc = None  # type: ignore[assignment]


# Write ops, used by the spend estimate when the calculator import is
# unavailable. Mirrors calculate_costs.WRITE_OPS (the source of truth when cc is
# importable); kept here so the estimate still works in a cc-less environment.
_FALLBACK_WRITE_OPS = {
    "PutItem",
    "UpdateItem",
    "DeleteItem",
    "BatchWriteItem",
    "TransactWriteItems",
}


def _die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _require_boto3():
    try:
        import boto3  # noqa: F401
        from botocore.exceptions import ClientError  # noqa: F401

        return boto3
    except ImportError:
        _die("boto3 not installed. Run: pip install boto3>=1.34")


def _load_json(path: Path) -> dict:
    if not path.exists():
        _die(f"file not found: {path}")
    with path.open() as f:
        return json.load(f)


_QUICK_PRESET = {
    "table_settle_seconds": 10,
    "warmup_seconds": 3,
    "duration_seconds": 15,
    "ramp_seconds": 3,
    "seed_items_per_table": 100,
}

# Representative mode: a proportionally-higher load tier that surfaces SCALE
# risk (hot partitions, throttle-under-load, GSI amplification at volume,
# Query-at-realistic-cardinality) at bounded cost. Distinct from quick/standard,
# which validate per-op UNIT cost at ~1% scale. scale_factor sits in the
# confirmed 0.10–0.25 band; zipf sampling concentrates load on a few partitions
# so one partition can approach the per-partition ceiling (Mechanics #3);
# items_per_partition makes partitions hold real collections so Query patterns
# read realistic multi-item pages. max_rps_per_pattern is the HONEST ceiling:
# one in-region Lambda with 32 I/O-bound threads tops out near 1500–2000
# RPS/pattern (raised from the prior 8-thread ~800–1000).
_REPRESENTATIVE_PRESET = {
    "table_settle_seconds": 45,
    "warmup_seconds": 15,
    "duration_seconds": 120,
    "ramp_seconds": 20,
    "seed_items_per_table": 2000,
    "items_per_partition": 40,
    "scale_factor": 0.15,
    "max_rps_per_pattern": 1800,
    "min_rps_per_pattern": 5,
    "concurrency_per_pattern": 32,
    "read_pattern_key_sampling": "zipf",
    "zipf_s": 1.1,
}

_PRESETS: dict[str, dict[str, Any]] = {
    "quick": _QUICK_PRESET,
    "representative": _REPRESENTATIVE_PRESET,
}


def _apply_mode_preset(cfg: dict) -> dict:
    """Overlay a mode preset (quick / representative) on cfg.

    The preset only fills fields the user did NOT set explicitly — an explicit
    value in benchmark_config.json always wins. Unknown modes are refused so a
    typo like "quik" doesn't silently run a default-shaped benchmark.
    """
    mode = cfg.get("mode")
    if mode is None or mode == "standard":
        return cfg
    if mode not in _PRESETS:
        _die(
            f'unknown benchmark mode {mode!r}. Valid values: "quick", '
            '"representative", "standard" (default).'
        )
    merged = dict(cfg)
    for k, v in _PRESETS[mode].items():
        if k not in cfg:
            merged[k] = v
    if mode == "quick":
        print(
            "Quick mode: running a short per-pattern window "
            f"(settle={merged['table_settle_seconds']}s, "
            f"warmup={merged['warmup_seconds']}s, "
            f"duration={merged['duration_seconds']}s, "
            f"seed={merged['seed_items_per_table']} items). "
            "Percentiles and extrapolation are less stable than the standard "
            "mode — treat this run as a smoke test, not a cost-validation result."
        )
    elif mode == "representative":
        print(
            "Representative mode: scale ~"
            f"{merged.get('scale_factor', 0.15)}× declared peak, zipf hot-key "
            "sampling ON, capped at "
            f"{merged.get('max_rps_per_pattern', 1800)} RPS/pattern, "
            f"{merged.get('items_per_partition', 40)} items/partition. "
            "Surfaces hot-partition throttling, throttle-under-load, GSI "
            "amplification at volume, and Query-at-realistic-cardinality. "
            "ONE in-region Lambda (32 threads) tops out near 1500–2000 RPS/"
            "pattern — representative mode is BOUNDED and does NOT prove the "
            "design sustains declared peak RPS. Per-op cost extrapolation stays "
            "linear and valid; throttle/latency numbers are load-risk signals, "
            "not capacity-sustain proof — never extrapolate them linearly."
        )
    return merged


def _validate(model: dict) -> None:
    aps = model.get("access_patterns") or []
    if not aps:
        _die("access_patterns empty — refusing (Mechanics #2).")
    for ap in aps:
        if not ap.get("peak_rps"):
            _die(
                f"pattern {ap.get('pattern_id', '?')} has missing or zero "
                "peak_rps — refusing per Mechanics #2."
            )
    # Structural-reference check. Runs even on the reuse path (where deploy_model
    # is skipped), so a benchmark can never silently fail every call against a
    # missing table or a Query on a non-existent GSI — it refuses up front with a
    # clear message instead of reporting a "cheap" 0-CU run.
    tables_by_name = {t.get("table_name"): t for t in model.get("tables", [])}
    for ap in aps:
        pid = ap.get("pattern_id", "?")
        tn = ap.get("table")
        if not tn:
            _die(
                f'pattern {pid} has no "table" — every pattern must name the '
                "table it runs against."
            )
        td = tables_by_name.get(tn)
        if td is None:
            _die(
                f"pattern {pid} references table {tn!r}, not defined in tables[]. "
                f"Defined tables: {sorted(tables_by_name)}."
            )
        idx = ap.get("index")
        if idx:
            gsi_names = {g.get("index_name") for g in ((td or {}).get("gsis") or [])}
            if idx not in gsi_names:
                _die(
                    f"pattern {pid} uses index {idx!r} on table {tn!r}, but that "
                    f"table defines no such GSI. Defined GSIs: "
                    f"{sorted(n for n in gsi_names if n)}. A Query/Scan against a "
                    "non-existent index fails every call — fix the design JSON."
                )


def _compute_split(cfg: dict, n_patterns: int) -> tuple[int, float]:
    """Return (invocations_total, per_invocation_timeout_estimate).

    The Lambda runs patterns serially inside a single invocation (see
    run_warmup / run_measure in scripts/benchmark_lambda.py — they iterate
    patterns one at a time). Real wall-clock per invocation is therefore
    n_patterns × (warmup_seconds + duration_seconds_slice), NOT just
    warmup + duration. A 31-pattern design at 90s each takes ~47 min — well
    over Lambda's 15-min ceiling — so we must split into multiple
    invocations when the total would exceed the usable budget.
    """
    settle = int(cfg.get("table_settle_seconds", 30))
    # Seed wall-clock scales with total seed volume. run_seed seeds PER PATTERN
    # (each pattern's keys embed its pattern_id, so they don't dedup), writing
    # ~seed_items_per_table items per pattern in 25-item BatchWriteItem chunks at
    # ~30ms/batch (serial within the seed phase): seed_items/25 × 0.03s ×
    # n_patterns. Representative mode (2000 items) is ~2.4s per pattern. Scaling
    # by n_patterns (not a flat 60s) keeps the split honest for many-pattern
    # designs that seed a lot.
    seed_items = int(cfg.get("seed_items_per_table", 500))
    seed = int(30 + (seed_items / 25.0) * 0.03 * max(1, n_patterns))
    warmup = int(cfg.get("warmup_seconds", 10))
    duration = int(cfg.get("duration_seconds", 90))
    aggregation_margin = 20
    lambda_timeout = int(cfg.get("lambda_timeout_seconds", 900))
    usable = lambda_timeout * 0.9

    # First invocation carries settle + seed + per-pattern warmup once.
    first_overhead = settle + seed + n_patterns * warmup + aggregation_margin
    # Subsequent invocations only measure; overhead is just the margin.
    subsequent_overhead = aggregation_margin

    total_measure_time = n_patterns * duration

    # Can we fit everything into one invocation?
    if first_overhead + total_measure_time <= usable:
        return 1, usable

    # Need to split. Compute the per-invocation measurement budget for each
    # regime (first vs subsequent) and size the slice conservatively.
    first_slice_budget = max(0, usable - first_overhead)
    subsequent_slice_budget = max(0, usable - subsequent_overhead)

    # Use the smaller of the two so the same duration_per_pattern fits both.
    per_invocation_measure_budget = min(first_slice_budget, subsequent_slice_budget)
    if per_invocation_measure_budget <= 0:
        # First invocation's overhead alone exceeds usable — insufficient
        # Lambda timeout for this design. Caller can surface this.
        return -1, usable

    slice_per_pattern = max(1, int(per_invocation_measure_budget // n_patterns))
    per_invocation_total_measure = slice_per_pattern * n_patterns
    invocations = max(2, int(-(-total_measure_time // per_invocation_total_measure)))
    return invocations, usable


def _invoke_lambda(lambda_client, function_name: str, payload: dict):
    raw = json.dumps(payload).encode()
    resp = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=raw,
    )
    status = resp.get("StatusCode", 0)
    body = resp["Payload"].read()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        _die(
            f"Lambda returned non-JSON payload (status {status}): "
            f"{body[:200].decode(errors='replace')}"
        )
    if resp.get("FunctionError"):
        _die(f"Lambda function error ({resp['FunctionError']}): " f"{json.dumps(parsed)[:500]}")
    return parsed


def _bench_rps(pattern: dict, cfg: dict) -> float:
    declared = float(pattern.get("peak_rps", 0) or 0)
    scaled = declared * float(cfg.get("scale_factor", 0.01))
    return max(
        float(cfg.get("min_rps_per_pattern", 1)),
        min(float(cfg.get("max_rps_per_pattern", 50)), scaled),
    )


def _estimate_bench_spend(model: dict, cfg: dict) -> dict:
    """Estimate the actual AWS charge a run will incur, BEFORE running it.

    This is a PRE-SPEND gate distinct from the in-Lambda abort_on_throttle_rate
    runtime guard. Representative runs drive far more traffic than the ~1% unit-
    cost runs, so a cheap upper-bound estimate lets the orchestrator refuse (or
    ask consent) before creating the bill. Two cost components:

      driven load — Σ_patterns bench_rps × (warmup + duration) calls, each at the
                    calculator's expected per-op CU × on-demand unit price.
      seeding     — seed_items_per_table × items_per_partition writes per table
                    that has a pattern, each ⌈item_size/1KB⌉ WRU.

    Uses the calculator's own per-op CU so the estimate is consistent with the
    numbers the user already sees. Falls back to a coarse per-op CU when the
    calculator import is unavailable. Conservative by construction (counts the
    full warmup+duration window and ignores throttle-shed traffic)."""
    aps = model.get("access_patterns") or []
    tables = model.get("tables") or []
    table_map = {t["table_name"]: t for t in tables}
    entity_attr_sizes = cc._build_entity_attr_sizes(tables) if cc else {}

    warmup = float(cfg.get("warmup_seconds", 10))
    duration = float(cfg.get("duration_seconds", 90))
    window = warmup + duration

    driven_cost = 0.0
    per_pattern = []
    for ap in aps:
        rps = _bench_rps(ap, cfg)
        calls = rps * window
        op = ap.get("operation", "GetItem")
        write_ops = cc.WRITE_OPS if cc else _FALLBACK_WRITE_OPS
        is_write = op in write_ops
        if cc:
            td = table_map.get(ap.get("table", ""))
            try:
                cap = cc.pattern_monthly_cost(ap, td, entity_attr_sizes)["cap"]
                cu_per_call = cap["rcus"] + cap["wcus"]
            except Exception:
                cu_per_call = 1.0
            unit = cc.WRU_PRICE if is_write else cc.RRU_PRICE
        else:
            cu_per_call = 1.0
            unit = 0.625 / 1_000_000 if is_write else 0.125 / 1_000_000
        c = calls * cu_per_call * unit
        driven_cost += c
        per_pattern.append(
            {"pattern_id": ap.get("pattern_id"), "bench_rps": rps, "calls": calls, "cost": c}
        )

    # Seeding cost: writes are billed ⌈item_size/1KB⌉ WRU each. run_seed seeds
    # PER PATTERN, not per table — every seeded key embeds the pattern_id
    # (_seed_pk(pid, …)), so patterns sharing a table do NOT dedup against each
    # other. A table with K read/write patterns therefore gets ~K ×
    # seed_items_per_table items. The seed item size run_seed uses is the LARGEST
    # declared item size among the patterns on that pattern's table, so price
    # each pattern at its table's max size. (n_partitions × items_per_partition
    # still ≈ seed_items_per_table per pattern, so items_per_partition does not
    # multiply the count.)
    seed_items = int(cfg.get("seed_items_per_table", 500))
    wru_price = cc.WRU_PRICE if cc else 0.625 / 1_000_000
    # Per-table max item size (matches run_seed's choice of seed item size).
    table_max_size: dict = {}
    for ap in aps:
        tn = ap.get("table")
        if not tn:
            continue
        table_max_size[tn] = max(
            table_max_size.get(tn, 0), int(ap.get("estimated_item_size_bytes", 1024))
        )
    seed_cost = 0.0
    for ap in aps:
        tn = ap.get("table")
        if not tn:
            continue
        item_kb = max(1, -(-table_max_size[tn] // 1024))  # ceil KB
        seed_cost += seed_items * item_kb * wru_price

    total = driven_cost + seed_cost
    return {
        "total_usd": total,
        "driven_usd": driven_cost,
        "seed_usd": seed_cost,
        "per_pattern": per_pattern,
        "window_seconds": window,
    }


def _percentile(values, q):
    if not values:
        return None
    try:
        if len(values) < 2:
            return values[0]
        quantiles = statistics.quantiles(values, n=100, method="inclusive")
        idx = max(0, min(len(quantiles) - 1, q - 1))
        return quantiles[idx]
    except statistics.StatisticsError:
        return values[0] if values else None


def _aggregate(
    rows: list[dict],
    patterns: list[dict],
    tables: list[dict],
    cfg: dict,
    exact_counts: dict | None = None,
) -> list[dict]:
    """Per-pattern aggregation: steady-state + cold-start blocks.

    `exact_counts` (keyed by (pattern_id, phase)) carries the Lambda's uncapped
    call/throttle tallies. When present, the steady-state call_count and
    throttle count come from it — not from the (per-key-capped) rows — so a
    down-sampled measure window never under-reports throttles. Latency
    percentiles still come from the recorded rows (a representative sample)."""
    exact_counts = exact_counts or {}
    gsi_index_names = {}
    for t in tables:
        for g in t.get("gsis") or []:
            gsi_index_names[g["index_name"]] = g

    out = []
    for p in patterns:
        pid = p["pattern_id"]
        p_rows = [r for r in rows if r.get("pattern_id") == pid]
        measure = [r for r in p_rows if r.get("phase") == "measure"]
        warmup = [r for r in p_rows if r.get("phase") == "warmup"]

        def _lat(rs):
            return [r["latency_ms"] for r in rs if r.get("latency_ms") is not None]

        measure_lat = _lat(measure)
        warmup_lat = _lat(warmup)

        measure_cu = [r["consumed_cu"] for r in measure if r.get("consumed_cu") is not None]
        mean_cu = sum(measure_cu) / len(measure_cu) if measure_cu else 0.0

        gsi_sum: dict = {}
        base_wcu_sum = 0.0
        gsi_wcu_sum = 0.0
        for r in measure:
            for name, v in (r.get("gsi_cu") or {}).items():
                gsi_sum[name] = gsi_sum.get(name, 0.0) + v
                if p["operation"] in (
                    "PutItem",
                    "UpdateItem",
                    "DeleteItem",
                    "BatchWriteItem",
                    "TransactWriteItems",
                ):
                    gsi_wcu_sum += v
            if p["operation"] in (
                "PutItem",
                "UpdateItem",
                "DeleteItem",
                "BatchWriteItem",
                "TransactWriteItems",
            ):
                base_wcu_sum += r.get("consumed_cu", 0.0) or 0.0
        amp_ratio = (gsi_wcu_sum / base_wcu_sum) if base_wcu_sum > 0 else 0.0

        # Prefer the Lambda's exact uncapped tallies for call/throttle/error
        # counts; fall back to row-derived counts when exact_counts is absent
        # (older Lambda or a phase that recorded no exact tally). Counting errors
        # from the exact tally — not the capped rows — means a structurally broken
        # pattern's true error count survives row down-sampling, so the report can
        # raise a correctness finding rather than letting a "0 observed CU" delta
        # look benign. The Lambda's `errors` tally is NON-throttle only (throttles
        # are counted separately); the row fallback excludes throttled rows to
        # match that definition.
        ec = exact_counts.get((pid, "measure"))
        exact_calls = ec["calls"] if ec else len(measure)
        exact_throttles = ec["throttles"] if ec else sum(1 for r in measure if r.get("throttled"))
        if ec and "errors" in ec:
            exact_errors = ec["errors"]
            error_codes = dict(ec.get("error_codes") or {})
        else:
            exact_errors = sum(1 for r in measure if r.get("error") and not r.get("throttled"))
            error_codes = {}
            for r in measure:
                if r.get("error") and not r.get("throttled"):
                    error_codes[r["error"]] = error_codes.get(r["error"], 0) + 1
        error_rate = (exact_errors / exact_calls) if exact_calls else 0.0
        # Per-item Transact* cancellation reasons (e.g. {"TransactionConflict":
        # 13}) so the report can say WHY transactions cancelled instead of just
        # "TransactionCanceledException". Older Lambdas don't emit it → {}.
        cancellation_reason_codes = dict((ec or {}).get("cancellation_reason_codes") or {})

        steady = {
            "call_count": exact_calls,
            "rows_sampled": len(measure),
            "p50_ms": _percentile(measure_lat, 50),
            "p95_ms": _percentile(measure_lat, 95),
            "p99_ms": _percentile(measure_lat, 99),
            "mean_observed_cu": mean_cu,
            "gsi_cu_by_index": gsi_sum,
            "amplification_ratio": amp_ratio,
            "throttles": exact_throttles,
            "errors": exact_errors,
            "error_rate": error_rate,
            "error_codes": error_codes,
            "cancellation_reason_codes": cancellation_reason_codes,
        }

        # Key-distribution histogram → drives the key_skew_patterns signal
        # (hot-partition risk, Mechanics #3). Emitted ONLY for skewed (zipf)
        # sampling — i.e. representative mode or an explicit zipf config. Uniform
        # runs (quick/standard) DO record key_idx on every row, but a uniform
        # round-robin distribution is flat by construction, so its stddev_over_mean
        # ≈ 0 and the key_skew signal could never fire usefully; omitting the field
        # entirely keeps the documented guarantee ("uniform runs omit it") true and
        # the signal strictly representative-mode. Gate on the config, not on the
        # mere presence of key_idx.
        key_sampling = (cfg.get("read_pattern_key_sampling") or "uniform").lower()
        measure_keyed = (
            [r for r in measure if r.get("key_idx") is not None] if key_sampling == "zipf" else []
        )
        part_idxs = [r["key_idx"] for r in measure_keyed]
        if part_idxs:
            counts: dict = {}
            for k in part_idxs:
                counts[k] = counts.get(k, 0) + 1
            freqs = list(counts.values())
            n = len(part_idxs)
            mean_f = n / len(counts)
            var = sum((f - mean_f) ** 2 for f in freqs) / len(counts)
            stddev = var**0.5
            hot_part = max(counts, key=lambda k: counts[k])
            # Baseline-free hot-partition latency signal: the hottest partition's
            # tail latency vs every OTHER partition's, within this same pattern.
            # If the hot partition is materially slower than the cold ones, that
            # is a hot partition by definition — independent of other patterns or
            # absolute thresholds. On on-demand tables this is how a hot key
            # shows up (adaptive capacity absorbs it as latency, not throttles).
            hot_lat = [
                r["latency_ms"]
                for r in measure_keyed
                if r["key_idx"] == hot_part and r.get("latency_ms") is not None
            ]
            cold_lat = [
                r["latency_ms"]
                for r in measure_keyed
                if r["key_idx"] != hot_part and r.get("latency_ms") is not None
            ]
            steady["key_distribution"] = {
                "n_distinct_keys": len(counts),
                "top_key_share": max(freqs) / n,
                "stddev_over_mean": (stddev / mean_f) if mean_f > 0 else 0.0,
                "hot_partition_p99_ms": _percentile(sorted(hot_lat), 99),
                "cold_partition_p99_ms": _percentile(sorted(cold_lat), 99),
            }

        cold_start_elevated = False
        w_p50 = _percentile(warmup_lat, 50)
        w_p99 = _percentile(warmup_lat, 99)
        if w_p99 is not None and steady["p99_ms"] is not None and steady["p99_ms"] > 0:
            cold_start_elevated = w_p99 > 2 * steady["p99_ms"]

        cold = {
            "warmup_call_count": len(warmup),
            "warmup_p50_ms": w_p50,
            "warmup_p99_ms": w_p99,
            "warmup_throttles": sum(1 for r in warmup if r.get("throttled")),
            "cold_start_elevated": cold_start_elevated,
        }

        out.append(
            {
                "pattern_id": pid,
                "bench_rps": _bench_rps(p, cfg),
                "steady_state": steady,
                "cold_start": cold,
                "measurement_tainted": False,  # set by caller if Lambda flagged it
            }
        )

    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", required=True, help="path to dynamodb_data_model.json (the design)")
    p.add_argument(
        "--config",
        required=True,
        help="path to benchmark_config.json (per-run knobs; mode, "
        "scale, seeding — see references/performance-model-schema.md)",
    )
    p.add_argument(
        "--manifest",
        required=True,
        help="path to created_resources.json written by deploy_model.py "
        "(names the deployed tables + benchmark Lambda to invoke)",
    )
    p.add_argument(
        "--raw-out",
        required=True,
        help="output path for per-call rows (JSONL, large; human/agent "
        "do NOT read this — it feeds generate_perf_report.py)",
    )
    p.add_argument(
        "--summary-out",
        required=True,
        help="output path for the aggregated perf_summary.json consumed "
        "by generate_perf_report.py",
    )
    p.add_argument(
        "--allow-spend",
        action="store_true",
        help="acknowledge the estimated AWS spend and skip the cost-guardrail "
        "refusal (the orchestrator forwards this after user consent).",
    )
    args = p.parse_args()

    boto3_mod = _require_boto3()
    model = _load_json(Path(args.model))
    cfg = _apply_mode_preset(_load_json(Path(args.config)))
    manifest = _load_json(Path(args.manifest))

    _validate(model)

    if "lambda" not in manifest:
        _die(
            "manifest has no 'lambda' block — this benchmark_model.py "
            "expects a Lambda-based run. Re-run deploy_model.py on the "
            "current version of the skill."
        )

    session = boto3_mod.Session(profile_name=cfg["aws_profile"], region_name=cfg["region"])
    # Sync Lambda invoke holds the HTTP connection for up to `lambda_timeout_seconds`.
    # boto3 default read_timeout is 60s — way too short for a 90+s benchmark.
    # Bump to the Lambda timeout plus a safety margin and disable boto's own
    # invoke retries (Lambda surfaces handler errors via FunctionError we already
    # parse; retrying would re-run the benchmark).
    from botocore.config import Config as _BotoConfig

    _invoke_timeout = int(cfg.get("lambda_timeout_seconds", 900)) + 60
    lam = session.client(
        "lambda",
        config=_BotoConfig(
            retries={"max_attempts": 1, "mode": "standard"},
            read_timeout=_invoke_timeout,
            connect_timeout=10,
        ),
    )
    fn_name = manifest["lambda"]["function_name"]

    invocations_total, _ = _compute_split(cfg, len(model["access_patterns"]))
    if invocations_total < 0:
        _die(
            "Even a single Lambda invocation's settle+seed+warmup overhead "
            "exceeds the configured lambda_timeout_seconds. Either increase "
            "lambda_timeout_seconds (max 900), reduce warmup_seconds, or "
            "reduce the number of access patterns benchmarked per run."
        )
    print(
        f"Benchmark budget: {len(model['access_patterns'])} pattern(s), "
        f"splitting measurement across {invocations_total} Lambda invocation(s)."
    )

    # Upfront wall-clock estimate + a loud foreground reminder. Patterns run
    # SERIALLY inside the Lambda, so total time ≈ settle + seed + Σ_patterns
    # (warmup + duration), plus a little per-invocation handoff. This is the most
    # reliable nudge against the failure mode where the agent lets a long run get
    # auto-backgrounded (when it exceeds a tool's default timeout) and then reads
    # a stale prior summary. Seeing "~N min — run foreground and wait" BEFORE the
    # blocking phase is what reliably triggers the right behavior.
    _np = len(model["access_patterns"])
    _settle = int(cfg.get("table_settle_seconds", 30))
    _seedw = int(30 + (int(cfg.get("seed_items_per_table", 500)) / 25.0) * 0.03 * max(1, _np))
    _warm = int(cfg.get("warmup_seconds", 10))
    _dur = int(cfg.get("duration_seconds", 90))
    _est_s = _settle + _seedw + _np * (_warm + _dur) + invocations_total * 20
    _est_min = _est_s / 60.0
    print(
        f"Estimated wall-clock: ~{_est_min:.0f} min "
        f"({_est_s}s: {_settle}s settle + ~{_seedw}s seed + "
        f"{_np} patterns x ({_warm}s warmup + {_dur}s measure), serial)."
    )
    if _est_s > 110:
        print(
            "  ┌─ RUN THIS IN THE FOREGROUND AND WAIT ─────────────────────────┐\n"
            f"  │ This run takes ~{_est_min:.0f} min, longer than a default tool/shell │\n"
            "  │ timeout. Do NOT background it: a backgrounded run can be       │\n"
            "  │ killed mid-flight, leaving a STALE perf_summary.json that      │\n"
            "  │ looks fresh. Raise your tool's timeout to exceed the estimate  │\n"
            "  │ above and let this command block to completion. Verify         │\n"
            "  │ benchmark_completed_at in the summary post-dates launch.       │\n"
            "  └────────────────────────────────────────────────────────────────┘",
            flush=True,
        )

    # Cost guardrail (pre-spend gate). Estimate the actual AWS charge BEFORE
    # invoking the Lambda. Refuse if it exceeds cost_guardrail_usd unless the
    # user explicitly acknowledged via --allow-spend. Distinct from the in-Lambda
    # abort_on_throttle_rate runtime guard.
    guardrail = float(cfg.get("cost_guardrail_usd", 0.50))
    spend = _estimate_bench_spend(model, cfg)
    print(
        f"Estimated AWS spend for this run: ~${spend['total_usd']:.3f} "
        f"(driven load ~${spend['driven_usd']:.3f} + seeding "
        f"~${spend['seed_usd']:.3f}). Guardrail: ${guardrail:.2f}."
    )
    if spend["total_usd"] > guardrail and not args.allow_spend:
        _die(
            f"estimated spend ${spend['total_usd']:.3f} exceeds the cost "
            f"guardrail ${guardrail:.2f}. Lower scale_factor / duration_seconds "
            "/ max_rps_per_pattern, raise cost_guardrail_usd in "
            "benchmark_config.json, or re-run with --allow-spend to proceed "
            "after acknowledging the charge.",
            code=3,
        )

    all_rows: list[dict] = []
    tainted_overall: dict = {}
    coverage_union_measured: set = set()
    seed_verification: dict = {}
    first_invocation_errored = False
    # Load-shape knobs the Lambda echoes back (mode, key_sampling,
    # items_per_partition). Captured from the first invocation and surfaced at
    # the summary top-level so generate_perf_report can branch its disclaimer /
    # Load-risk section off the ACTUAL run, not just the config it was handed.
    lambda_echo: dict = {}
    # Accumulate exact (uncapped) call/throttle tallies across invocations,
    # keyed by (pattern_id, phase). These override the row-derived counts in
    # _aggregate so throttles are never under-reported when rows were capped.
    exact_counts: dict = {}

    # Wall-clock bookends for the whole invocation sequence. These let the
    # report (and the agent) confirm the summary came from THIS run, not a
    # stale prior one left on disk by a killed/backgrounded benchmark. The
    # summary is written once, after all invocations return, so a run that
    # never completes never stamps these — making them a reliable "completed"
    # marker. UTC, ISO-8601.
    run_started_at = datetime.now(timezone.utc)
    _wall_start = time.monotonic()

    for idx in range(invocations_total):
        is_first = idx == 0
        phase_plan = ["settle", "seed", "warmup", "measure"] if is_first else ["measure"]
        payload = {
            "phase_plan": phase_plan,
            "invocation_index": idx,
            "invocations_total": invocations_total,
            "patterns": model["access_patterns"],
            "tables": model["tables"],
            "manifest": manifest,
            "config": cfg,
        }
        print(
            f"Invoking Lambda (invocation {idx + 1}/{invocations_total}, " f"phases={phase_plan}) …"
        )
        t0 = time.monotonic()
        resp = _invoke_lambda(lam, fn_name, payload)
        dt = time.monotonic() - t0
        print(
            f"  returned in {dt:.1f}s, "
            f"{len(resp.get('raw_rows', []))} rows, "
            f"phases_run={resp.get('phases_run')}"
        )

        if is_first:
            seed_verification = resp.get("seed_verification") or {}
            if resp.get("seed_verification_failed"):
                print(
                    "  ! seed verification failed — aborting further invocations.", file=sys.stderr
                )
                all_rows.extend(resp.get("raw_rows") or [])
                first_invocation_errored = True
                break
            if resp.get("handler_error"):
                print(f"  ! Lambda handler error: {resp['handler_error']}", file=sys.stderr)
                all_rows.extend(resp.get("raw_rows") or [])
                first_invocation_errored = True
                break

        if is_first:
            for k in ("mode", "key_sampling", "items_per_partition"):
                if k in resp:
                    lambda_echo[k] = resp[k]

        all_rows.extend(resp.get("raw_rows") or [])
        tainted_overall.update(resp.get("measurement_tainted") or {})
        cov = resp.get("coverage") or {}
        for pid in cov.get("measured_patterns") or []:
            coverage_union_measured.add(pid)
        for ec in resp.get("exact_counts") or []:
            key = (ec["pattern_id"], ec["phase"])
            agg = exact_counts.setdefault(
                key,
                {
                    "calls": 0,
                    "throttles": 0,
                    "errors": 0,
                    "error_codes": {},
                    "cancellation_reason_codes": {},
                },
            )
            agg["calls"] += ec.get("calls", 0)
            agg["throttles"] += ec.get("throttles", 0)
            agg["errors"] += ec.get("errors", 0)
            for code, cnt in (ec.get("error_codes") or {}).items():
                agg["error_codes"][code] = agg["error_codes"].get(code, 0) + cnt
            for code, cnt in (ec.get("cancellation_reason_codes") or {}).items():
                agg["cancellation_reason_codes"][code] = (
                    agg["cancellation_reason_codes"].get(code, 0) + cnt
                )

    # Write raw.
    raw_path = Path(args.raw_out)
    with raw_path.open("w") as f:
        for r in all_rows:
            f.write(json.dumps(r, default=str))
            f.write("\n")
    print(f"Raw rows: {raw_path} ({len(all_rows)} rows)")

    # Aggregate.
    patterns = model["access_patterns"]
    per_pattern = _aggregate(all_rows, patterns, model.get("tables") or [], cfg, exact_counts)
    for item in per_pattern:
        if item["pattern_id"] in tainted_overall:
            item["measurement_tainted"] = True
            item["tainted_reason"] = tainted_overall[item["pattern_id"]]

    declared = {p["pattern_id"] for p in patterns}
    missing = sorted(declared - coverage_union_measured)

    summary = {
        "run_id": manifest.get("run_id"),
        "account": manifest.get("account"),
        "region": manifest.get("region"),
        "prefix": manifest.get("prefix"),
        "manifest": {
            "account": manifest.get("account"),
            "region": manifest.get("region"),
            "prefix": manifest.get("prefix"),
            "run_id": manifest.get("run_id"),
        },
        "config": cfg,
        # Freshness markers — written only here, after every invocation has
        # returned, so a killed/backgrounded run never produces them. The
        # report renders these and the agent checks benchmark_completed_at
        # against the time it launched the run; a stale summary (from a prior
        # run) will pre-date the launch and is caught instead of interpreted.
        "run_started_at": run_started_at.isoformat(),
        "benchmark_completed_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_wall_seconds": round(time.monotonic() - _wall_start, 1),
        "total_rows": len(all_rows),
        # Load-shape knobs as the Lambda actually ran them (echoed back). The
        # report prefers summary["mode"] over config["mode"] so it branches on
        # what ran, not just what was requested. Falls back to cfg if an older
        # Lambda didn't echo.
        "mode": lambda_echo.get("mode", cfg.get("mode", "standard")),
        "key_sampling": lambda_echo.get(
            "key_sampling", cfg.get("read_pattern_key_sampling", "uniform")
        ),
        "items_per_partition": lambda_echo.get(
            "items_per_partition", cfg.get("items_per_partition", 1)
        ),
        "invocations_total": invocations_total,
        "seed_verification": seed_verification,
        "coverage": {
            "measured_patterns": sorted(coverage_union_measured),
            "missing_patterns": missing,
            "coverage_incomplete": bool(missing) or first_invocation_errored,
        },
        "patterns": per_pattern,
    }
    sp = Path(args.summary_out)
    sp.write_text(json.dumps(summary, indent=2, default=str))
    print(f"Summary: {sp}")
    print(
        f"Benchmark completed at {summary['benchmark_completed_at']} "
        f"({summary['benchmark_wall_seconds']}s wall, "
        f"{summary['total_rows']} rows) — verify this timestamp is newer "
        f"than when you launched the run before trusting the report."
    )

    if summary["coverage"]["coverage_incomplete"]:
        print(
            f"\nWARNING: coverage incomplete — missing: {missing}",
            file=sys.stderr,
        )
        sys.exit(1 if first_invocation_errored else 0)


if __name__ == "__main__":
    main()
