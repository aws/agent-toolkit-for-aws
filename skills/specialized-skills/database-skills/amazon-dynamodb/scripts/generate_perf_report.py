#!/usr/bin/env python3
"""Turn perf_summary.json + the design JSON into performance_report.md + design_findings.json.

Imports calculate_costs directly so the Expected column matches the calculator
exactly — no formula duplication. Produces two artifacts:

  - performance_report.md — human-readable report per references/performance-report-format.md.
  - design_findings.json — machine-readable classified findings for the agent to
    reason over when authoring the Design reflection section.

No AWS calls; no side effects. Runs locally on any fixture.

Usage:
    python3 generate_perf_report.py \\
        --model dynamodb_data_model.json \\
        --summary perf_summary.json \\
        --output performance_report.md \\
        --findings-out design_findings.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Import the sibling calculator module for exact expected-number parity.
_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
import calculate_costs as cc  # noqa: E402

TOLERANCE = 0.10  # 10% deviation triggers flagging
PAGE_CAP_BYTES = cc.PAGE_CAP_KB * 1024
# Above this NON-throttle error rate a pattern is treated as structurally broken
# (e.g. ValidationException from a bad index/attr, a duplicate-key batch, or
# AccessDenied). Its observed CU/latency are meaningless, so it becomes a
# high-severity correctness finding rather than a benign cost-delta. Below it,
# sporadic errors are surfaced as a low-severity note.
ERROR_RATE_HIGH = 0.5

# Error/cancellation codes that signal a BENCHMARK ARTIFACT rather than a design
# defect. These arise from the synthetic load shape — many concurrent writes
# contending on a small seeded key space — not from anything wrong with the
# schema or access-pattern JSON:
#   TransactionConflict       — two in-flight transactions touched the same item
#                               (the benchmark reuses ~seed_items_per_table keys;
#                               real unique IDs don't collide).
#   ConditionalCheckFailed*   — a conditional write's guard fired because the item
#                               already exists / changed — expected when the
#                               benchmark rewrites a bounded key pool.
# Everything else above the error threshold (ValidationException,
# ResourceNotFoundException, AccessDeniedException, ...) is treated as a genuine
# STRUCTURAL defect the design/JSON must fix.
#
# This list is intentionally small and conservative: a code NOT listed here is
# classified "structural" (the fail-safe direction — we'd rather over-flag a
# real defect than downplay one as a benign artifact). If AWS ever surfaces
# another pure-contention / condition cancellation code that a benchmark's small
# key space can provoke, add it here.
ARTIFACT_ERROR_CODES = frozenset(
    {
        "TransactionConflict",
        "ConditionalCheckFailed",
        "ConditionalCheckFailedException",
    }
)


def _is_artifact_code(code: str) -> bool:
    return code in ARTIFACT_ERROR_CODES


def _classify_error_codes(error_codes: dict, cancellation_reason_codes: dict):
    """Return (kind, dominant_code, reason_histogram).

    kind is "artifact" when the dominant failure is contention/condition (a
    benchmark-key-space artifact) or "structural" otherwise. For a
    TransactionCanceledException the per-item cancellation reasons (when the
    Lambda captured them) are authoritative — they say WHY it cancelled — so
    they drive the classification; otherwise the top-level error code does.
    `reason_histogram` is the cancellation-reason map when present, else {}.
    """
    reasons = cancellation_reason_codes or {}
    if reasons:
        dominant = max(reasons, key=lambda k: reasons[k])
        kind = "artifact" if all(_is_artifact_code(c) for c in reasons) else "structural"
        return kind, dominant, dict(reasons)
    codes = error_codes or {}
    if not codes:
        return "structural", "unknown", {}
    dominant = max(codes, key=lambda k: codes[k])
    # Treat as artifact only when EVERY observed code is an artifact code — a
    # mix that includes a real ValidationException stays structural.
    kind = "artifact" if all(_is_artifact_code(c) for c in codes) else "structural"
    return kind, dominant, {}


def _load_json(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(2)
    with path.open() as f:
        return json.load(f)


def _fmt_delta(obs: float, exp: float) -> str:
    if exp == 0:
        return "—"
    return f"{((obs - exp) / exp) * 100:+.1f}%"


def _fmt_money(v: float) -> str:
    if v is None:
        return "—"
    if v >= 100:
        return f"${v:,.0f}"
    return f"${v:,.2f}"


def _fmt_ms(v) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}"


def _hot_cold_ratio(r: dict):
    """Hot-partition p99 ÷ cold-partition p99 for a row, or None if unknown.

    Used to tell a genuine hot-partition effect (hot p99 ≫ cold p99) from
    uniform capacity starvation (hot p99 ≈ cold p99). Returns None when the
    distribution wasn't captured (uniform/quick/standard runs) or cold p99 is
    zero/missing — callers treat None as "cannot confirm skew".
    """
    kd = r.get("key_distribution") or {}
    hot = kd.get("hot_partition_p99_ms")
    cold = kd.get("cold_partition_p99_ms")
    if hot is None or cold is None or cold <= 0:
        return None
    return hot / cold


# ---------------------------------------------------------------------------
# Per-pattern merge — observed vs expected
# ---------------------------------------------------------------------------


def _merge_rows(model: dict, summary: dict) -> list[dict]:
    tables = model.get("tables", [])
    table_map = {t["table_name"]: t for t in tables}
    entity_attr_sizes = cc._build_entity_attr_sizes(tables)
    ap_map = {ap["pattern_id"]: ap for ap in model.get("access_patterns", [])}

    rows = []
    for p in summary.get("patterns", []):
        pid = p["pattern_id"]
        ap = ap_map.get(pid)
        if not ap:
            continue
        td = table_map.get(ap.get("table", ""))
        pc = cc.pattern_monthly_cost(ap, td, entity_attr_sizes)
        cap = pc["cap"]

        # Expected capacity per call = cap["rcus"] + cap["wcus"] (mutually exclusive).
        expected_cu = cap["rcus"] + cap["wcus"]
        observed_cu = p["steady_state"]["mean_observed_cu"]

        declared_rps = ap["peak_rps"]
        # Extrapolation uses pricing constants + declared peak.
        unit_price = cc.WRU_PRICE if ap["operation"] in cc.WRITE_OPS else cc.RRU_PRICE
        extrapolated = observed_cu * declared_rps * cc.SECONDS_PER_MONTH * unit_price
        expected_monthly = pc["total_cost"]

        delta_pct = None
        if expected_cu > 0:
            delta_pct = (observed_cu - expected_cu) / expected_cu
        rows.append(
            {
                "pattern_id": pid,
                "op": ap["operation"],
                "table": ap["table"],
                "index": ap.get("index"),
                "table_index": (f"{ap['table']}/{ap['index']}" if ap.get("index") else ap["table"]),
                "declared_peak_rps": declared_rps,
                "bench_rps": p["bench_rps"],
                "observed_cu": observed_cu,
                "expected_cu": expected_cu,
                "delta_pct": delta_pct,
                "p50_ms": p["steady_state"]["p50_ms"],
                "p95_ms": p["steady_state"]["p95_ms"],
                "p99_ms": p["steady_state"]["p99_ms"],
                "throttles": p["steady_state"]["throttles"],
                "errors": p["steady_state"].get("errors", 0),
                "error_rate": p["steady_state"].get("error_rate", 0.0),
                "error_codes": p["steady_state"].get("error_codes") or {},
                "cancellation_reason_codes": p["steady_state"].get("cancellation_reason_codes")
                or {},
                "call_count": p["steady_state"]["call_count"],
                "key_distribution": p["steady_state"].get("key_distribution"),
                "extrapolated_monthly": extrapolated,
                "expected_monthly": expected_monthly,
                "amplification_ratio": p["steady_state"]["amplification_ratio"],
                "gsi_cu_by_index": p["steady_state"]["gsi_cu_by_index"],
                "cold_start": p["cold_start"],
                "measurement_tainted": p.get("measurement_tainted", False),
                "consistency": ap.get("consistency", "eventual"),
                "items_per_request": ap.get("items_per_request", 1),
                "estimated_item_size_bytes": ap.get("estimated_item_size_bytes", 1024),
                "attributes_written": ap.get("attributes_written") or [],
                "conditional_fail_rate": ap.get("conditional_fail_rate", 0.0),
                "projection_type": None,
                "ap": ap,
                "td": td,
            }
        )

    return rows


# ---------------------------------------------------------------------------
# Design signal extraction
# ---------------------------------------------------------------------------


def _extract_signals(rows: list[dict]) -> dict:
    total_monthly = sum((r["extrapolated_monthly"] or 0.0) for r in rows)

    dominant: list[dict] = []
    if total_monthly > 0:
        for r in rows:
            share = (r["extrapolated_monthly"] or 0.0) / total_monthly
            if share > 0.20:
                dominant.append(
                    {
                        "pattern_id": r["pattern_id"],
                        "monthly": r["extrapolated_monthly"],
                        "share": share,
                        # op/consistency drive axiom selection in _classify_findings —
                        # a transactional write's cost driver (Mechanics #18 2×) is
                        # nothing like an analytical read's (move-off-DDB / projection).
                        "op": r["op"],
                        "consistency": r.get("consistency", "eventual"),
                        # Does any LIVE signal corroborate treating this as high-sev?
                        # Cost share alone is load-invariant (already in cost_report).
                        "throttles": r.get("throttles", 0),
                        "delta_pct": r.get("delta_pct"),
                    }
                )
    dominant.sort(key=lambda x: -x["share"])

    persistent_throttles = [
        {"pattern_id": r["pattern_id"], "throttles": r["throttles"]}
        for r in rows
        if r["throttles"] > 0 and not r["measurement_tainted"]
    ]

    high_amp: list[dict] = []
    for r in rows:
        td = r["td"] or {}
        if r["op"] not in cc.WRITE_OPS or not td.get("gsis"):
            continue
        obs_amp = r["amplification_ratio"]
        for g in td["gsis"]:
            proj = (g.get("projection") or {}).get("type", "ALL").upper()
            implied = {"ALL": 1.0, "INCLUDE": 0.3, "KEYS_ONLY": 0.1}.get(proj, 1.0)
            if obs_amp > implied * 1.15 and obs_amp > 0.01:
                high_amp.append(
                    {
                        "pattern_id": r["pattern_id"],
                        "gsi_name": g["index_name"],
                        "projection": proj,
                        "observed_amp": obs_amp,
                        "projection_implied_amp": implied,
                    }
                )

    # Strong-read overhead: flag a strong-consistency read only if its share
    # of the total monthly bill is meaningful AND at least one cheaper
    # alternative exists (eventual read on the same aggregate). Without that
    # comparison, a strong read isn't inherently a design flaw — it's only a
    # finding when the added cost is non-trivial. Threshold: >10% of total
    # monthly.
    strong_reads: list[dict] = []
    for r in rows:
        if r["op"] not in cc.READ_OPS or r["consistency"] != "strong":
            continue
        share = (r["extrapolated_monthly"] or 0.0) / total_monthly if total_monthly > 0 else 0.0
        if share > 0.10:
            strong_reads.append(
                {
                    "pattern_id": r["pattern_id"],
                    "extrapolated_monthly": r["extrapolated_monthly"],
                    "share": share,
                }
            )

    page_cap_hits: list[dict] = []
    for r in rows:
        if r["op"] == "Query":
            approx_bytes = r["items_per_request"] * r["estimated_item_size_bytes"]
            if approx_bytes >= PAGE_CAP_BYTES * 0.9:
                page_cap_hits.append(
                    {
                        "pattern_id": r["pattern_id"],
                        "approx_page_bytes": approx_bytes,
                    }
                )

    cold_elevated = [
        {
            "pattern_id": r["pattern_id"],
            "warmup_p99": r["cold_start"]["warmup_p99_ms"],
            "steady_p99": r["p99_ms"],
        }
        for r in rows
        if r["cold_start"].get("cold_start_elevated")
    ]

    # Key skew → hot-partition risk (Mechanics #3). Fires when a pattern's
    # measured key distribution is materially uneven (stddev/mean > 0.5, the
    # threshold documented in performance-report-format.md) AND the hot
    # partition shows distress — EITHER throttles OR materially elevated tail
    # latency relative to the design's other patterns. The latency arm matters
    # because on **on-demand** tables (the skill's default) adaptive capacity
    # isolates a single hot key and absorbs it as LATENCY rather than throttles:
    # a throttle-only test would never warn on the most common configuration.
    # Throttles remain the stronger signal (provisioned tables, or load beyond
    # what adaptive capacity can split). Only representative/zipf runs carry
    # key_distribution; uniform runs omit it so this never fires spuriously.
    key_skew: list[dict] = []
    for r in rows:
        kd = r.get("key_distribution")
        if not kd:
            continue
        if kd.get("stddev_over_mean", 0.0) <= 0.5:
            continue
        # Baseline-free hot-partition latency check: the hottest partition's p99
        # vs the cold partitions' p99, WITHIN this pattern. > 1.8× means the hot
        # key is materially slower than its peers — a hot partition by
        # definition, independent of any other pattern or absolute threshold.
        hot_p99 = kd.get("hot_partition_p99_ms")
        cold_p99 = kd.get("cold_partition_p99_ms")
        elevated_latency = (
            hot_p99 is not None
            and cold_p99 is not None
            and cold_p99 > 0
            and hot_p99 > 1.8 * cold_p99
        )
        if r["throttles"] > 0 or elevated_latency:
            key_skew.append(
                {
                    "pattern_id": r["pattern_id"],
                    "stddev_over_mean": kd["stddev_over_mean"],
                    "top_key_share": kd.get("top_key_share"),
                    "throttles": r["throttles"],
                    "hot_partition_p99_ms": hot_p99,
                    "cold_partition_p99_ms": cold_p99,
                    "evidence_kind": ("throttles" if r["throttles"] > 0 else "elevated_latency"),
                }
            )

    # High non-throttle error rate → the pattern is structurally broken, not
    # mispriced. This MUST be detected before large_delta below, because a
    # 100%-error pattern has observed_cu == 0 and would otherwise be misread as a
    # benign "observed << expected" delta ("RPS/item-size off") — exactly the
    # silent-failure mode the real-AWS run exposed (a Query on a missing GSI, a
    # duplicate-key batch, an undefined GSI attr all exit 0 with errors recorded
    # but never surfaced). error_rate/error_codes come from the Lambda's exact
    # (uncapped) non-throttle tally via benchmark_model._aggregate.
    high_error: list[dict] = []
    error_pids: set = set()
    for r in rows:
        if r.get("error_rate", 0.0) >= ERROR_RATE_HIGH and r["call_count"] > 0:
            error_pids.add(r["pattern_id"])
            codes = r.get("error_codes") or {}
            reasons = r.get("cancellation_reason_codes") or {}
            top_code = max(codes, key=lambda k: codes[k]) if codes else "unknown"
            # Distinguish a benchmark artifact (contention on the small seeded
            # key space) from a genuine structural defect, using the per-item
            # cancellation reasons when the Lambda captured them.
            kind, dom_code, reason_hist = _classify_error_codes(codes, reasons)
            high_error.append(
                {
                    "pattern_id": r["pattern_id"],
                    "error_rate": r["error_rate"],
                    "errors": r["errors"],
                    "call_count": r["call_count"],
                    "top_error_code": top_code,
                    "error_codes": codes,
                    "error_kind": kind,  # "artifact" | "structural"
                    "dominant_code": dom_code,
                    "cancellation_reason_codes": reason_hist,
                }
            )

    # Low-but-nonzero error rate (below the structural threshold): surface as a
    # note so transient/partial failures aren't completely invisible either.
    minor_error: list[dict] = []
    for r in rows:
        if r["pattern_id"] not in error_pids and r.get("errors", 0) > 0:
            codes = r.get("error_codes") or {}
            top_code = max(codes, key=lambda k: codes[k]) if codes else "unknown"
            minor_error.append(
                {
                    "pattern_id": r["pattern_id"],
                    "error_rate": r.get("error_rate", 0.0),
                    "errors": r["errors"],
                    "call_count": r["call_count"],
                    "top_error_code": top_code,
                }
            )

    large_delta: list[dict] = []
    for r in rows:
        if r["delta_pct"] is None:
            continue
        # Skip patterns dominated by structural errors: their observed_cu is 0
        # because the calls FAILED, not because the inputs are mispriced. Letting
        # them fall through would emit a misleading "input-accuracy" delta finding
        # and mask the real correctness problem.
        if r["pattern_id"] in error_pids:
            continue
        # Same for throttled patterns: a throttled write reports observed_cu well
        # below expected because most calls were REJECTED, not because the item
        # size was overstated. Labeling that "item_size_off" contradicts the
        # (correct, loud) throttle finding the Load-risk section already raised.
        # Suppress — the throttle is the story, not a cost deviation.
        if r["throttles"] > 0:
            continue
        if abs(r["delta_pct"]) > TOLERANCE:
            likely = "other"
            # Heuristics: a write with observed << expected is often an item-size
            # or conditional_fail_rate misstatement; a read with observed >>
            # expected often points at RPS being off or strong-vs-eventual drift.
            if r["op"] in cc.WRITE_OPS:
                likely = (
                    "item_size_off" if r["delta_pct"] < 0 else "conditional_fail_rate_or_projection"
                )
            else:
                likely = "RPS_or_consistency_off"
            large_delta.append(
                {
                    "pattern_id": r["pattern_id"],
                    "delta_pct": r["delta_pct"],
                    "likely_cause": likely,
                }
            )

    return {
        "dominant_cost_patterns": dominant,
        "persistent_throttles": persistent_throttles,
        "high_gsi_amplification": high_amp,
        "strong_read_overhead": strong_reads,
        "page_cap_hits": page_cap_hits,
        "cold_start_elevated_patterns": cold_elevated,
        "key_skew_patterns": key_skew,
        "high_error_rate_patterns": high_error,
        "minor_error_patterns": minor_error,
        "large_expected_observed_delta_patterns": large_delta,
    }


def _classify_findings(signals: dict) -> list[dict]:
    out = []
    counter = 1

    for d in signals["dominant_cost_patterns"]:
        op = d.get("op", "")
        consistency = d.get("consistency", "eventual")
        is_write = op in cc.WRITE_OPS
        is_txn = op == "TransactWriteItems" or (is_write and consistency == "transactional")
        # Axioms must match WHY this pattern dominates the bill:
        #  - transactional write → the 2× transaction multiplier (Mechanics #18);
        #    aggregate tightness is the lever (Mechanics #1). NOT projection
        #    (Mechanics #7) and NOT "move off DynamoDB" (Integration #8) — those
        #    are analytical-read levers and are nonsensical for an OLTP write.
        #  - plain write → aggregate tightness + mutable-GSI-key amplification.
        #  - read/scan → the original analytical triple (projection / move-off-DDB).
        if is_txn:
            axioms = ["Mechanics #18", "Mechanics #1"]
        elif is_write:
            axioms = ["Mechanics #1", "Mechanics #8"]
        else:
            axioms = ["Mechanics #1", "Mechanics #7", "Integration #8"]
        # Severity: cost SHARE alone is load-invariant (it's computed from declared
        # peak, not anything the run stressed) and is already surfaced in
        # cost_report.md. Only escalate to high when a LIVE signal corroborates a
        # real problem — throttles, or a materially-off observed-vs-expected delta.
        # Otherwise cap at medium so a clean unit-cost run doesn't manufacture a
        # high-severity finding that flips no_significant_findings / triggers the
        # iteration offer on its own.
        live_corroborated = (d.get("throttles") or 0) > 0 or (
            d.get("delta_pct") is not None and abs(d["delta_pct"]) > TOLERANCE
        )
        severity = "high" if (d["share"] > 0.4 and live_corroborated) else "medium"
        out.append(
            {
                "id": f"finding-{counter}",
                "category": "design",
                "signal": "dominant_cost_patterns",
                "pattern_ids": [d["pattern_id"]],
                "evidence": {"monthly": d["monthly"], "share": d["share"]},
                "axioms": axioms,
                "severity": severity,
            }
        )
        counter += 1

    for t in signals["persistent_throttles"]:
        out.append(
            {
                "id": f"finding-{counter}",
                "category": "design",
                "signal": "persistent_throttles",
                "pattern_ids": [t["pattern_id"]],
                "evidence": {"throttles": t["throttles"]},
                "axioms": ["Mechanics #3"],
                "severity": "high",
            }
        )
        counter += 1

    for h in signals["high_gsi_amplification"]:
        out.append(
            {
                "id": f"finding-{counter}",
                "category": "design",
                "signal": "high_gsi_amplification",
                "pattern_ids": [h["pattern_id"]],
                "evidence": {
                    "observed_amp": h["observed_amp"],
                    "projection_implied_amp": h["projection_implied_amp"],
                    "projection": h["projection"],
                    "gsi_name": h["gsi_name"],
                },
                "axioms": ["Mechanics #6", "Mechanics #7", "Mechanics #8"],
                "severity": (
                    "high" if h["observed_amp"] > 2 * h["projection_implied_amp"] else "medium"
                ),
            }
        )
        counter += 1

    for p in signals["page_cap_hits"]:
        out.append(
            {
                "id": f"finding-{counter}",
                "category": "design",
                "signal": "page_cap_hits",
                "pattern_ids": [p["pattern_id"]],
                "evidence": {"approx_page_bytes": p["approx_page_bytes"]},
                "axioms": ["Mechanics #17"],
                "severity": "medium",
            }
        )
        counter += 1

    for s in signals["strong_read_overhead"]:
        out.append(
            {
                "id": f"finding-{counter}",
                "category": "design",
                "signal": "strong_read_overhead",
                "pattern_ids": [s["pattern_id"]],
                "evidence": {
                    "extrapolated_monthly": s["extrapolated_monthly"],
                    "share": s["share"],
                },
                "axioms": ["Mechanics #15"],
                "severity": "medium",
            }
        )
        counter += 1

    for c in signals["cold_start_elevated_patterns"]:
        out.append(
            {
                "id": f"finding-{counter}",
                "category": "design",
                "signal": "cold_start_elevated_patterns",
                "pattern_ids": [c["pattern_id"]],
                "evidence": {
                    "warmup_p99": c["warmup_p99"],
                    "steady_p99": c["steady_p99"],
                },
                "axioms": ["Mechanics #19"],
                "severity": "low",
            }
        )
        counter += 1

    for k in signals["key_skew_patterns"]:
        out.append(
            {
                "id": f"finding-{counter}",
                "category": "design",
                "signal": "key_skew_patterns",
                "pattern_ids": [k["pattern_id"]],
                "evidence": {
                    "stddev_over_mean": k["stddev_over_mean"],
                    "top_key_share": k["top_key_share"],
                    "throttles": k["throttles"],
                    "hot_partition_p99_ms": k.get("hot_partition_p99_ms"),
                    "cold_partition_p99_ms": k.get("cold_partition_p99_ms"),
                    "evidence_kind": k.get("evidence_kind", "throttles"),
                },
                "axioms": ["Mechanics #3"],
                # Throttles are the stronger signal; elevated latency under skew on
                # an on-demand table is a warning, not a hard ceiling breach.
                "severity": "high" if k["throttles"] > 0 else "medium",
            }
        )
        counter += 1

    # Structural errors first — highest priority. A pattern failing most/all of
    # its calls is broken, not mispriced; this is a correctness finding the agent
    # must act on (fix the index/attr/key shape) before any cost reasoning.
    for e in signals.get("high_error_rate_patterns", []):
        is_artifact = e.get("error_kind") == "artifact"
        if is_artifact:
            reason = e.get("dominant_code", "TransactionConflict")
            interpretation = (
                f"Most calls for this pattern were rejected with `{reason}`. "
                "This is almost certainly a BENCHMARK ARTIFACT, not a design "
                "defect: the load generator drives many concurrent writes "
                "against a small synthetic key pool (`seed_items_per_table`), so "
                "the same items collide far more often than they would under real "
                "traffic with unique IDs. The cost/latency numbers from the "
                "calls that DID succeed are still representative of per-op cost. "
                "To drive this pattern to a clean error rate, raise "
                "`seed_items_per_table` well above the "
                "write RPS, or lower the driven rate — do NOT change the design "
                "on account of this error rate alone. Confirm against the "
                "real cancellation-reason histogram in the Correctness section."
            )
        else:
            interpretation = (
                "Most/all calls for this pattern FAILED (non-throttle). "
                "Observed capacity is 0 because the operation errored, not "
                "because the design is cheap. Common causes: Query/GSI names "
                "an index that does not exist on the table; an operation "
                "references an attribute the table never defines; a batch/"
                "transact request built duplicate or unseeded keys; or the "
                "Lambda role lacks the action. Fix the structural cause and "
                "re-run — the cost/latency numbers for this pattern are not "
                "meaningful until it succeeds."
            )
        out.append(
            {
                "id": f"finding-{counter}",
                "category": "correctness",
                "signal": (
                    "pattern_artifact_error_rate" if is_artifact else "pattern_high_error_rate"
                ),
                "pattern_ids": [e["pattern_id"]],
                "evidence": {
                    "error_rate": e["error_rate"],
                    "errors": e["errors"],
                    "call_count": e["call_count"],
                    "top_error_code": e["top_error_code"],
                    "error_codes": e["error_codes"],
                    "error_kind": e.get("error_kind", "structural"),
                    "cancellation_reason_codes": e.get("cancellation_reason_codes") or {},
                    "interpretation": interpretation,
                },
                "axioms": ["Mechanics #2"],
                # An artifact is a measurement caveat, not a correctness defect, so
                # it must not flip the run to "significant findings" / high severity.
                "severity": "medium" if is_artifact else "high",
            }
        )
        counter += 1

    for e in signals.get("minor_error_patterns", []):
        out.append(
            {
                "id": f"finding-{counter}",
                "category": "correctness",
                "signal": "pattern_minor_errors",
                "pattern_ids": [e["pattern_id"]],
                "evidence": {
                    "error_rate": e["error_rate"],
                    "errors": e["errors"],
                    "call_count": e["call_count"],
                    "top_error_code": e["top_error_code"],
                },
                "axioms": ["Mechanics #2"],
                "severity": "low",
            }
        )
        counter += 1

    for d in signals["large_expected_observed_delta_patterns"]:
        out.append(
            {
                "id": f"finding-{counter}",
                "category": "input-accuracy",
                "signal": "large_expected_observed_delta_patterns",
                "pattern_ids": [d["pattern_id"]],
                "evidence": {
                    "delta_pct": d["delta_pct"],
                    "likely_cause": d["likely_cause"],
                },
                "axioms": ["Mechanics #2", "Mechanics #18"],
                "severity": "medium",
            }
        )
        counter += 1

    return out


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _render_report(
    model: dict, summary: dict, rows: list[dict], signals: dict, findings: list[dict]
) -> str:
    mf = summary.get("manifest") or {}
    cfg = summary.get("config") or {}
    # benchmark_model.py surfaces the Lambda-echoed mode at the summary top-level
    # (what actually ran); fall back to the config's mode for older summaries.
    mode = summary.get("mode") or cfg.get("mode") or "standard"
    is_representative = mode == "representative"
    account = mf.get("account") or "<unknown>"
    region = mf.get("region") or "<unknown>"
    prefix = mf.get("prefix") or "<unknown>"
    run_id = mf.get("run_id") or "<unknown>"
    # Freshness markers (benchmark_model.py stamps these only after a run
    # completes). Rendered in the Deployment block so the user/agent can
    # confirm the report reflects the run they just launched, not a stale
    # summary. Absent on older summaries → rendered as "<not recorded>".
    completed_at = summary.get("benchmark_completed_at") or "<not recorded>"
    wall_seconds = summary.get("benchmark_wall_seconds")
    total_rows = summary.get("total_rows")

    total_extrapolated = sum((r["extrapolated_monthly"] or 0.0) for r in rows)
    total_expected = sum((r["expected_monthly"] or 0.0) for r in rows)
    delta = None
    if total_expected > 0:
        delta = (total_extrapolated - total_expected) / total_expected * 100

    # Crude actual-bill estimate: mean_observed_cu × number of calls × unit price.
    bench_cost = 0.0
    for r in rows:
        unit = cc.WRU_PRICE if r["op"] in cc.WRITE_OPS else cc.RRU_PRICE
        bench_cost += r["observed_cu"] * r["call_count"] * unit

    # Effective driven throughput — describe what the run ACTUALLY drove, from
    # the per-pattern bench_rps in the summary, not the nominal scale_factor
    # (which the min_rps floor can override, as it did when a small-peak design
    # got clamped to ~1 rps and "0 throttles" meant nothing). When every pattern
    # ran at the min floor, this was a unit-cost sample, not a load test — say so.
    _bench_rates = [float(r["bench_rps"]) for r in rows if r.get("bench_rps") is not None]
    _min_rps = float(cfg.get("min_rps_per_pattern", 1))
    _floor_bound = bool(_bench_rates) and all(abs(b - _min_rps) < 1e-6 for b in _bench_rates)
    if _bench_rates:
        _lo, _hi = min(_bench_rates), max(_bench_rates)
        _rate_str = (
            f"{_lo:.2g} rps/pattern"
            if abs(_hi - _lo) < 1e-6
            else f"{_lo:.2g}–{_hi:.2g} rps/pattern"
        )
    else:
        _rate_str = "unknown rate"
    if _floor_bound:
        _scale_clause = (
            f"drove {_rate_str} — the `min_rps_per_pattern` floor, BELOW the "
            f"configured scale_factor, so this is a UNIT-COST sample, not a load "
            f"test: it validates per-op cost and unloaded latency only, NOT load, "
            f"throttling, or behaviour at your declared peak"
        )
    else:
        _scale_clause = (
            f"drove {_rate_str} (a fraction of declared peak) for "
            f"{cfg.get('duration_seconds', 90)}s/pattern"
        )

    out: list[str] = []
    a = out.append

    a("# DynamoDB Live Performance Report\n")

    # Coverage banner — belt-and-suspenders for a partial/zero-coverage summary
    # (e.g. a hand-fed or interrupted run). benchmark_model already exits with a
    # warning on incomplete coverage, but the report is sometimes generated from
    # a summary directly, so surface it loudly at the very top too.
    _cov = summary.get("coverage") or {}
    _all_zero = bool(rows) and all((r.get("call_count") or 0) == 0 for r in rows)
    if _cov.get("coverage_incomplete") or _cov.get("missing_patterns") or _all_zero:
        _miss = _cov.get("missing_patterns") or []
        a(
            "> ⚠️ **INCOMPLETE COVERAGE — do not trust these numbers as a full "
            "result.** "
            + (f"Patterns with no measurement: {', '.join(_miss)}. " if _miss else "")
            + ("Every measured pattern recorded zero calls. " if _all_zero else "")
            + "The benchmark did not measure every declared pattern (a killed/"
            "backgrounded run, a seed failure, or a hand-fed summary). Re-run to "
            "completion before drawing conclusions.\n"
        )

    a(
        "> **Disclaimer:** This report measures a scaled-down benchmark that "
        f"{_scale_clause}, against real AWS resources deployed in "
        f"{account}/{region}. Capacity numbers are live observations from "
        "ReturnConsumedCapacity. Monthly-cost figures extrapolate linearly: "
        "observed per-op capacity × declared peak RPS × on-demand unit price "
        "(full public rate; rates vary by region — confirm against the AWS "
        "DynamoDB pricing page for your region). This benchmark does NOT prove the design "
        "sustains declared peak RPS — it validates per-op unit cost, latency, "
        "and GSI amplification shape. Not measured: stream consumers, TTL "
        "sweep, autoscaling, cross-region replication, long-tail bursts, any "
        "non-DDB services in the design.\n"
    )
    if is_representative:
        a(
            "> **Representative mode:** this run drove ~"
            f"{cfg.get('scale_factor', 0.15)}× declared peak with **zipf hot-key "
            "sampling** and **realistic item-collection cardinality** "
            f"({cfg.get('items_per_partition', 40)} items/partition) to surface "
            "SCALE risk — hot-partition throttling, throttle-under-load, GSI "
            "amplification at volume, and Query-at-cardinality. **Throttle and "
            "latency numbers here are load-risk signals collected under "
            "deliberate skew at bounded scale — they scale NONLINEARLY with "
            "skew and must NOT be linearly extrapolated to peak.** The cost "
            "figures above remain valid: they extrapolate per-op capacity "
            "(scale-invariant) against declared peak, not the driven bench RPS. "
            "One in-region Lambda tops out near 1,500–2,000 RPS/pattern, so this "
            "surfaces hot-partition risk at bounded cost; it does not prove "
            "sustained-peak capacity.\n"
        )

    a(
        f"**Extrapolated Monthly Cost (measurement-based): {_fmt_money(total_extrapolated)}**  *(from steady-state measurement only)*"
    )
    a(f"**Calculator Monthly Cost (expected):              {_fmt_money(total_expected)}**")
    a(
        f"**Delta:                                           {f'{delta:+.1f}%' if delta is not None else '—'}**"
    )
    a(
        f"**This benchmark consumed: ~{_fmt_money(bench_cost)} in actual AWS charges** *(seed + warmup + measurement)*\n"
    )

    a("| Source                  | Measured Monthly | Calculator | Δ% |")
    a("| ----------------------- | ---------------- | ---------- | -- |")
    a("| Storage (not measured)  | —                | —          | —  |")
    a(
        f"| Read/write requests     | {_fmt_money(total_extrapolated):<16} | {_fmt_money(total_expected):<10} | {(f'{delta:+.1f}%' if delta is not None else '—'):<2} |\n"
    )

    # Deployment.
    a("## Deployment\n")
    a(f"Account: {account}   Region: {region}   Run ID: {run_id}   ")
    a(f"Resource prefix: `{prefix}`  ")
    _window_bits = [f"completed {completed_at} UTC"]
    if wall_seconds is not None:
        _window_bits.append(f"{wall_seconds}s wall")
    if total_rows is not None:
        _window_bits.append(f"{total_rows} measured rows")
    a(f"Window: {', '.join(_window_bits)}.  ")
    a(
        f"Resources: {len(model.get('tables', []))} tables, "
        f"{sum(len(t.get('gsis') or []) for t in model.get('tables', []))} GSIs. "
        f"Manifest: created_resources.json.  "
    )
    a("Teardown: teardown.sh (run manually; the skill does NOT auto-delete).\n")

    # Storage.
    a("## Storage (not benchmarked)\n")
    a(
        "Storage is not measured in a short-window benchmark. "
        "See `cost_report.md` for the storage breakdown from the calculator.\n"
    )

    # Seed verification — how many items actually landed per table before the
    # measurement phase. A shortfall means measurements ran against the wrong
    # data shape (see the seed_shortfall correctness finding).
    sv_map = summary.get("seed_verification") or {}
    if sv_map:
        a("## Seed verification\n")
        a("| Table | Expected | Seeded (observed) | Status |")
        a("| --- | --- | --- | --- |")
        for tname, sv in sv_map.items():
            exp = sv.get("expected")
            act = sv.get("actual")
            if sv.get("passed", True):
                status = "ok (sampled to cap)" if sv.get("sampled") else "ok"
            else:
                status = "SHORTFALL" if not sv.get("sampled") else "below cap (sampled)"
            act_cell = f"{act}{'+' if sv.get('sampled') else ''}"
            a(
                f"| `{tname}` | {exp if exp is not None else '—'} | "
                f"{act_cell if act is not None else '—'} | {status} |"
            )
        a("")

    # Access Pattern Measurements.
    a("## Access Pattern Measurements\n")
    a('Steady-state only (warmup excluded). See "Cold start" below for warmup numbers.\n')
    a(
        "| Pattern | Operation | Table/Index | Peak RPS | Bench RPS | "
        "Observed RCU/WCU | Expected RCU/WCU | Δ | p50 ms | p99 ms | Throttles | Errors | Extrapolated Monthly |"
    )
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    # Driver-saturation detection (Little's Law). The benchmark drives each
    # pattern with `concurrency_per_pattern` threads sharing a connection pool.
    # The mean number of requests in flight is bench_rps × mean_latency
    # (p50, seconds). When that approaches/exceeds the thread count, requests
    # queue INSIDE the driver waiting for a worker/connection, so the measured
    # tail (p99) reflects client-side queueing, not DynamoDB. Flag those rows so
    # a reader of this report alone isn't alarmed by an inflated p99 that the
    # service didn't cause. (With the pool now sized to the concurrency this is
    # rarer, but high bench_rps × non-trivial latency can still saturate the
    # threads themselves.)
    _concurrency = int(cfg.get("concurrency_per_pattern", 32) or 32)

    def _driver_saturated(r) -> bool:
        p50 = r.get("p50_ms")
        if not p50 or not r.get("bench_rps"):
            return False
        inflight = r["bench_rps"] * (p50 / 1000.0)
        return inflight >= 0.9 * _concurrency

    saturated = [r["pattern_id"] for r in rows if _driver_saturated(r)]
    for r in rows:
        # Show errors as "N (rate%)" so a structurally broken pattern is visible
        # in the headline table, not just buried in the findings JSON. A '*'
        # marks an error rate high enough to make the cost/latency cells
        # meaningless (the calls failed).
        err_n = r.get("errors", 0)
        if err_n:
            err_cell = f"{err_n} ({r.get('error_rate', 0.0):.0%})"
            if r.get("error_rate", 0.0) >= ERROR_RATE_HIGH:
                err_cell += " *"
        else:
            err_cell = "0"
        # A '†' on p99 marks driver saturation: the latency tail is client-side
        # queueing (threads/pool), not DynamoDB.
        p99_cell = _fmt_ms(r["p99_ms"]) + (" †" if _driver_saturated(r) else "")
        a(
            "| {pid} | {op} | {ti} | {pk} | {bk:.2f} | {oc:.3f} | {ec:.3f} | {d} | {p50} | {p99} | {thr} | {er} | {mo} |".format(
                pid=r["pattern_id"],
                op=r["op"],
                ti=r["table_index"],
                pk=r["declared_peak_rps"],
                bk=r["bench_rps"],
                oc=r["observed_cu"],
                ec=r["expected_cu"],
                d=_fmt_delta(r["observed_cu"], r["expected_cu"]),
                p50=_fmt_ms(r["p50_ms"]),
                p99=p99_cell,
                thr=r["throttles"],
                er=err_cell,
                mo=_fmt_money(r["extrapolated_monthly"]),
            )
        )
    a("")
    if any(r.get("error_rate", 0.0) >= ERROR_RATE_HIGH for r in rows):
        a(
            "> `*` = this pattern errored on most/all calls (non-throttle). Its "
            "Observed RCU/WCU, latency, and Extrapolated Monthly are **not "
            "meaningful** — the operation failed. See **Correctness** below.\n"
        )
    if saturated:
        a(
            f"> `†` = **driver-saturated p99 — not a DynamoDB latency.** At the "
            f"driven rate, the in-flight request count (rps × p50) meets or "
            f"exceeds the {_concurrency} benchmark driver threads, so these "
            f"requests queue client-side waiting for a worker/connection and the "
            f"**p99 reflects the single-Lambda load generator, not the service**. "
            f"p50 is still representative; the true service tail is closer to the "
            f"p99 of the low-rate patterns. To measure an un-saturated tail at "
            f"this rate, raise `concurrency_per_pattern` or drive the pattern at a "
            f"lower rps. Affected: {', '.join(saturated)}.\n"
        )

    # Correctness — operation errors. Placed high in the report (right after the
    # measurements) so a broken run cannot be mistaken for a clean one. A pattern
    # erroring on ~all calls is EITHER a design/JSON bug (structural) OR a
    # benchmark artifact (contention on the small synthetic key space) — the two
    # are split below so a contention artifact is never narrated as "your design
    # is broken".
    high_err = signals.get("high_error_rate_patterns", [])
    minor_err = signals.get("minor_error_patterns", [])
    struct_err = [e for e in high_err if e.get("error_kind") != "artifact"]
    artifact_err = [e for e in high_err if e.get("error_kind") == "artifact"]
    if high_err or minor_err:
        a("## Correctness (operation errors)\n")

        def _err_table(entries):
            a("| Pattern | Op | Error rate | Top reason | Errors / calls |")
            a("| --- | --- | --- | --- | --- |")
            for e in entries:
                r = next((x for x in rows if x["pattern_id"] == e["pattern_id"]), None)
                op = r["op"] if r else "?"
                # Prefer the real cancellation reason over the generic
                # "TransactionCanceledException" wrapper when we captured it.
                shown = e.get("dominant_code") or e["top_error_code"]
                a(
                    f"| {e['pattern_id']} | {op} | {e['error_rate']:.0%} | "
                    f"`{shown}` | {e['errors']}/{e['call_count']} |"
                )
            a("")

        if struct_err:
            a(
                "**These patterns FAILED on most/all calls (non-throttle errors).** "
                "Their cost and latency numbers above are not meaningful until the "
                "operation succeeds. This is a structural problem in the design or "
                "the access-pattern JSON, not a capacity issue:\n"
            )
            _err_table(struct_err)
            a(
                "Likely causes by error code: `ValidationException` → a Query/GSI "
                "names an index that doesn't exist, an operation references an "
                "undefined attribute, or a batch/transact built duplicate/unseeded "
                "keys; `ResourceNotFoundException` → the pattern's table isn't in "
                "the design; `AccessDeniedException` → the benchmark role lacks the "
                "action. Fix the structural cause in `dynamodb_data_model.json` and "
                "re-run; do not interpret the cost numbers for these patterns until "
                "they succeed.\n"
            )

        if artifact_err:
            a(
                "**Benchmark artifact — NOT a design defect.** These patterns showed "
                "a high error rate, but the failures are `TransactionConflict` / "
                "condition-check rejections, which come from the benchmark driving "
                "many concurrent writes against a small synthetic key pool "
                "(`seed_items_per_table`), not from anything wrong with the schema or the "
                "access-pattern JSON. Under real traffic with unique IDs these do "
                "not occur. The successful calls' per-op cost/latency are still "
                "representative — do **not** change the design on account of this "
                "error rate:\n"
            )
            _err_table(artifact_err)
            # Render the REAL cancellation-reason histogram when the Lambda
            # captured it — so the agent narrates from data, not a guess about
            # what cancelled.
            for e in artifact_err:
                hist = e.get("cancellation_reason_codes") or {}
                if hist:
                    parts = ", ".join(
                        f"`{c}` ×{n}" for c, n in sorted(hist.items(), key=lambda kv: -kv[1])
                    )
                    a(
                        f"- {e['pattern_id']} cancellation reasons (per-item, "
                        f"observed): {parts}."
                    )
            a(
                "To drive a clean error rate, raise `seed_items_per_table` well "
                "above the write RPS for these "
                "patterns, or lower the driven rate, then re-run.\n"
            )

        if minor_err:
            a(
                "Patterns with a LOW but non-zero error rate (transient or partial "
                "— below the structural threshold, cost numbers still usable): "
                + ", ".join(
                    f"{e['pattern_id']} ({e['errors']}/{e['call_count']}, "
                    f"`{e['top_error_code']}`)"
                    for e in minor_err
                )
                + ".\n"
            )

    # Load-risk signals — representative mode only. These are the numbers that
    # do NOT appear in a 1%-scale unit-cost run: hot-partition throttling and
    # the latency/amplification observed under deliberate skew.
    if is_representative:
        a("## Load-risk signals (representative mode only)\n")
        a(
            "Collected under zipf hot-key sampling at bounded scale. **These scale "
            "nonlinearly with key skew and must not be linearly extrapolated to "
            "peak** — they characterize hot-partition and throttle RISK, not "
            "sustained-peak capacity.\n"
        )
        a("| Pattern | Throttles | p99 ms | Observed amp | Top-key share | Distinct keys |")
        a("| --- | --- | --- | --- | --- | --- |")
        for r in rows:
            kd = r.get("key_distribution") or {}
            tks = kd.get("top_key_share")
            ndk = kd.get("n_distinct_keys")
            a(
                "| {pid} | {thr} | {p99} | {amp:.2f}× | {tks} | {ndk} |".format(
                    pid=r["pattern_id"],
                    thr=r["throttles"],
                    p99=_fmt_ms(r["p99_ms"]),
                    amp=r["amplification_ratio"],
                    tks=(f"{tks:.0%}" if tks is not None else "—"),
                    ndk=(ndk if ndk is not None else "—"),
                )
            )
        a("")
        skew_pids = {k["pattern_id"] for k in signals.get("key_skew_patterns", [])}
        throttled = [r for r in rows if r["throttles"] > 0]
        lat_only = [r for r in rows if r["pattern_id"] in skew_pids and r["throttles"] == 0]
        # Skew-vs-starvation split. A throttled pattern points at a HOT PARTITION
        # only if the hot partition's p99 is materially above the cold ones'
        # (the same within-pattern differential the key_skew signal uses). When
        # hot p99 ≈ cold p99, every partition throttled UNIFORMLY — that is
        # capacity starvation (the whole table/GSI is under-provisioned for the
        # driven load), NOT key skew, and must not be attributed to the
        # partition key. Missing/zero cold p99 → can't isolate → treat as
        # not-confirmed-skew (conservative).
        throttled_skew = [
            r for r in throttled if _hot_cold_ratio(r) is not None and _hot_cold_ratio(r) >= 1.3
        ]
        throttled_starved = [r for r in throttled if r not in throttled_skew]
        if throttled_skew:
            a(
                "Patterns with steady-state throttles AND a hot partition p99 "
                "materially above the cold partitions' — a hot partition is at the "
                "per-partition ceiling (Mechanics #3, ~1000 WCU / 3000 RCU). "
                "Write-shard the partition key (hash suffix) or re-aggregate: "
                + ", ".join(r["pattern_id"] for r in throttled_skew)
                + ".\n"
            )
        if throttled_starved:
            a(
                "Patterns that throttled with hot-partition p99 ≈ cold-partition "
                "p99 — this is **uniform capacity starvation, NOT key skew**: the "
                "whole table/GSI was under-provisioned for the driven load, so "
                "every partition throttled equally. This run did **not** isolate a "
                "hot-partition effect for these — do not attribute it to the "
                "partition key. To test skew specifically, re-run with capacity set "
                "*above* uniform demand so only a genuinely hot partition throttles: "
                + ", ".join(r["pattern_id"] for r in throttled_starved)
                + ".\n"
            )
        if lat_only:
            a(
                "Patterns whose hot partition shows **elevated tail latency** (no "
                "throttles) under skew — on an on-demand table this is adaptive "
                "capacity absorbing a hot key as latency rather than rejecting it. "
                "It signals the same partition-key concentration (Mechanics #3) and "
                "the same fix (write-shard / re-aggregate); on a PROVISIONED table "
                "the identical skew would throttle. Watch: "
                + ", ".join(r["pattern_id"] for r in lat_only)
                + ".\n"
            )
        if not throttled and not lat_only:
            a(
                "No hot-partition distress (throttles or elevated tail latency) "
                "observed under skew at this scale. (Absence at bounded scale is "
                "not proof of headroom at peak; a provisioned table would throttle "
                "sooner than on-demand, which absorbs hot keys via adaptive "
                "capacity.)\n"
            )

    # Cold start.
    a("## Cold start\n")
    a(
        f"Settle window: {cfg.get('table_settle_seconds', 30)}s after CreateTable "
        "before the first measurement call. "
        f"Warmup window: {cfg.get('warmup_seconds', 10)}s per pattern, excluded "
        "from percentiles above.\n"
    )
    a("| Pattern | Warmup p50 ms | Warmup p99 ms | Steady p99 ms | Warmup throttles | Elevated? |")
    a("| --- | --- | --- | --- | --- | --- |")
    for r in rows:
        cs = r["cold_start"]
        a(
            f"| {r['pattern_id']} | {_fmt_ms(cs['warmup_p50_ms'])} | "
            f"{_fmt_ms(cs['warmup_p99_ms'])} | {_fmt_ms(r['p99_ms'])} | "
            f"{cs.get('warmup_throttles', 0)} | "
            f"{'yes' if cs.get('cold_start_elevated') else 'no'} |"
        )
    a("")
    a(
        'A pattern is flagged "Elevated" when warmup p99 > 2× steady-state p99 — '
        "a signal that callers hitting this pattern immediately after deploy will "
        "see materially worse latency than the steady-state numbers suggest.\n"
    )

    # Supporting services.
    a("## Supporting services (designed, not benchmarked)\n")
    # Detect references to non-DDB services in the design JSON. The current
    # schema has no explicit "supporting_services" block; key off any
    # table-level "streams" flag as a proxy for "consumers exist but not
    # deployed."
    streams_tables = [
        t["table_name"] for t in model.get("tables", []) if (t.get("streams") or {}).get("enabled")
    ]
    if streams_tables:
        for tn in streams_tables:
            a(
                f"- Stream on table `{tn}`: configured in design; consumers "
                "(Lambda / EventBridge Pipe / Kinesis) not deployed."
            )
    else:
        a("The design references no non-DDB services that require mention here.\n")
    a("")

    # Axiom Findings.
    a("## Axiom Findings\n")
    a("**Validated by this run**\n")
    a(
        "- Mechanics #18: RCU/WCU formulas reproduced within tolerance for patterns "
        "where `|Δ| ≤ 10%`. See Access Pattern Measurements table."
    )
    # Mechanics #15 eventual/strong 2:1 check if we have both
    a(
        "- Mechanics #15 (eventual vs strong 2:1): observed where both modes "
        "are present in the design; see per-pattern deltas."
    )
    a("")
    a("**Deviations**\n")
    # Patterns dominated by structural errors are reported under Correctness, NOT
    # here: their observed_cu is 0 because the calls FAILED, so a "-100% vs
    # calculator" line with "Likely: other" would re-introduce the misleading
    # "looks mispriced" framing the error signal exists to kill. Exclude them so
    # a broken pattern isn't double-reported as a cost deviation to investigate.
    error_pids = {e["pattern_id"] for e in signals.get("high_error_rate_patterns", [])}
    artifact_pids = {
        e["pattern_id"]
        for e in signals.get("high_error_rate_patterns", [])
        if e.get("error_kind") == "artifact"
    }
    structural_pids = error_pids - artifact_pids
    any_dev = False
    throttled_excluded = 0
    for r in rows:
        if r["pattern_id"] in error_pids:
            continue
        # Throttled patterns are excluded for the same reason as errored ones:
        # observed_cu is low because calls were REJECTED, not mispriced. They're
        # reported in the Load-risk section; a "-100%, Likely: item_size_off"
        # line here would contradict that and re-introduce the "looks mispriced"
        # framing the throttle signal exists to kill.
        if r["throttles"] > 0:
            throttled_excluded += 1
            continue
        if r["delta_pct"] is not None and abs(r["delta_pct"]) > TOLERANCE:
            likely = next(
                (
                    d["likely_cause"]
                    for d in signals["large_expected_observed_delta_patterns"]
                    if d["pattern_id"] == r["pattern_id"]
                ),
                "other",
            )
            a(
                f"- {r['pattern_id']}: observed {r['observed_cu']:.3f} vs "
                f"expected {r['expected_cu']:.3f} "
                f"(Δ {_fmt_delta(r['observed_cu'], r['expected_cu'])}). Likely: {likely}."
            )
            any_dev = True
    if structural_pids:
        a(
            f"- ({len(structural_pids)} pattern(s) excluded here — they FAILED "
            "most/all calls and are reported under **Correctness** above, not as "
            "cost deviations.)"
        )
    if artifact_pids:
        a(
            f"- ({len(artifact_pids)} pattern(s) excluded here — their high error "
            "rate is a benchmark artifact (contention on the synthetic key space), "
            "not a cost or design issue; see **Correctness** above.)"
        )
    if throttled_excluded:
        a(
            f"- ({throttled_excluded} pattern(s) excluded here — they THROTTLED and "
            "are reported under **Load-risk signals** above, not as cost "
            "deviations.)"
        )
    if not any_dev:
        a("- None: every pattern within ±10% of calculator prediction.")
    a("")
    a("**Not validated by this run**\n")
    if is_representative:
        a(
            "- Mechanics #3 (per-partition ceilings 1000 WCU / 3000 RCU): "
            "PROBED under zipf skew at bounded scale — see Load-risk signals. "
            "Throttles indicate a hot partition near its ceiling ONLY when the hot "
            "partition's p99 is materially above the cold partitions'; throttles "
            "with hot p99 ≈ cold p99 are uniform capacity starvation, not skew, and "
            "do not isolate a hot-partition effect. Absence of throttles is not "
            "proof of headroom at full peak."
        )
    else:
        a(
            "- Mechanics #3 (per-partition ceilings 1000 WCU / 3000 RCU): bench did not push to ceilings by design."
        )
    a("- Mechanics #12 (TTL eventual delete): sweep cadence is hours; short window cannot observe.")
    a(
        "- Data Modeling #3, #5 (Streams/PITR/recovery granularity): configuration-level, not traffic-observable."
    )
    a("- Data Modeling #13 (Global Tables LWW / MRSC): single-region deploy.")
    a("- Patterns #1 (idempotency middleware): application layer, not DDB alone.")
    a("- Integration #1 (consumer idempotency): consumers not deployed.\n")

    # Cost-estimate validation.
    a("## Cost-estimate validation\n")
    if any_dev:
        a(
            "See **Deviations** above: at least one pattern diverges from the "
            "calculator by more than 10%. Investigate per-pattern as called out.\n"
        )
    elif structural_pids:
        a(
            "Cost validation is INCONCLUSIVE for "
            f"{len(structural_pids)} pattern(s) that errored on most/all calls — "
            "their observed capacity is 0 because the operation failed, not because "
            "the design is cheap (see **Correctness** above). Fix those patterns "
            "and re-run before trusting their cost numbers. The patterns that DID "
            "succeed reproduce the calculator within tolerance.\n"
        )
    elif artifact_pids:
        a(
            "Cost numbers are trustworthy. "
            f"{len(artifact_pids)} pattern(s) showed a high error rate, but it is a "
            "benchmark artifact (key-space contention, see **Correctness** above), "
            "not a design issue — the successful calls reproduce the calculator "
            "within tolerance.\n"
        )
    else:
        a(
            "Calculator unit-cost formulas reproduce live DynamoDB billing within "
            "tolerance for this design; any remaining cost risk lies in the RPS / "
            "item-size assumptions fed to the calculator.\n"
        )

    # Cost-concentration caveat (P2.6): when one pattern dominates the bill, the
    # headline is only as accurate as that pattern's item-size/RPS inputs — carry
    # the fragility note from the calculator into the live report so the two
    # artifacts agree.
    dom = signals.get("dominant_cost_patterns") or []
    if dom:
        top = dom[0]
        dom_row = next((r for r in rows if r["pattern_id"] == top["pattern_id"]), None)
        delta_bit = ""
        if dom_row and dom_row.get("delta_pct") is not None:
            delta_bit = f" (its observed vs expected Δ here is " f"{dom_row['delta_pct']:+.0%})"
        a(
            f"Cost concentration: `{top['pattern_id']}` drives ~{top['share']:.0%} of "
            "the estimate, so the headline is dominated by that one pattern's "
            f"item-size and RPS inputs{delta_bit} — a misstatement there moves the "
            "whole number roughly in proportion. Validate those inputs before "
            "quoting the figure.\n"
        )

    # Design reflection — scaffolded; agent authors the subsections.
    a("## Design reflection\n")
    a(
        f"Authored by the agent from `design_findings.json` ({len(findings)} "
        "findings extracted) and the axioms.\n"
    )
    input_acc = [f for f in findings if f["category"] == "input-accuracy"]
    design_f = [f for f in findings if f["category"] == "design"]
    correctness_f = [f for f in findings if f["category"] == "correctness"]

    a("### Correctness findings (fix before reading cost numbers)\n")
    if correctness_f:
        for f_ in correctness_f:
            ev = f_["evidence"]
            if f_["signal"] == "seed_shortfall":
                a(
                    f"- **seed_shortfall** on table `{ev.get('table')}`: "
                    f"severity={f_['severity']}. Seeded {ev.get('actual')} of "
                    f"{ev.get('expected')} expected items. Measurements for "
                    "patterns on this table ran against far less data than declared "
                    "(hot-key skew and item-collection cardinality are both wrong) "
                    "— fix the seed (or seed volume) and re-run before trusting any "
                    "number on this table."
                )
                continue
            pid_list = ", ".join(f_["pattern_ids"])
            a(
                f"- **{f_['signal']}** on {pid_list}: severity={f_['severity']}. "
                f"Error rate {ev.get('error_rate', 0.0):.0%}, top code "
                f"`{ev.get('top_error_code', 'unknown')}` "
                f"({ev.get('errors', '?')}/{ev.get('call_count', '?')} calls). "
                "Cost/latency for this pattern are meaningless until it succeeds — "
                "fix the structural cause in the design JSON and re-run."
            )
    else:
        a("- None — every pattern completed its calls without structural errors.")
    a("")

    a("### Input-accuracy findings (update the inputs, not the design)\n")
    if input_acc:
        for f_ in input_acc:
            pid = f_["pattern_ids"][0]
            match_row: Optional[dict] = next((x for x in rows if x["pattern_id"] == pid), None)
            if not match_row:
                continue
            a(
                f"- {pid}: observed {match_row['observed_cu']:.3f}, expected "
                f"{match_row['expected_cu']:.3f}. Likely cause: "
                f"{f_['evidence'].get('likely_cause', 'unknown')}. Proposed: "
                "update JSON and re-run calculator only."
            )
    else:
        a("- None — declared inputs reproduce observed capacity within tolerance.")
    a("")

    a("### Design findings (the structure itself is the source)\n")
    if design_f:
        for f_ in design_f:
            pid_list = ", ".join(f_["pattern_ids"])
            a(
                f"- **{f_['signal']}** on {pid_list}: severity={f_['severity']}. "
                f"Axioms: {', '.join(f_['axioms'])}. Evidence: "
                f"{json.dumps(f_['evidence'], default=str)}. "
                "See SKILL.md `## Live validation` for the axiom-indexed "
                "alternative-design menu and how to express it as a JSON diff."
            )
    else:
        a("Measurements support the current design. No alternative is argued " "for by this run.")
    a("")

    # Iteration offer — when at least one design OR correctness finding exists
    # (a structurally broken pattern needs a JSON fix + re-run just as much as a
    # design finding does).
    if design_f or correctness_f:
        a("## Iteration offer\n")
        a(
            "- **Calculator-only re-eval** — update the JSON with the proposed "
            "changes from the Design findings section above and re-run "
            "`scripts/calculate_costs.py`. No AWS calls."
        )
        a(
            "- **Full re-eval** — calculator + a second live validation against "
            "the revised design. Requires re-consenting to AWS deployment and "
            "running the prior `teardown.sh` first unless the change is "
            "additive-only (e.g. adding a GSI)."
        )
        a(
            "- **No changes** — record the decision as a deviation per Artifact "
            "#5 with your stated reason.\n"
        )

    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", required=True, help="path to dynamodb_data_model.json (the design)")
    p.add_argument(
        "--summary", required=True, help="path to perf_summary.json written by benchmark_model.py"
    )
    p.add_argument(
        "--output", required=True, help="output path for the human-facing performance_report.md"
    )
    p.add_argument(
        "--findings-out",
        default="design_findings.json",
        help="output path for the compact machine-readable findings the "
        "agent reads (default: design_findings.json)",
    )
    args = p.parse_args()

    model = _load_json(Path(args.model))
    summary = _load_json(Path(args.summary))

    rows = _merge_rows(model, summary)
    signals = _extract_signals(rows)
    findings = _classify_findings(signals)

    # Seed-shortfall finding (P1.5). verify_seed now reports a bounded-pagination
    # actual count plus a `sampled` flag. A real shortfall (passed:false AND
    # sampled:false — we counted to exhaustion, not just to the cap) means the
    # table seeded far fewer items than declared, so its measurements ran against
    # the wrong data shape: high-severity correctness. A `sampled` non-pass is
    # only "we stopped counting at the cap" and is NOT a defect.
    for tname, sv in (summary.get("seed_verification") or {}).items():
        if not sv.get("passed", True) and not sv.get("sampled", False):
            findings.append(
                {
                    "id": f"seed-{tname}",
                    "category": "correctness",
                    "signal": "seed_shortfall",
                    "pattern_ids": [],
                    "evidence": {
                        "table": tname,
                        "expected": sv.get("expected"),
                        "actual": sv.get("actual"),
                        "seed_shortfall_ratio": sv.get("seed_shortfall_ratio"),
                    },
                    "axioms": ["Mechanics #2"],
                    "severity": "high",
                }
            )

    top = sorted(rows, key=lambda r: -(r["extrapolated_monthly"] or 0.0))[:5]
    total = sum((r["extrapolated_monthly"] or 0.0) for r in rows)
    top_drivers = [
        {
            "pattern_id": r["pattern_id"],
            "monthly": r["extrapolated_monthly"],
            "share": (r["extrapolated_monthly"] or 0.0) / total if total else 0.0,
        }
        for r in top
    ]

    # "Significant" = something the agent must ACT on: any design finding, or a
    # STRUCTURAL correctness finding (a pattern failing most/all calls — the
    # high-severity pattern_high_error_rate). A 100%-error pattern is NOT a clean
    # run even with no design findings — surfacing that is the whole point of the
    # error signal added after the real-AWS run found silent 100%-error patterns.
    # A LOW-severity minor-error note (e.g. 1 transient error in 200 calls) is
    # informational AWS noise, not an action item: it stays visible in the
    # findings + report but does NOT flip the clean-run bit, so realistic
    # transient blips don't raise a false "significant finding".
    # A dominant_cost finding that did NOT reach high severity is load-invariant
    # cost concentration with no live corroboration — it's already shown in
    # cost_report.md and must not, on its own, flip the clean-run bit or trigger
    # the iteration offer on an otherwise-clean unit-cost run. Every other design
    # finding (throttles, skew, amplification, page-cap, strong-read, cold-start)
    # still counts, as does a high-severity correctness finding.
    def _is_significant(f: dict) -> bool:
        if f["signal"] == "dominant_cost_patterns":
            return f["severity"] == "high"
        if f["category"] == "design":
            return True
        return f["category"] == "correctness" and f["severity"] == "high"

    significant = [f for f in findings if _is_significant(f)]
    # Incomplete coverage (missing patterns, or a partial/zero-call run) is itself
    # a reason the run is not a clean result — surface it as a flag the agent
    # reads and let it flip the clean-run bit so a half-finished benchmark never
    # reports "no significant findings".
    cov = summary.get("coverage") or {}
    coverage_incomplete = bool(cov.get("coverage_incomplete") or cov.get("missing_patterns"))
    no_significant = (not significant) and (not coverage_incomplete)

    findings_payload = {
        "classified_findings": findings,
        "top_cost_drivers": top_drivers,
        "no_significant_findings": no_significant,
        "coverage_incomplete": coverage_incomplete,
    }

    report_md = _render_report(model, summary, rows, signals, findings)
    Path(args.output).write_text(report_md)
    Path(args.findings_out).write_text(json.dumps(findings_payload, indent=2, default=str))
    print(f"Report: {args.output}")
    print(f"Findings: {args.findings_out}")
    print(
        f"Analyzed {len(rows)} patterns, extracted {len(findings)} findings "
        f"({'clean' if no_significant else 'has design findings'})."
    )


if __name__ == "__main__":
    main()
