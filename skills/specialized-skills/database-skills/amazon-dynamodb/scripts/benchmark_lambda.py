"""Benchmark Lambda handler: runs settle/seed/warmup/measure phases against deployed DDB resources.

Invoked by scripts/benchmark_model.py. Single file, stdlib + boto3 only.
Every DynamoDB data-path call sets ReturnConsumedCapacity='TOTAL' and is
timed with time.monotonic() so latency numbers reflect service + SDK
overhead inside the same-region Lambda — not the user's local network.

Event schema (from the orchestrator):

    {
      "phase_plan": ["settle","seed","warmup","measure"] | ["measure"],
      "invocation_index": 0,           # 0 for the first call, then 1, 2, ...
      "invocations_total": 1,          # how many invocations for this run
      "patterns": [ <access_pattern>, ... ],  # from design JSON
      "tables":   [ <table_def>, ... ],       # from design JSON (includes key_schema)
      "manifest": { deploy_model.py output — tables[].name (prefixed) },
      "config": { ...benchmark_config.json knobs... }
    }

Response schema:

    {
      "invocation_index": 0,
      "phases_run": ["settle","seed","warmup","measure"],
      "raw_rows": [ {pattern_id, op, phase, ts, latency_ms, consumed_cu,
                     gsi_cu, throttled, error}, ... ],
      "seed_verification": { table: {expected, actual}, ... },
      "coverage": { "measured_patterns": [...], "missing_patterns": [...],
                    "coverage_incomplete": bool },
      "measurement_tainted": { pattern_id: "warmup"|"ramp"|... },
      "lambda_duration_seconds": float
    }

Raw-row payload is kept under the 6MB Lambda response limit by capping rows
per invocation; when measurement spans multiple invocations the orchestrator
concatenates across responses.
"""

from __future__ import annotations

import bisect
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

READ_OPS = {"GetItem", "Query", "Scan", "BatchGetItem", "TransactGetItems"}
WRITE_OPS = {"PutItem", "UpdateItem", "DeleteItem", "BatchWriteItem", "TransactWriteItems"}
THROTTLE_CODES = (
    "ProvisionedThroughputExceededException",
    "ThrottlingException",
    "RequestLimitExceeded",
)

# Keep Lambda response under the 6MB payload limit. Each row is roughly
# 200-300 bytes JSON-encoded; 15k leaves headroom for gsi_cu dicts and errors.
# This is the HARD payload safety bound — the sum of PHASE_ROW_BUDGET below is
# kept at or under it so the per-phase reservation never exceeds the payload.
MAX_ROWS_PER_INVOCATION = 15_000

# Per-PHASE row budget. A single shared global cap is wrong: warmup runs for
# EVERY pattern before any measure row is recorded, so on a multi-pattern run
# that fits in one invocation, warmup fills the whole 15k budget and `measure`
# gets ZERO latency rows — the p50/p99 columns (and the hot-vs-cold p99 signal
# that drives key_skew on on-demand tables) come back empty. Reserving a fixed
# budget per phase guarantees `measure` always keeps its allocation no matter
# how many warmup rows were produced. settle/seed are tiny in practice; the bulk
# goes to measure. The four budgets sum to MAX_ROWS_PER_INVOCATION so the hard
# payload bound still holds. Exact call/throttle COUNTS are tracked separately
# (uncapped) in run_pattern_window, so down-sampling recorded ROWS only thins the
# latency percentiles, never the throttle tally.
PHASE_ROW_BUDGET = {
    "settle": 500,
    "seed": 1_500,
    "warmup": 4_000,
    "measure": 9_000,
}
# Floor for the per-(pattern, phase) sub-cap so a design with many patterns
# still records a usable per-pattern latency sample.
MIN_ROWS_PER_PATTERN_PHASE = 200

# Seeded-key namespace is deterministic per pattern so a second invocation
# can resume without a shared manifest.
#
# Key VALUES must match the key attribute's declared DDB type. A string key gets
# the readable "bench#<pattern>#pk<idx>" form. A NUMERIC key (type "N") cannot
# carry a string prefix, so we encode the pattern + role + index into a single
# deterministic integer: a per-(pattern,role) "bank" offset (hash of the label,
# kept well inside JS/DDB safe-integer range) plus the index. Distinct patterns,
# distinct roles (pk vs sk), and distinct indices therefore never collide — the
# same uniqueness guarantee the string form gives, which the batch/transact
# distinct-key walk depends on. A binary key ("B") gets the UTF-8 bytes of the
# string form. Unknown/defaulted type is "S" (historical behavior).
# Indices per (pattern,role) numeric "bank". Cross-bank disjointness — and thus
# the collision-freedom the batch/transact distinct-key walk relies on — holds
# as long as the per-bank index stays below this stride. Seed indices are
# bounded by seed_items_per_table (default 500; thousands at most), so the 10M
# headroom is never approached in practice.
_NUM_BANK_STRIDE = 10_000_000


def _bank_offset(pattern_id: str, role: str) -> int:
    # Stable, process-independent offset in [0, ~9e15) — comfortably within DDB's
    # 38-digit number range and JS safe-int (2^53) so no precision is lost.
    h = 0
    for ch in f"{pattern_id}#{role}":
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return (h % 900_000_000) * _NUM_BANK_STRIDE


def _seed_key_val(pattern_id: str, idx: int, role: str, ktype: str):
    """Deterministic, type-correct, collision-free key value.

    role is "pk" or "sk"; ktype is the declared DDB type ("S"/"N"/"B")."""
    if ktype == "N":
        return _bank_offset(pattern_id, role) + idx
    s = f"bench#{pattern_id}#{role}{idx:06d}"
    if ktype == "B":
        return s.encode("utf-8")
    return s


# GSI synthetic key value — type-aware, and IDENTICAL between the seed side and
# the query side so a GSI Query finds the items the seed wrote. role is "pk"/"sk".
def _gsi_val(pattern_id: str, idx: int, role: str, ktype: str):
    if ktype == "N":
        return _bank_offset(f"gsi#{pattern_id}", role) + idx
    s = f"bench#gsi-{role}#{pattern_id}#{idx}"
    if ktype == "B":
        return s.encode("utf-8")
    return s


# Back-compat string generators (retained for any remaining string-only callers).
def _seed_pk(pattern_id: str, idx: int) -> str:
    return f"bench#{pattern_id}#pk{idx:06d}"


def _seed_sk(pattern_id: str, idx: int) -> str:
    return f"bench#{pattern_id}#sk{idx:06d}"


# ---------------------------------------------------------------------------
# DDB type helpers (low-level client uses type-annotated JSON)
# ---------------------------------------------------------------------------


def _serialize(value):
    """Minimal DDB low-level serializer for strings/numbers/bytes/bool/null."""
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, (int, float)):
        return {"N": str(value)}
    if value is None:
        return {"NULL": True}
    if isinstance(value, bytes):
        return {"B": value}
    raise ValueError(f"unsupported attribute type for {value!r}")


def _build_item(pk_attr, pk_val, sk_attr, sk_val, target_size_bytes, gsi_attrs=None, extra=None):
    """Build a DDB item padded to target_size_bytes using a blob attribute."""
    item = {pk_attr: _serialize(pk_val)}
    if sk_attr and sk_val is not None:
        item[sk_attr] = _serialize(sk_val)
    for name, val in (gsi_attrs or {}).items():
        item[name] = _serialize(val)
    for name, val in (extra or {}).items():
        item[name] = _serialize(val)

    # Pad using a single "payload" String attribute. Account for the small
    # attribute-name overhead; target is approximate.
    def _size(it):
        # Rough: attribute-name + value-bytes for each attribute. Only S/N/B
        # values contribute value-bytes here; BOOL/NULL count as their key length
        # only. That under-counts an item that leads with a bool/null attr by a
        # few bytes, which just makes the payload pad VERY slightly larger — never
        # smaller — so the item still meets target_size_bytes. Bench items are
        # dominated by the padded "payload" blob, so this approximation is fine.
        return sum(
            len(k) + (len(v.get("S", "") or v.get("N", "") or v.get("B", b"") or ""))
            for k, v in it.items()
        )

    current = _size(item)
    if target_size_bytes and current < target_size_bytes:
        pad_len = max(1, target_size_bytes - current - len("payload"))
        item["payload"] = {"S": "x" * pad_len}
    return item


# ---------------------------------------------------------------------------
# Context: resolves table specs, attribute names, prefixed table names
# ---------------------------------------------------------------------------


class RunContext:
    def __init__(self, event, client):
        self.cfg = event.get("config") or {}
        self.patterns = event.get("patterns") or []
        self.tables = event.get("tables") or []
        self.manifest = event.get("manifest") or {}
        self.client = client
        self.phase_plan = event.get("phase_plan") or ["settle", "seed", "warmup", "measure"]
        self.invocation_index = int(event.get("invocation_index", 0))
        self.invocations_total = int(event.get("invocations_total", 1))
        self.run_id = self.manifest.get("run_id") or "unknown"

        # Map original table name -> prefixed table name.
        self.prefixed = {}
        for t in self.manifest.get("tables") or []:
            orig = t.get("original_name") or t["name"]
            self.prefixed[orig] = t["name"]

        # Map table name -> table def (with key_schema, gsis, entities).
        self.table_by_name = {t["table_name"]: t for t in self.tables}

        # Map (table_name, attribute_name) -> declared DDB scalar type ("S"/"N"/
        # "B"). Key generation MUST honor this: a key attribute declared "N"
        # (e.g. a numeric `recorded_at` or epoch `order_date` sort key) rejects a
        # string value with ValidationException, so the seed/read/write key value
        # has to match the declared type. Defaults to "S" when a type isn't
        # declared (the common case and the historical behavior), so string-keyed
        # designs are unaffected.
        #
        # Types are read from TWO sources, in increasing precedence:
        #   1. entities[].attributes[] as {"name","type"} — the canonical schema
        #      form documented in references/cost-model-schema.md.
        #   2. a table-level "attribute_definitions" block — the raw-CreateTable
        #      -API spelling an author (or LLM) naturally reaches for. Accepts
        #      BOTH {"attribute_name","attribute_type"} (API style) and the
        #      {"name","type"} shorthand. An explicit attribute_definitions entry
        #      WINS over an entities-derived type for the same attribute.
        #
        # CRITICAL: scripts/deploy_model.py (_collect_attr_types) parses these
        # exact two sources with the same precedence. If the two ever diverge —
        # deploy creates order_date as N but this map thinks it's S — key
        # generation emits the wrong type and every write fails with
        # ValidationException (the W4 bug). Keep them in sync.
        def _norm_t(v):
            v = (v or "S").upper()
            return v if v in ("S", "N", "B") else "S"

        self.attr_types: dict[tuple, str] = {}
        for t in self.tables:
            tn = t["table_name"]
            # 1. entities[].attributes[]  (lower precedence)
            for ent in t.get("entities") or []:
                for a in ent.get("attributes") or []:
                    name = a.get("name")
                    if name:
                        self.attr_types[(tn, name)] = _norm_t(a.get("type"))
            # 2. table-level attribute_definitions  (higher precedence)
            for a in t.get("attribute_definitions") or []:
                name = a.get("attribute_name") or a.get("name")
                if name:
                    self.attr_types[(tn, name)] = _norm_t(a.get("attribute_type") or a.get("type"))

        # Seed items per table — the number written in the seed phase. This is
        # also the size of the distinct-key pool the read-key sampler draws over
        # (see n_partitions below and n_distinct_keys in _dispatch); there is no
        # separate key-space knob.
        self.seed_items = int(self.cfg.get("seed_items_per_table", 500))

        # Item-collection cardinality. items_per_partition > 1 means each
        # partition key holds a real collection of that many items (distinct
        # sort keys under a shared PK) instead of a singleton — so Query
        # patterns read realistic multi-item pages and GSI collections are
        # observable. Default 1 preserves the historical singleton behavior of
        # quick/standard modes. The number of DISTINCT partitions is therefore
        # seed_items // items_per_partition, and that partition count — not
        # seed_items — is the space the read-key sampler draws over (a Query
        # must target a partition that actually has a full collection seeded).
        self.items_per_partition = max(1, int(self.cfg.get("items_per_partition", 1)))
        self.n_partitions = max(1, self.seed_items // self.items_per_partition)

        # Read-key sampling distribution. "uniform" (default) spreads load
        # evenly via round-robin; "zipf" concentrates load on a few hot
        # partitions so a single partition approaches the per-partition
        # throughput ceiling (Mechanics #3, ~1000 WCU / 3000 RCU) and
        # hot-partition throttling becomes observable.
        self.key_sampling = (self.cfg.get("read_pattern_key_sampling") or "uniform").lower()
        self.zipf_s = float(self.cfg.get("zipf_s", 1.1))
        self._zipf_cum = None  # lazily built cumulative-weight table
        self._zipf_lock = threading.Lock()

        # Measurement window sizing.
        self.duration_seconds = int(self.cfg.get("duration_seconds", 90))
        self.warmup_seconds = int(self.cfg.get("warmup_seconds", 10))
        self.ramp_seconds = int(self.cfg.get("ramp_seconds", 10))
        self.scale_factor = float(self.cfg.get("scale_factor", 0.01))
        self.min_rps = float(self.cfg.get("min_rps_per_pattern", 1))
        self.max_rps = float(self.cfg.get("max_rps_per_pattern", 50))
        # 32 worker threads per pattern. The per-pattern driver is an open-loop
        # scheduler feeding a ThreadPoolExecutor; since each call is I/O-bound (a
        # DynamoDB round trip), threads — not CPU — set the sustainable rate. At
        # ~5-20ms/call, 32 threads sustain ~1500-2000 rps/pattern, raising the
        # single-Lambda ceiling well above the old ~800-1000 (8 threads) before
        # any multi-Lambda sharding would be needed. Overridable via config.
        self.concurrency = int(self.cfg.get("concurrency_per_pattern", 32))
        self.abort_throttle = float(self.cfg.get("abort_on_throttle_rate", 0.2))
        # Non-throttle error rate that taints a pattern and stops its window. Set
        # well above the throttle threshold — a structural error (bad index/attr,
        # duplicate key, access denied) reliably fails ~100% of calls, so 0.5
        # catches a genuinely broken pattern without tripping on sporadic
        # transient errors. Overridable via config for tuning.
        self.abort_error_rate = float(self.cfg.get("abort_on_error_rate", 0.5))
        self.table_settle = int(self.cfg.get("table_settle_seconds", 30))

    def prefixed_table(self, orig: str) -> str:
        """Return the benchmark-prefixed physical table name."""
        return self.prefixed.get(orig, orig)

    def key_type(self, table_name: str, attr: str) -> str:
        """Declared DDB type ('S'/'N'/'B') of a key attribute; 'S' if unknown."""
        return self.attr_types.get((table_name, attr), "S")

    def bench_rps_for(self, pattern) -> float:
        declared = float(pattern.get("peak_rps", 0) or 0)
        scaled = declared * self.scale_factor
        return max(self.min_rps, min(self.max_rps, scaled))

    def _build_zipf_cum(self) -> list:
        """Build a cumulative-probability table for ranks 1..n_partitions with
        P(rank r) proportional to 1/r^s. Built once, under a lock, because the
        submission loop calls sampled_idx() once per request at bench RPS."""
        n = self.n_partitions
        weights = [1.0 / (r**self.zipf_s) for r in range(1, n + 1)]
        total = sum(weights)
        cum = []
        acc = 0.0
        for w in weights:
            acc += w / total
            cum.append(acc)
        cum[-1] = 1.0  # guard against float drift so bisect always lands in-range
        return cum

    def sampled_idx(self, key_counter: int) -> int:
        """Map a per-call counter to a seeded PARTITION index in [0, n_partitions).

        "uniform" → round-robin (historical behavior). "zipf" → draw a rank by
        the precomputed cumulative distribution so a few partitions absorb most
        traffic. The space is the number of distinct seeded partitions, so a
        sampled index always points at a partition that has its full collection
        seeded — never an unseeded key that would misread as empty/throttled."""
        n = self.n_partitions
        if n <= 1:
            return 0
        if self.key_sampling == "zipf":
            if self._zipf_cum is None:
                with self._zipf_lock:
                    if self._zipf_cum is None:
                        self._zipf_cum = self._build_zipf_cum()
            u = random.random()
            return bisect.bisect_left(self._zipf_cum, u)
        return key_counter % n


# ---------------------------------------------------------------------------
# Raw-row recorder (thread-safe)
# ---------------------------------------------------------------------------


class RowSink:
    def __init__(self, n_patterns: int = 1):
        self._rows: list = []
        self._lock = threading.Lock()
        self._n_patterns = max(1, int(n_patterns))
        # Per-(pattern_id, phase) recorded counts — fair-share sub-cap within a
        # phase so one busy pattern can't take the whole phase budget.
        self._per_key: dict = {}
        # Per-phase recorded counts — the primary budget so warmup can't consume
        # measure's allocation.
        self._phase_count: dict = {}
        # Per-(pattern, phase) stack of row indices that are currently
        # non-distressed (no throttle/error). Lets the distress-swap below run in
        # O(1) instead of scanning every recorded row.
        self._noncrit: dict = {}

    def _per_key_cap(self, phase: str) -> int:
        budget = PHASE_ROW_BUDGET.get(phase, 1_000)
        return max(MIN_ROWS_PER_PATTERN_PHASE, budget // self._n_patterns)

    def add(self, row):
        pid = row.get("pattern_id")
        phase = row.get("phase")
        key = (pid, phase)
        with self._lock:
            n = self._per_key.get(key, 0)
            phase_n = self._phase_count.get(phase, 0)
            phase_budget = PHASE_ROW_BUDGET.get(phase, 1_000)
            # Append only if ALL three bounds allow it: the hard payload bound,
            # this phase's reserved budget, and this pattern's fair share of it.
            if (
                len(self._rows) < MAX_ROWS_PER_INVOCATION
                and phase_n < phase_budget
                and n < self._per_key_cap(phase)
            ):
                idx = len(self._rows)
                self._rows.append(row)
                self._per_key[key] = n + 1
                self._phase_count[phase] = phase_n + 1
                if not (row.get("throttled") or row.get("error")):
                    self._noncrit.setdefault(key, []).append(idx)
                return
            # No room. A throttled/error row is diagnostically more valuable than
            # yet another success — so swap it in over an earlier NON-distressed
            # row for the same (pattern, phase). Otherwise the first N pre-throttle
            # successes monopolize the sample and p99 looks clean even when the
            # table is throttling hard. Exact call/throttle COUNTS are tracked
            # separately and are unaffected. O(1) via the per-key index stack.
            if not (row.get("throttled") or row.get("error")):
                return
            stack = self._noncrit.get(key)
            while stack:
                i = stack.pop()
                existing = self._rows[i]
                if not (existing.get("throttled") or existing.get("error")):
                    self._rows[i] = row
                    return
            # No swappable success row found — drop (sample already all-distress).

    def extend(self, rows):
        for r in rows:
            self.add(r)

    def drain(self):
        with self._lock:
            out, self._rows = self._rows, []
            self._per_key = {}
            self._phase_count = {}
            self._noncrit = {}
            return out


# ---------------------------------------------------------------------------
# Op dispatchers — each returns (consumed_cu_base, gsi_cu_by_index, latency_ms,
# throttled_bool, error_str)
# ---------------------------------------------------------------------------


def _consumed(cc_block):
    """Extract (base CU, per-GSI CU dict) from ConsumedCapacity response.

    DynamoDB's ConsumedCapacity shape:
      - CapacityUnits (top-level) = total across base + LSI + GSI
      - Table.CapacityUnits       = base table only
      - GlobalSecondaryIndexes.{name}.CapacityUnits = per-GSI
    We want base-only so amplification_ratio = sum(GSI) / base is meaningful.
    Prefer Table.CapacityUnits; fall back to top-level minus sum(GSI) if absent.
    """
    if not cc_block:
        return 0.0, {}
    gsi = {}
    for name, block in (cc_block.get("GlobalSecondaryIndexes") or {}).items():
        gsi[name] = float(block.get("CapacityUnits", 0.0) or 0.0)
    table_block = cc_block.get("Table") or {}
    if "CapacityUnits" in table_block:
        base = float(table_block.get("CapacityUnits", 0.0) or 0.0)
    else:
        top = float(cc_block.get("CapacityUnits", 0.0) or 0.0)
        base = max(0.0, top - sum(gsi.values()))
    return base, gsi


def _time_call(fn, *args, **kwargs):
    start = time.monotonic()
    try:
        resp = fn(*args, **kwargs)
        lat_ms = (time.monotonic() - start) * 1000.0
        cc_raw = resp.get("ConsumedCapacity") if isinstance(resp, dict) else None
        # BatchWriteItem / BatchGetItem return ConsumedCapacity as a list of
        # per-table dicts; single-item ops return a single dict. Normalise to
        # one dict for _consumed.
        if isinstance(cc_raw, list):
            merged: dict = {}
            for entry in cc_raw:
                for k, v in entry.items():
                    if k == "CapacityUnits":
                        merged["CapacityUnits"] = merged.get("CapacityUnits", 0.0) + float(v or 0)
                    elif k == "Table":
                        t = merged.setdefault("Table", {})
                        t["CapacityUnits"] = t.get("CapacityUnits", 0.0) + float(
                            (v or {}).get("CapacityUnits", 0) or 0
                        )
                    elif k == "GlobalSecondaryIndexes":
                        g = merged.setdefault("GlobalSecondaryIndexes", {})
                        for idx_name, idx_block in (v or {}).items():
                            g.setdefault(idx_name, {})
                            g[idx_name]["CapacityUnits"] = g[idx_name].get(
                                "CapacityUnits", 0.0
                            ) + float((idx_block or {}).get("CapacityUnits", 0) or 0)
            cc_block = merged if merged else None
        else:
            cc_block = cc_raw
        base, gsi = _consumed(cc_block)
        return {
            "latency_ms": lat_ms,
            "consumed_cu": base,
            "gsi_cu": gsi,
            "throttled": False,
            "error": None,
            "resp": resp,
        }
    except ClientError as e:
        lat_ms = (time.monotonic() - start) * 1000.0
        code = e.response.get("Error", {}).get("Code", "")
        # TransactWriteItems/TransactGetItems surface a single top-level
        # "TransactionCanceledException" whose ACTUAL per-item reasons live in
        # e.response["CancellationReasons"] (a list of {Code, Message}). The
        # top-level code alone can't tell a TransactionConflict (concurrent
        # writes to the same key — a benchmark artifact on a small seeded key
        # space) from a ConditionalCheckFailed (a guard the design relies on)
        # from a real ValidationException. Extract the distinct, non-"None"
        # reason codes so the report narrates from data instead of guessing.
        cancel_codes = [
            r.get("Code")
            for r in (e.response.get("CancellationReasons") or [])
            if r.get("Code") and r.get("Code") != "None"
        ]
        return {
            "latency_ms": lat_ms,
            "consumed_cu": 0.0,
            "gsi_cu": {},
            "throttled": code in THROTTLE_CODES,
            "error": code,
            "cancellation_reasons": cancel_codes,
            "resp": None,
        }
    except Exception as e:
        lat_ms = (time.monotonic() - start) * 1000.0
        return {
            "latency_ms": lat_ms,
            "consumed_cu": 0.0,
            "gsi_cu": {},
            "throttled": False,
            "error": type(e).__name__,
            "resp": None,
        }


def _dispatch(ctx: RunContext, pattern: dict, part_idx: int, member_counter: int):
    """Dispatch one call of the declared operation. Never substitute op types.

    `part_idx` is the seeded PARTITION index chosen by the caller via
    ctx.sampled_idx() (uniform round-robin or zipf hot-key skew) — passed in so
    the caller can record it for the key-distribution histogram. `member_counter`
    selects which collection member within the partition a point op targets.
    The result dict carries `sampled_partition` so the drain can build the
    per-pattern histogram that surfaces hot-partition skew (Mechanics #3)."""
    op = pattern["operation"]
    td = ctx.table_by_name.get(pattern["table"])
    if not td:
        return {
            "latency_ms": 0.0,
            "consumed_cu": 0.0,
            "gsi_cu": {},
            "throttled": False,
            "error": "table_not_found_in_design",
        }
    ks = td.get("key_schema") or {}
    pk_attr = ks.get("partition_key")
    sk_attr = ks.get("sort_key")
    table_name = ctx.prefixed_table(td["table_name"])
    pid = pattern["pattern_id"]
    item_size = int(pattern.get("estimated_item_size_bytes", 1024))
    items_per = int(pattern.get("items_per_request", 1))

    # Key layout mirrors run_seed: partition `pidx` holds `items_per_partition`
    # members; the global sort-key index is pidx*ipp + member. A single point op
    # targets (part_idx, member_counter % ipp); multi-key ops (batch/transact)
    # walk distinct (partition, member) pairs starting at part_idx so every key
    # they touch is one that was actually seeded.
    ipp = ctx.items_per_partition
    npar = ctx.n_partitions

    # Resolve key attribute types once so every generated key value matches the
    # declared type (a numeric key rejects a string value — the bug a "recorded_at"
    # N sort key hit). Defaults to "S".
    pk_type = ctx.key_type(td["table_name"], pk_attr or "")
    sk_type = ctx.key_type(td["table_name"], sk_attr) if sk_attr else "S"

    def _pk(idx):
        return _seed_key_val(pid, idx, "pk", pk_type)

    def _sk(idx):
        return _seed_key_val(pid, idx, "sk", sk_type)

    def _key_at(j):
        pidx = (part_idx + j) % npar
        member = ((member_counter + j) % ipp) if ipp > 1 else 0
        global_idx = pidx * ipp + member
        pkv = _pk(pidx)
        skv = _sk(global_idx) if sk_attr else None
        return pkv, skv

    # Distinct seeded-key space, matching run_seed exactly:
    #   sort-key table   -> npar partitions × ipp members = npar*ipp distinct
    #                       (pk, sk) pairs; flat index g maps pidx=g//ipp,
    #                       global_idx=g.
    #   no-sort-key table-> run_seed writes one item per partition over
    #                       ctx.seed_items partitions, so there are seed_items
    #                       distinct partition keys (member is meaningless with
    #                       no SK).
    # A flat index walked modulo this count yields ONLY distinct keys, so
    # multi-key requests can never contain a duplicate (DynamoDB rejects a whole
    # BatchGetItem/BatchWriteItem/Transact* request that lists the same key
    # twice — "Provided list of item keys contains duplicates"). This replaces
    # the old (part_idx+j)%npar walk, which wrapped onto an already-used key
    # whenever items_per_request exceeded the distinct space (the common case on
    # a no-SK table where the space is just `npar` partitions).
    n_distinct_keys = (npar * ipp) if sk_attr else ctx.seed_items

    def _key_flat(g):
        gg = g % max(1, n_distinct_keys)
        if sk_attr:
            pidx = gg // ipp
            return _pk(pidx), _sk(gg)
        return _pk(gg), None

    def _distinct_keys(n_requested, hard_max):
        """Yield (pkv, skv) for `n` DISTINCT seeded keys, starting at the hot
        partition so zipf skew is preserved. `n` is capped at the distinct
        seeded-key space (so we never duplicate) and at the op's DynamoDB limit
        (`hard_max`). Returns a list; len may be < n_requested when the seeded
        space or the API limit is smaller."""
        n = max(1, min(int(n_requested), int(hard_max), int(n_distinct_keys)))
        if sk_attr:
            start_g = (part_idx % max(1, npar)) * ipp + (member_counter % ipp)
        else:
            start_g = part_idx % max(1, n_distinct_keys)
        return [_key_flat(start_g + k) for k in range(n)]

    pk_val, sk_val = _key_at(0)
    idx = part_idx  # partition index for GSI-synthetic key derivation

    client = ctx.client

    if op == "GetItem":
        key = {pk_attr: _serialize(pk_val)}
        if sk_attr:
            key[sk_attr] = _serialize(sk_val)
        consistent = pattern.get("consistency") == "strong"
        return _time_call(
            client.get_item,
            TableName=table_name,
            Key=key,
            ConsistentRead=consistent,
            ReturnConsumedCapacity="TOTAL",
        )

    if op == "Query":
        # Query on base table OR on a GSI.
        index = pattern.get("index")
        if index:
            # Query GSI: we seeded base items with GSI PK populated. Use
            # the GSI's partition key attribute.
            gsi_def = next((g for g in td.get("gsis") or [] if g["index_name"] == index), None)
            if not gsi_def:
                return {
                    "latency_ms": 0.0,
                    "consumed_cu": 0.0,
                    "gsi_cu": {},
                    "throttled": False,
                    "error": "gsi_not_found",
                }
            g_pk = gsi_def["partition_key"]
            # If the GSI shares its PK attribute with the base table's PK or
            # SK, seeding did NOT set a synthetic gsi value (see run_seed) —
            # so query with the base PK/SK value. Otherwise use the synthetic.
            if g_pk == pk_attr:
                g_pk_val = pk_val
            elif g_pk == sk_attr:
                g_pk_val = sk_val
            else:
                # Synthetic GSI PK — seeded off the partition index (pidx==idx),
                # type-aware, IDENTICAL to run_seed's _gsi_val so the Query hits.
                g_pk_val = _gsi_val(pid, idx, "pk", ctx.key_type(td["table_name"], g_pk))
            kwargs = dict(
                TableName=table_name,
                IndexName=index,
                KeyConditionExpression="#pk = :pk",
                ExpressionAttributeNames={"#pk": g_pk},
                ExpressionAttributeValues={":pk": _serialize(g_pk_val)},
                Limit=items_per,
                ReturnConsumedCapacity="TOTAL",
            )
        else:
            kwargs = dict(
                TableName=table_name,
                KeyConditionExpression="#pk = :pk",
                ExpressionAttributeNames={"#pk": pk_attr},
                ExpressionAttributeValues={":pk": _serialize(pk_val)},
                Limit=items_per,
                ReturnConsumedCapacity="TOTAL",
            )
        return _time_call(client.query, **kwargs)

    if op == "Scan":
        # One-shot per Mechanics #16 — do not loop. Limit items to the
        # declared items_per_request to keep costs predictable.
        return _time_call(
            client.scan,
            TableName=table_name,
            Limit=max(1, items_per),
            ReturnConsumedCapacity="TOTAL",
        )

    if op == "BatchGetItem":
        # BatchGetItem caps at 100 keys per call; keys must be distinct.
        keys = []
        for bpk, bsk in _distinct_keys(items_per, hard_max=100):
            k = {pk_attr: _serialize(bpk)}
            if sk_attr:
                k[sk_attr] = _serialize(bsk)
            keys.append(k)
        return _time_call(
            client.batch_get_item,
            RequestItems={table_name: {"Keys": keys}},
            ReturnConsumedCapacity="TOTAL",
        )

    if op == "PutItem":
        item = _build_item(
            pk_attr,
            pk_val,
            sk_attr,
            sk_val,
            item_size,
            extra={"bench_ts": int(time.time())},
        )
        return _time_call(
            client.put_item,
            TableName=table_name,
            Item=item,
            ReturnConsumedCapacity="TOTAL",
        )

    if op == "UpdateItem":
        # Update a single attribute — mirrors a typical mutate-one-field call.
        key = {pk_attr: _serialize(pk_val)}
        if sk_attr:
            key[sk_attr] = _serialize(sk_val)
        return _time_call(
            client.update_item,
            TableName=table_name,
            Key=key,
            UpdateExpression="SET bench_ts = :t",
            ExpressionAttributeValues={":t": _serialize(int(time.time()))},
            ReturnConsumedCapacity="TOTAL",
        )

    if op == "DeleteItem":
        key = {pk_attr: _serialize(pk_val)}
        if sk_attr:
            key[sk_attr] = _serialize(sk_val)
        return _time_call(
            client.delete_item,
            TableName=table_name,
            Key=key,
            ReturnConsumedCapacity="TOTAL",
        )

    if op == "BatchWriteItem":
        # BatchWriteItem caps at 25 items per call; PutRequests in one call must
        # not target duplicate primary keys.
        reqs = []
        for bpk, bsk in _distinct_keys(items_per, hard_max=25):
            it = _build_item(
                pk_attr,
                bpk,
                sk_attr,
                bsk,
                item_size,
                extra={"bench_ts": int(time.time())},
            )
            reqs.append({"PutRequest": {"Item": it}})
        return _time_call(
            client.batch_write_item,
            RequestItems={table_name: reqs},
            ReturnConsumedCapacity="TOTAL",
        )

    if op == "TransactWriteItems":
        # Use declared item_sizes if present; fall back to items_per × item_size.
        # A transaction caps at 100 items and cannot operate on the SAME item
        # twice ("Transaction request cannot include multiple operations on one
        # item"), so walk DISTINCT seeded keys. The number of writes is the count
        # of declared sizes, still capped at the distinct seeded space.
        sizes = pattern.get("item_sizes") or [item_size] * max(1, items_per)
        keys = _distinct_keys(len(sizes), hard_max=100)
        tx_items = []
        for i, (bpk, bsk) in enumerate(keys):
            sz = sizes[i] if i < len(sizes) else item_size
            tx_items.append(
                {
                    "Put": {
                        "TableName": table_name,
                        "Item": _build_item(
                            pk_attr,
                            bpk,
                            sk_attr,
                            bsk,
                            sz,
                            extra={"bench_tx": int(time.time()), "i": i},
                        ),
                    }
                }
            )
        return _time_call(
            client.transact_write_items,
            TransactItems=tx_items,
            ReturnConsumedCapacity="TOTAL",
        )

    if op == "TransactGetItems":
        # TransactGetItems caps at 100 items; keys must be distinct.
        tx_items = []
        for bpk, bsk in _distinct_keys(items_per, hard_max=100):
            k = {pk_attr: _serialize(bpk)}
            if sk_attr:
                k[sk_attr] = _serialize(bsk)
            tx_items.append({"Get": {"TableName": table_name, "Key": k}})
        return _time_call(
            client.transact_get_items,
            TransactItems=tx_items,
            ReturnConsumedCapacity="TOTAL",
        )

    return {
        "latency_ms": 0.0,
        "consumed_cu": 0.0,
        "gsi_cu": {},
        "throttled": False,
        "error": f"unsupported_op:{op}",
    }


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------


def run_settle(ctx: RunContext, sink: RowSink):
    """Wait for cold-start capacity to stabilize; warm each thread's SDK."""
    if ctx.table_settle > 0:
        time.sleep(ctx.table_settle)

    def _warm(table_name):
        start = time.monotonic()
        try:
            ctx.client.describe_table(TableName=table_name)
        except ClientError:
            pass
        return (time.monotonic() - start) * 1000.0

    prefixed_names = list(ctx.prefixed.values())
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(prefixed_names)))) as pool:
        for tn in prefixed_names:
            lat = pool.submit(_warm, tn).result()
            sink.add(
                {
                    "pattern_id": "__settle__",
                    "op": "DescribeTable",
                    "phase": "settle",
                    "ts": time.time(),
                    "latency_ms": lat,
                    "consumed_cu": 0.0,
                    "gsi_cu": {},
                    "throttled": False,
                    "error": None,
                    "table": tn,
                }
            )


def _tables_in_use(ctx: RunContext) -> set[str]:
    """Every table referenced by at least one access pattern (read OR write)."""
    return {p["table"] for p in ctx.patterns if p.get("table")}


def run_seed(ctx: RunContext, sink: RowSink) -> dict:
    """Seed every table that has any access pattern. Returns per-table seed counts."""
    seed_count_per_table = {}
    patterns_by_table: dict[str, list[dict]] = {}
    for p in ctx.patterns:
        patterns_by_table.setdefault(p["table"], []).append(p)

    for orig_table in _tables_in_use(ctx):
        td = ctx.table_by_name.get(orig_table)
        if not td:
            continue
        ks = td.get("key_schema") or {}
        pk_attr = ks.get("partition_key")
        sk_attr = ks.get("sort_key")
        table_name = ctx.prefixed_table(orig_table)
        table_patterns = patterns_by_table.get(orig_table, [])

        # Determine an item size for seeds: use the largest item size declared
        # for any pattern on this table so reads against seeded items look
        # realistic.
        item_size = max(
            (int(p.get("estimated_item_size_bytes", 1024)) for p in table_patterns),
            default=1024,
        )

        # For GSI queries on this table, also populate the GSI PK/SK with a
        # predictable pattern-scoped value so the Query phase hits items.
        gsis = {g["index_name"]: g for g in (td.get("gsis") or [])}

        # Seed items per pattern that reads from this table, so every read
        # pattern has items to hit. Write-only patterns still get seeded
        # (UpdateItem/DeleteItem target pre-existing items).
        #
        # Layout: n_partitions distinct partition keys, each holding
        # items_per_partition members (distinct sort keys). The global sort-key
        # index is pidx*ipp + member — the SAME mapping _dispatch._key_at uses,
        # so a Query on partition `pidx` reads the full seeded collection and a
        # point op resolves to a real member. With items_per_partition=1 this
        # reduces to the historical one-item-per-partition behavior.
        #
        # A table with NO sort key cannot hold a collection (no second key to
        # vary), so it falls back to one item per partition regardless of ipp.
        ipp = ctx.items_per_partition if sk_attr else 1
        n_part = ctx.n_partitions if sk_attr else ctx.seed_items
        # Resolve key types so seeded primary keys match _dispatch's generated
        # keys EXACTLY (same type, same value) — otherwise a Query/GetItem would
        # look for a key the seed never wrote. Defaults to "S".
        pk_type = ctx.key_type(orig_table, pk_attr or "")
        sk_type = ctx.key_type(orig_table, sk_attr) if sk_attr else "S"
        items = []
        for p in table_patterns:
            pid = p["pattern_id"]
            idx_name = p.get("index")
            g = gsis.get(idx_name) if idx_name else None
            for pidx in range(n_part):
                for member in range(ipp):
                    global_idx = pidx * ipp + member
                    gsi_extras = {}
                    if g:
                        g_pk = g["partition_key"]
                        g_sk = g.get("sort_key")
                        # Key the GSI PK off the PARTITION (pidx), not the member,
                        # so the GSI also holds a real collection per partition —
                        # this is what makes GSI Query and GSI amplification
                        # observable at volume. Never overwrite an attribute that
                        # is the base table's own PK/SK (that would corrupt the
                        # primary key); only set distinct GSI attributes. GSI key
                        # values are type-aware too (a numeric GSI key rejects a
                        # string), matching the _dispatch Query side.
                        if g_pk != pk_attr and g_pk != sk_attr:
                            gsi_extras[g_pk] = _gsi_val(
                                pid, pidx, "pk", ctx.key_type(orig_table, g_pk)
                            )
                        if g_sk and g_sk != pk_attr and g_sk != sk_attr:
                            gsi_extras[g_sk] = _gsi_val(
                                pid, global_idx, "sk", ctx.key_type(orig_table, g_sk)
                            )
                    it = _build_item(
                        pk_attr,
                        _seed_key_val(pid, pidx, "pk", pk_type),
                        sk_attr,
                        _seed_key_val(pid, global_idx, "sk", sk_type) if sk_attr else None,
                        item_size,
                        gsi_attrs=gsi_extras,
                        extra={"bench_seed": 1},
                    )
                    items.append(it)

        # Deduplicate by primary key as a safety net. Each pattern's keys embed
        # its own pattern_id (via _seed_key_val(pid, …)), so patterns sharing a
        # table do NOT collide — this table gets ~seed_items items PER pattern, by design
        # (each pattern reads its own seeded keyspace via _dispatch._key_at). The
        # dedup only guards against an accidental intra-pattern collision; it is
        # effectively a no-op for the current key layout. (The spend estimate in
        # benchmark_model._estimate_bench_spend accounts for the per-pattern
        # volume; do not assume cross-pattern dedup shrinks it.)
        def _keyval(av):
            # The single scalar value out of a DDB attribute-value dict,
            # whatever its type tag (S/N/B) — so dedup works for numeric keys
            # too, not just strings.
            if not av:
                return None
            return next(iter(av.values()))

        seen_keys = set()
        deduped = []
        for it in items:
            key_tuple = (_keyval(it.get(pk_attr)), _keyval(it.get(sk_attr)) if sk_attr else None)
            if key_tuple in seen_keys:
                continue
            seen_keys.add(key_tuple)
            deduped.append(it)

        # Write in BatchWriteItem chunks of 25.
        written = 0
        for chunk_start in range(0, len(deduped), 25):
            chunk = deduped[chunk_start : chunk_start + 25]
            reqs = [{"PutRequest": {"Item": it}} for it in chunk]
            res = _time_call(
                ctx.client.batch_write_item,
                RequestItems={table_name: reqs},
                ReturnConsumedCapacity="TOTAL",
            )
            sink.add(
                {
                    "pattern_id": "__seed__",
                    "op": "BatchWriteItem",
                    "phase": "seed",
                    "ts": time.time(),
                    "latency_ms": res["latency_ms"],
                    "consumed_cu": res["consumed_cu"],
                    "gsi_cu": res["gsi_cu"],
                    "throttled": res["throttled"],
                    "error": res["error"],
                    "table": table_name,
                }
            )
            # Handle UnprocessedItems with bounded exponential backoff. Seeding
            # is correctness, not measurement — and now that the data-path client
            # has retries disabled (so the MEASURE phase can observe throttles),
            # seeding must do its own retry, especially against a low PROVISIONED
            # capacity where BatchWriteItem will shed items until capacity frees.
            if res.get("resp"):
                unproc = res["resp"].get("UnprocessedItems") or {}
                attempt = 0
                while unproc.get(table_name) and attempt < 8:
                    time.sleep(min(0.1 * (2**attempt), 3.0))
                    retry = _time_call(
                        ctx.client.batch_write_item,
                        RequestItems=unproc,
                        ReturnConsumedCapacity="TOTAL",
                    )
                    sink.add(
                        {
                            "pattern_id": "__seed_retry__",
                            "op": "BatchWriteItem",
                            "phase": "seed",
                            "ts": time.time(),
                            "latency_ms": retry["latency_ms"],
                            "consumed_cu": retry["consumed_cu"],
                            "gsi_cu": retry["gsi_cu"],
                            "throttled": retry["throttled"],
                            "error": retry["error"],
                            "table": table_name,
                        }
                    )
                    unproc = (retry.get("resp") or {}).get("UnprocessedItems") or {}
                    attempt += 1
            written += len(chunk)

        seed_count_per_table[table_name] = written

    return seed_count_per_table


SEED_VERIFY_CAP = 2000  # max items counted per table — bounds the verify cost


def verify_seed(ctx: RunContext, seed_counts: dict) -> dict:
    """Verify seed landed via a bounded-pagination Scan(Select=COUNT).

    DescribeTable.ItemCount is eventually consistent — updated ~every 6h — so a
    freshly-seeded table always reports 0. A Scan with Select=COUNT returns a
    ground-truth count of what landed. The OLD implementation used Limit=1, so
    `Count` capped at 1 and `passed = actual > 0` was true whenever a SINGLE
    item landed — a table that seeded 1 of 1000 items read as clean, hiding a
    massive shortfall that silently corrupts every measurement on that table.

    Now we paginate, accumulating `Count`, until we either reach the target
    (`min(expected, SEED_VERIFY_CAP)`) or exhaust the table. Cost is bounded:
    Select=COUNT bills on items examined, capped at ~SEED_VERIFY_CAP items.

    Per-table result fields:
      expected            declared seed target
      actual              items counted (≥ this many exist; '+' if we stopped at cap)
      sampled             True if we stopped at the cap before exhausting the table
      passed              expected==0, OR actual ≥ 50% of the capped target
      seed_shortfall_ratio  1 - actual/expected (0.0 when expected==0); only
                            meaningful when not `sampled`
    """
    out = {}
    for table_name, expected in seed_counts.items():
        target = min(int(expected), SEED_VERIFY_CAP) if expected else 0
        actual = 0
        sampled = False
        start_key = None
        try:
            while True:
                kwargs = {"TableName": table_name, "Select": "COUNT"}
                if start_key:
                    kwargs["ExclusiveStartKey"] = start_key
                resp = ctx.client.scan(**kwargs)
                actual += resp.get("Count", 0)
                start_key = resp.get("LastEvaluatedKey")
                if target and actual >= target:
                    # Counted enough to make the pass/fail call; stop early so a
                    # large table doesn't run up cost past the cap.
                    sampled = bool(start_key)
                    break
                if not start_key:
                    break  # exhausted the table — `actual` is exact
        except ClientError:
            actual = 0
        # Threshold against the CAPPED target, not raw expected, so a table with
        # more than SEED_VERIFY_CAP declared items isn't failed for our choosing
        # to stop counting.
        passed = expected == 0 or actual >= max(1, int(target * 0.5))
        shortfall = (1.0 - (actual / expected)) if expected else 0.0
        out[table_name] = {
            "expected": expected,
            "actual": actual,
            "sampled": sampled,
            "passed": passed,
            "seed_shortfall_ratio": round(max(0.0, shortfall), 3),
        }
    return out


def run_pattern_window(
    ctx: RunContext,
    pattern: dict,
    duration_s: float,
    phase: str,
    sink: RowSink,
    tainted: dict,
    counts: dict | None = None,
):
    """Drive one pattern at its bench RPS for duration_s seconds.

    Scheduler design: a single submission thread submits calls at the
    configured rate to a ThreadPoolExecutor. A separate drain thread pulls
    completed futures off a queue and records rows. This keeps the
    submission loop from blocking on result processing, so genuine
    concurrency matches `concurrency_per_pattern`.

    `counts`, if given, receives EXACT (uncapped) call/throttle tallies keyed by
    (pattern_id, phase). Recorded rows are per-key capped for the response
    payload, but these counts see every call — so throttle totals stay accurate
    even when the latency-percentile rows are down-sampled.
    """
    import queue

    pid = pattern["pattern_id"]
    bench_rps = ctx.bench_rps_for(pattern)
    if bench_rps <= 0:
        return

    deadline = time.monotonic() + duration_s
    interval = 1.0 / bench_rps
    ramp_deadline = time.monotonic() + ctx.ramp_seconds if phase == "measure" else deadline
    stop_flag = threading.Event()

    # Shared counters (only touched by the drain thread except stop_flag).
    # `errors`/`ramp_errors` count NON-throttle failures (a throttle is its own
    # signal, tallied separately and surfaced via the skew/taint path); a
    # non-throttle error is usually structural (ValidationException from a bad
    # index/attr/duplicate-key, AccessDenied, ResourceNotFound) and would
    # otherwise vanish — observed_cu is 0, so it can masquerade as a benign
    # expected-vs-observed delta. `error_codes` tallies the distinct codes so the
    # report can name the cause (e.g. {"ValidationException": 80}).
    stats: dict[str, Any] = {
        "calls": 0,
        "throttles": 0,
        "ramp_calls": 0,
        "ramp_throttles": 0,
        "errors": 0,
        "ramp_errors": 0,
        "error_codes": {},
        # Per-item Transact* cancellation reason histogram (e.g.
        # {"TransactionConflict": 13}). Tallied separately from error_codes
        # because the top-level code is always "TransactionCanceledException"
        # and hides whether the failures are contention (artifact) or a
        # genuine structural problem. Empty for non-transactional patterns.
        "cancellation_reason_codes": {},
    }

    # One DescribeTable on entry to warm SDK/TLS/credentials off the
    # critical path.
    try:
        ctx.client.describe_table(TableName=ctx.prefixed_table(pattern["table"]))
    except ClientError:
        pass

    pool = ThreadPoolExecutor(max_workers=ctx.concurrency)
    fut_queue: "queue.Queue" = queue.Queue()

    def _drain_worker():
        # Pulls (future, partition_idx) tuples off the queue, waits for each,
        # records the row. None sentinel means no more futures will be submitted.
        while True:
            item = fut_queue.get()
            if item is None:
                return
            fut_obj, part_idx = item
            try:
                res = fut_obj.result()
            except Exception as e:
                res = {
                    "latency_ms": 0.0,
                    "consumed_cu": 0.0,
                    "gsi_cu": {},
                    "throttled": False,
                    "error": f"drain_exc:{type(e).__name__}",
                }
            stats["calls"] += 1
            in_ramp = time.monotonic() < ramp_deadline
            if res["throttled"]:
                stats["throttles"] += 1
                if in_ramp:
                    stats["ramp_throttles"] += 1
            elif res["error"]:
                # Non-throttle failure — structural, not capacity. Count it
                # separately so it cannot hide inside a "0 observed CU" delta.
                stats["errors"] += 1
                code = res["error"]
                stats["error_codes"][code] = stats["error_codes"].get(code, 0) + 1
                # Unpack Transact* per-item cancellation reasons so the report
                # can distinguish contention (TransactionConflict) from a real
                # structural failure, instead of seeing only the generic
                # "TransactionCanceledException".
                for rc in res.get("cancellation_reasons") or []:
                    stats["cancellation_reason_codes"][rc] = (
                        stats["cancellation_reason_codes"].get(rc, 0) + 1
                    )
                if in_ramp:
                    stats["ramp_errors"] += 1
            if in_ramp:
                stats["ramp_calls"] += 1
            sink.add(
                {
                    "pattern_id": pid,
                    "op": pattern["operation"],
                    "phase": phase,
                    "ts": time.time(),
                    "latency_ms": res["latency_ms"],
                    "consumed_cu": res["consumed_cu"],
                    "gsi_cu": res["gsi_cu"],
                    "throttled": res["throttled"],
                    "error": res["error"],
                    # Partition the read/write targeted — drives the per-pattern
                    # key-distribution histogram (hot-partition skew, Mechanics #3).
                    "key_idx": part_idx,
                }
            )
            # Abort guard — active through ramp window during measurement.
            # `pid not in tainted` so a throttle burst doesn't overwrite an
            # error-rate taint already set below — the distinct reason strings
            # ("ramp:throttle_rate=" vs "error_rate=:CODE") must each survive so
            # the report can tell a throttled pattern from a structurally broken
            # one. (The downstream correctness finding keys off exact error
            # counts regardless, but the human-readable reason should be right.)
            if phase == "measure" and stats["ramp_calls"] >= 20 and pid not in tainted:
                rate = stats["ramp_throttles"] / max(1, stats["ramp_calls"])
                if rate > ctx.abort_throttle:
                    tainted[pid] = f"ramp:throttle_rate={rate:.2f}"
                    stop_flag.set()
            elif phase == "warmup" and stats["throttles"] > 0 and stats["calls"] >= 20:
                rate = stats["throttles"] / max(1, stats["calls"])
                if rate > ctx.abort_throttle:
                    # Warmup-only throttles: do NOT taint; stop warmup early.
                    stop_flag.set()
            # Error-rate guard — distinct from throttling. A high NON-throttle
            # error rate during measurement means the pattern is structurally
            # broken (bad index/attr, duplicate key, access denied), not capacity-
            # bound: its observed CU/latency are meaningless, so taint it and stop
            # burning the window. The distinct taint reason ("error_rate=") lets
            # the report tell a broken pattern apart from a throttle-tainted one
            # and raise a correctness finding instead of a benign cost delta. The
            # error tally itself flows out via exact_counts regardless of taint.
            if phase == "measure" and stats["calls"] >= 20:
                erate = stats["errors"] / max(1, stats["calls"])
                if erate > ctx.abort_error_rate and pid not in tainted:
                    top_code = max(
                        stats["error_codes"], key=stats["error_codes"].get, default="error"
                    )
                    tainted[pid] = f"error_rate={erate:.2f}:{top_code}"
                    stop_flag.set()

    drain_thread = threading.Thread(target=_drain_worker, daemon=True)
    drain_thread.start()

    try:
        next_time = time.monotonic()
        key_counter = 0
        while time.monotonic() < deadline and not stop_flag.is_set():
            now = time.monotonic()
            if now < next_time:
                time.sleep(min(0.01, next_time - now))
                continue
            next_time += interval
            # Draw the target partition here (once per call) so zipf's RNG draw
            # is counted exactly once and the drain can record which partition
            # was hit. member_counter cycles collection members within it.
            part_idx = ctx.sampled_idx(key_counter)
            fut = pool.submit(_dispatch, ctx, pattern, part_idx, key_counter)
            fut_queue.put((fut, part_idx))
            key_counter += 1
    finally:
        # Signal drain to stop after everything submitted has been processed.
        fut_queue.put(None)
        pool.shutdown(wait=True)
        drain_thread.join(timeout=30)

    # Record EXACT (uncapped) tallies for this (pattern, phase) so throttle,
    # error, and call totals survive per-key row down-sampling.
    if counts is not None:
        counts[(pid, phase)] = {
            "calls": stats["calls"],
            "throttles": stats["throttles"],
            "errors": stats["errors"],
            "error_codes": dict(stats["error_codes"]),
            "cancellation_reason_codes": dict(stats["cancellation_reason_codes"]),
        }


def run_warmup(ctx: RunContext, sink: RowSink, tainted: dict, counts: dict):
    if ctx.warmup_seconds <= 0:
        return
    # Serialize patterns so they don't compete in a tiny Lambda — but each
    # pattern uses its internal ThreadPoolExecutor so within-pattern calls
    # still overlap.
    for p in ctx.patterns:
        run_pattern_window(ctx, p, ctx.warmup_seconds, "warmup", sink, tainted, counts)


def run_measure(ctx: RunContext, sink: RowSink, tainted: dict, slice_seconds: float, counts: dict):
    for p in ctx.patterns:
        if p["pattern_id"] in tainted:
            continue
        run_pattern_window(ctx, p, slice_seconds, "measure", sink, tainted, counts)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handler(event, context):
    started = time.monotonic()
    region = (event.get("manifest") or {}).get("region") or os.environ.get(
        "AWS_REGION", "us-east-1"
    )
    cfg_block = event.get("config") or {}
    # Tight client-side timeouts so one stuck call can't eat the budget.
    #
    # CRITICAL: data-path retries are DISABLED (max_attempts=1). boto3's default
    # "standard"/"legacy" retry modes transparently re-issue throttled requests
    # (ProvisionedThroughputExceeded / ThrottlingException) and only surface the
    # eventual success — which would make a load benchmark whose entire job is to
    # OBSERVE throttling report zero throttles even when the table is throttling
    # hard. We want each throttle counted once, not retried away. The orchestrator
    # already disables retries on the Lambda invoke for the same reason. (Seeding,
    # which is correctness-not-measurement, keeps its own UnprocessedItems retry
    # loop in run_seed.)
    # Size the HTTP connection pool to the per-pattern driver concurrency.
    # botocore defaults max_pool_connections to 10; the measurement driver runs
    # `concurrency_per_pattern` threads (default 32), so the default pool starves
    # — threads block waiting for a connection ("Connection pool is full"), which
    # inflates the measured p99 with DRIVER queueing that has nothing to do with
    # DynamoDB. Pool to the concurrency + headroom so the measured latency
    # reflects the service, not the client. (+8 covers the warmup warm-pool and
    # any incidental concurrent calls.)
    _pool = int(cfg_block.get("concurrency_per_pattern", 32)) + 8
    client = boto3.client(
        "dynamodb",
        region_name=region,
        config=BotoConfig(
            retries={"max_attempts": 1, "mode": "standard"},
            connect_timeout=3,
            read_timeout=10,
            max_pool_connections=_pool,
        ),
    )
    ctx = RunContext(event, client)
    sink = RowSink(n_patterns=len(ctx.patterns) or 1)
    tainted: dict = {}
    phases_run: list[str] = []
    seed_counts: dict = {}
    seed_verification: dict = {}
    # Exact (uncapped) per-(pattern, phase) call/throttle tallies. Survives the
    # per-key row cap so the summary's throttle/call counts are never truncated.
    exact_counts: dict = {}

    try:
        if "settle" in ctx.phase_plan:
            run_settle(ctx, sink)
            phases_run.append("settle")

        if "seed" in ctx.phase_plan:
            seed_counts = run_seed(ctx, sink)
            seed_verification = verify_seed(ctx, seed_counts)
            phases_run.append("seed")
            # Refuse to proceed if seeding manifestly failed (every target is empty).
            all_empty = seed_verification and all(
                v["actual"] == 0 and v["expected"] > 0 for v in seed_verification.values()
            )
            if all_empty:
                return {
                    "invocation_index": ctx.invocation_index,
                    "phases_run": phases_run,
                    "raw_rows": sink.drain(),
                    "seed_verification": seed_verification,
                    "coverage": {
                        "measured_patterns": [],
                        "missing_patterns": [p["pattern_id"] for p in ctx.patterns],
                        "coverage_incomplete": True,
                    },
                    "measurement_tainted": tainted,
                    "seed_verification_failed": True,
                    "lambda_duration_seconds": time.monotonic() - started,
                }

        if "warmup" in ctx.phase_plan:
            run_warmup(ctx, sink, tainted, exact_counts)
            phases_run.append("warmup")

        if "measure" in ctx.phase_plan:
            # Split the total measurement duration across invocations.
            slice_s = ctx.duration_seconds / max(1, ctx.invocations_total)
            run_measure(ctx, sink, tainted, slice_s, exact_counts)
            phases_run.append("measure")
    except Exception as e:
        return {
            "invocation_index": ctx.invocation_index,
            "phases_run": phases_run,
            "raw_rows": sink.drain(),
            "seed_verification": seed_verification,
            "coverage": {
                "measured_patterns": [],
                "missing_patterns": [],
                "coverage_incomplete": True,
            },
            "measurement_tainted": tainted,
            "handler_error": f"{type(e).__name__}: {e}",
            "lambda_duration_seconds": time.monotonic() - started,
        }

    # Coverage check: every pattern must have produced at least one measure row
    # (only applies when measure phase was part of this invocation).
    rows = sink.drain()
    coverage = {"measured_patterns": [], "missing_patterns": [], "coverage_incomplete": False}
    if "measure" in phases_run:
        measured = {r["pattern_id"] for r in rows if r["phase"] == "measure"}
        declared = {p["pattern_id"] for p in ctx.patterns}
        coverage = {
            "measured_patterns": sorted(measured),
            "missing_patterns": sorted(declared - measured),
            "coverage_incomplete": bool(declared - measured),
        }

    return {
        "invocation_index": ctx.invocation_index,
        "phases_run": phases_run,
        "raw_rows": rows,
        "seed_verification": seed_verification,
        "coverage": coverage,
        "measurement_tainted": tainted,
        "lambda_duration_seconds": time.monotonic() - started,
        # Exact per-(pattern, phase) call/throttle/error tallies (uncapped) so the
        # summary never under-reports throttles OR errors when rows were
        # down-sampled. error_codes names the distinct non-throttle failure codes.
        "exact_counts": [
            {
                "pattern_id": k[0],
                "phase": k[1],
                "calls": v["calls"],
                "throttles": v["throttles"],
                "errors": v.get("errors", 0),
                "error_codes": v.get("error_codes", {}),
                "cancellation_reason_codes": v.get("cancellation_reason_codes", {}),
            }
            for k, v in exact_counts.items()
        ],
        # Echo the load-shape knobs so the report can branch its disclaimer and
        # render the load-risk section only for representative-mode runs.
        "mode": cfg_block.get("mode", "standard"),
        "key_sampling": (cfg_block.get("read_pattern_key_sampling") or "uniform").lower(),
        "items_per_partition": int(cfg_block.get("items_per_partition", 1)),
    }
