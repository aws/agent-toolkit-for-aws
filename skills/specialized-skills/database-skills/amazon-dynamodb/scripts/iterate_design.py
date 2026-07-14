#!/usr/bin/env python3
"""Run ONE round of the iterative DynamoDB design loop, then STOP.

The loop is human-driven, not autonomous. Each invocation runs exactly one
round and hands back to the user:

    [optionally apply a user-agreed change to the design JSON]
        -> decide reuse-vs-redeploy from a schema fingerprint
        -> (gated) deploy, or reuse the existing deployment
        -> benchmark at representative scale (cost-guardrailed)
        -> generate the report + machine-readable findings
        -> refresh the calculator cost report
        -> append one round entry to loop_state.json (with deltas vs prior)
        -> print a compact round summary + a STOP marker
        -> EXIT.

This script never starts a second round, never proposes or selects a change of
its own (it only applies the `--apply-change` it is handed), and never tears
down resources. Teardown stays the separate, two-phase, attested flow
(generate_teardown.py -> teardown.sh). All AWS safety gates are inherited by
calling the real deploy/benchmark scripts as subprocesses rather than
reimplementing them: prod-marker refusal, --yes-deploy, the resource prefix
guard, and the pre-spend cost guardrail all still apply.

Token-efficiency: the agent reads only the compact artifacts this round
produces — design_findings.json, cost_report.md, and loop_state.json. It never
needs to read perf_raw.jsonl (large) or performance_report.md (human-facing).

Usage:
    python3 iterate_design.py \\
        --model dynamodb_data_model.json \\
        --config benchmark_config.json \\
        --loop-state loop_state.json \\
        --manifest created_resources.json \\
        [--apply-change change.json] \\
        [--mode representative] \\
        [--yes-deploy] [--allow-spend] \\
        [--skip-deploy] [--calculator-only] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import NoReturn, Optional

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
try:
    import calculate_costs as cc
except Exception:  # pragma: no cover
    cc = None  # type: ignore[assignment]
try:
    # Imported only for its mode-preset table, so the resolved config this
    # script writes (and records in loop_state) matches exactly what
    # benchmark_model.py would compute. No banner is printed here — we read the
    # preset dict directly rather than calling _apply_mode_preset.
    import benchmark_model as bm
except Exception:  # pragma: no cover
    bm = None  # type: ignore[assignment]

# Artifact filenames written alongside the design JSON (kept stable so the
# agent always knows where to look).
PERF_RAW = "perf_raw.jsonl"
PERF_SUMMARY = "perf_summary.json"
PERF_REPORT = "performance_report.md"
DESIGN_FINDINGS = "design_findings.json"
COST_REPORT = "cost_report.md"


def _die(msg: str, code: int = 2) -> NoReturn:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _load_json(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        _die(f"file not found: {path}")
    with path.open() as f:
        return json.load(f)


def _now_iso(arg_ts: str | None) -> str:
    if arg_ts:
        return arg_ts
    return (
        _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _resolve_config(cfg: dict) -> dict:
    """Return cfg with the mode preset filled in (explicit values always win).

    This MUST match benchmark_model.py's _apply_mode_preset so the config this
    script writes to its overlay — and records in loop_state — is byte-identical
    to what the benchmark would resolve. The subprocesses re-read a file from
    disk, so resolving the preset only in memory here (as a bare
    cfg["mode"]=... ) would be silently dropped: the whole point of the loop's
    --mode flag (zipf, representative scale, items_per_partition) would never
    reach the actual run. We write the resolved config to an overlay and pass
    THAT to deploy + benchmark.
    """
    mode = cfg.get("mode")
    if mode is None or mode == "standard":
        return dict(cfg)
    presets = getattr(bm, "_PRESETS", {}) if bm else {}
    merged = dict(cfg)
    for k, v in presets.get(mode, {}).items():
        if k not in cfg:
            merged[k] = v
    return merged


# ---------------------------------------------------------------------------
# Apply a user-agreed change to the design JSON
# ---------------------------------------------------------------------------


def _apply_change(model: dict, change: dict) -> dict:
    """Apply a user-agreed change to the design. Two supported shapes:

      1. JSON merge-patch  — {"merge": {<partial design to deep-merge>}}
      2. Op list (RFC6902-lite) — {"ops": [{"op": "...", "path": "/a/b", "value": ...}]}
         ops: "replace" | "add" | "remove". Paths are JSON-pointer-ish
         ("/tables/0/gsis/1/projection/type"); list indices are integers, and
         "-" appends to a list (for "add").

    The script applies ONLY what it is handed. It contains no logic to decide
    what should change — that is the user's call, surfaced by the agent."""
    if "merge" in change:
        return _deep_merge(model, change["merge"])
    if "ops" in change:
        for op in change["ops"]:
            _apply_op(model, op)
        return model
    _die(
        '--apply-change file must contain a top-level "merge" object '
        '(partial design to deep-merge) or an "ops" list (JSON-patch-lite). '
        "Got keys: " + (", ".join(change.keys()) or "<none>") + ". " + _OPS_HELP
    )


def _deep_merge(base, patch):
    if isinstance(base, dict) and isinstance(patch, dict):
        for k, v in patch.items():
            if v is None:
                base.pop(k, None)
            else:
                base[k] = _deep_merge(base.get(k), v)
        return base
    return patch


def _pointer_tokens(path: str):
    return [t for t in path.split("/") if t != ""]


_OPS_HELP = (
    'In the --apply-change file, each entry in "ops" needs '
    '{"op": "add"|"replace"|"remove", "path": "/json/pointer", "value": ...} '
    "(value omitted for remove). Example: "
    '{"op": "replace", "path": "/tables/0/gsis/1/projection/type", "value": "INCLUDE"}.'
)


def _apply_op(model: dict, op: dict):
    kind = op.get("op")
    tokens = _pointer_tokens(op.get("path", ""))
    if not tokens:
        _die(f'--apply-change op is missing a non-empty "path": {op}. {_OPS_HELP}')
    parent = model
    for tok in tokens[:-1]:
        key = int(tok) if isinstance(parent, list) else tok
        parent = parent[key]
    last = tokens[-1]
    if isinstance(parent, list):
        if last == "-":
            if kind != "add":
                _die(
                    f"--apply-change: a trailing '-' in path {op.get('path')!r} "
                    f'appends to a list and is only valid for op "add", not '
                    f"{kind!r}. {_OPS_HELP}"
                )
            parent.append(op["value"])
            return
        idx = int(last)
        if kind == "remove":
            parent.pop(idx)
        elif kind in ("add", "replace"):
            if kind == "add":
                parent.insert(idx, op["value"])
            else:
                parent[idx] = op["value"]
        else:
            _die(
                f"--apply-change: unsupported op {kind!r} at path "
                f"{op.get('path')!r}. {_OPS_HELP}"
            )
    else:
        if kind == "remove":
            parent.pop(last, None)
        elif kind in ("add", "replace"):
            parent[last] = op["value"]
        else:
            _die(
                f"--apply-change: unsupported op {kind!r} at path "
                f"{op.get('path')!r}. {_OPS_HELP}"
            )


# ---------------------------------------------------------------------------
# Schema fingerprint — drives reuse-vs-redeploy
# ---------------------------------------------------------------------------


def _schema_fingerprint(model: dict) -> str:
    """A short, stable hash of everything that requires a physical redeploy if
    it changes: per table the key schema, the GSIs (name + keys + projection +
    sorted non-key attributes), and the stream config. RPS / item-size /
    consistency changes do NOT affect this — they only change the driven load
    and the calculator-expected numbers, so they can REUSE the deployment."""
    import hashlib

    sig = []
    for t in sorted(model.get("tables", []), key=lambda x: x.get("table_name", "")):
        ks = t.get("key_schema") or {}
        gsis = []
        for g in sorted(t.get("gsis") or [], key=lambda x: x.get("index_name", "")):
            proj = g.get("projection") or {}
            gsis.append(
                (
                    g.get("index_name"),
                    g.get("partition_key"),
                    g.get("sort_key"),
                    (proj.get("type") or "ALL").upper(),
                    tuple(
                        sorted(
                            proj.get("attributes")
                            or proj.get("non_key_attributes")
                            or proj.get("NonKeyAttributes")
                            or []
                        )
                    ),
                )
            )
        streams = t.get("streams") or {}
        sig.append(
            (
                t.get("table_name"),
                ks.get("partition_key"),
                ks.get("sort_key"),
                tuple(gsis),
                bool(streams.get("enabled")),
                streams.get("view_type"),
            )
        )
    blob = json.dumps(sig, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Headline metrics for loop-state genealogy
# ---------------------------------------------------------------------------


def _headline_from_artifacts(model: dict, workdir: Path, have_bench: bool) -> dict:
    """Build the small numeric snapshot recorded per round. Pulls from the
    compact artifacts only (design_findings.json, perf_summary.json) plus the
    calculator for the canonical monthly cost — never the large raw file."""
    h: dict = {
        "extrapolated_monthly_usd": None,
        "calculator_monthly_usd": None,
        "hot_pattern_throttles": {},
        "p99_ms_by_pattern": {},
        "max_gsi_amplification": None,
        "top_key_share_by_pattern": {},
    }

    # Calculator monthly (always available, no AWS): sum pattern_monthly_cost.
    if cc:
        try:
            tables = model.get("tables", [])
            tmap = {t["table_name"]: t for t in tables}
            sizes = cc._build_entity_attr_sizes(tables)
            total = 0.0
            for ap in model.get("access_patterns", []):
                td = tmap.get(ap.get("table", ""))
                total += cc.pattern_monthly_cost(ap, td, sizes)["total_cost"]
            h["calculator_monthly_usd"] = round(total, 2)
        except Exception:
            pass

    if not have_bench:
        return h

    summary = _load_json(workdir / PERF_SUMMARY, default={})
    findings = _load_json(workdir / DESIGN_FINDINGS, default={})

    # Total extrapolated monthly: derive from any top_cost_driver as
    # monthly / share (share = driver_monthly / total), guarding share>0.
    drivers = findings.get("top_cost_drivers") or []
    for d in drivers:
        if d.get("share"):
            h["extrapolated_monthly_usd"] = round(d["monthly"] / d["share"], 2)
            break

    max_amp: Optional[float] = None
    for p in summary.get("patterns", []):
        pid = p["pattern_id"]
        ss = p.get("steady_state") or {}
        if ss.get("throttles"):
            h["hot_pattern_throttles"][pid] = ss["throttles"]
        if ss.get("p99_ms") is not None:
            h["p99_ms_by_pattern"][pid] = round(ss["p99_ms"], 1)
        amp = ss.get("amplification_ratio")
        if amp is not None:
            max_amp = amp if max_amp is None else max(max_amp, amp)
        kd = ss.get("key_distribution") or {}
        if kd.get("top_key_share") is not None:
            h["top_key_share_by_pattern"][pid] = round(kd["top_key_share"], 3)
    h["max_gsi_amplification"] = round(max_amp, 3) if max_amp is not None else None
    return h


def _compute_deltas(cur: dict, prev: dict | None) -> dict:
    if not prev:
        return {
            "monthly_usd_pct": None,
            "throttle_delta": {},
            "p99_delta_ms": {},
            "gsi_amp_delta": None,
        }
    d = {}
    pc, cm = prev.get("extrapolated_monthly_usd"), cur.get("extrapolated_monthly_usd")
    d["monthly_usd_pct"] = (
        round((cm - pc) / pc * 100, 1) if pc and cm is not None and pc != 0 else None
    )
    td = {}
    keys = set(cur.get("hot_pattern_throttles", {})) | set(prev.get("hot_pattern_throttles", {}))
    for k in keys:
        td[k] = cur.get("hot_pattern_throttles", {}).get(k, 0) - prev.get(
            "hot_pattern_throttles", {}
        ).get(k, 0)
    d["throttle_delta"] = td
    pd = {}
    keys = set(cur.get("p99_ms_by_pattern", {})) & set(prev.get("p99_ms_by_pattern", {}))
    for k in keys:
        pd[k] = round(cur["p99_ms_by_pattern"][k] - prev["p99_ms_by_pattern"][k], 1)
    d["p99_delta_ms"] = pd
    pa, ca = prev.get("max_gsi_amplification"), cur.get("max_gsi_amplification")
    d["gsi_amp_delta"] = round(ca - pa, 3) if pa is not None and ca is not None else None
    return d


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], step: str) -> None:
    print(f"\n[iterate_design] {step}: {' '.join(cmd)}")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        _die(
            f"step '{step}' failed (exit {res.returncode}). See output above.", code=res.returncode
        )


# ---------------------------------------------------------------------------
# Main — one round
# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--model",
        required=True,
        help="path to dynamodb_data_model.json (the design this round "
        "benchmarks; the --apply-change patch is written back here)",
    )
    p.add_argument(
        "--config",
        required=True,
        help="path to benchmark_config.json (per-run knobs; the resolved "
        "mode preset is written to a transient overlay beside it)",
    )
    p.add_argument(
        "--loop-state",
        required=True,
        help="path to loop_state.json — the compact per-round genealogy "
        "this script appends to (created if absent)",
    )
    p.add_argument(
        "--manifest",
        default="created_resources.json",
        help="path to created_resources.json from a prior deploy; drives "
        "the reuse-vs-redeploy decision (default: created_resources.json)",
    )
    p.add_argument(
        "--apply-change",
        default=None,
        help="path to a JSON file with a user-agreed change "
        "('merge' object or 'ops' list) to apply this round",
    )
    p.add_argument(
        "--mode",
        default="representative",
        help="benchmark mode for this round (default: representative)",
    )
    p.add_argument(
        "--timestamp", default=None, help="ISO timestamp for the round entry (default: now UTC)"
    )
    p.add_argument(
        "--yes-deploy",
        action="store_true",
        help="consent to create real AWS resources if a redeploy is " "needed this round",
    )
    p.add_argument(
        "--allow-spend",
        action="store_true",
        help="acknowledge the estimated AWS spend (forwarded to the " "benchmark's cost guardrail)",
    )
    p.add_argument(
        "--skip-deploy",
        action="store_true",
        help="force reuse of the existing deployment; refuse if the " "schema changed",
    )
    p.add_argument(
        "--calculator-only",
        action="store_true",
        help="re-cost the (optionally changed) design with no AWS "
        "deploy or benchmark; for the 'Calculator only' tier",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="rehearse the round without creating AWS resources "
        "(forwards dry_run to deploy); still applies the change "
        "and updates loop_state with deploy_decision recorded",
    )
    args = p.parse_args()

    model_path = Path(args.model)
    workdir = model_path.resolve().parent
    model = _load_json(model_path)
    cfg = _load_json(Path(args.config))
    cfg.setdefault("mode", args.mode)
    # Resolve the mode preset NOW (zipf, representative scale, items_per_partition,
    # …) and persist it to an overlay the subprocesses read from disk. Passing the
    # user's original --config to deploy/benchmark would drop --mode entirely,
    # because those scripts re-read the file and would see no "mode" unless the
    # user had hand-set it. The overlay carries the fully-resolved knobs, and the
    # SAME resolved cfg is what we record in loop_state (so scale_factor etc. are
    # the values actually driven, not null).
    resolved_cfg = _resolve_config(cfg)
    cfg_overlay_path = workdir / ".iterate_config.json"
    ls_path = Path(args.loop_state)
    loop_state = _load_json(
        ls_path,
        default={
            "loop_id": uuid.uuid4().hex[:8],
            "model_path": str(model_path),
            "created_at": _now_iso(args.timestamp),
            "current_schema_fingerprint": None,
            "active_manifest": None,
            "rounds": [],
        },
    )
    manifest_path = Path(args.manifest)
    manifest = _load_json(manifest_path, default={})

    round_idx = len(loop_state.get("rounds", []))
    prev_round = loop_state["rounds"][-1] if loop_state.get("rounds") else None
    ts = _now_iso(args.timestamp)

    # --- 1. Apply the user-agreed change (if any) ---
    applied_diff = None
    if args.apply_change:
        change = _load_json(Path(args.apply_change))
        model = _apply_change(model, change)
        model_path.write_text(json.dumps(model, indent=2))
        applied_diff = change
        print(f"[iterate_design] applied change to {model_path.name}")

    # --- 2. Schema fingerprint + reuse-vs-redeploy decision ---
    fp = _schema_fingerprint(model)
    prior_fp = loop_state.get("current_schema_fingerprint")
    have_manifest = bool(manifest.get("lambda"))
    schema_changed = prior_fp is not None and fp != prior_fp

    if args.calculator_only:
        deploy_decision = "calculator-only"
    elif schema_changed:
        deploy_decision = "deploy"
    elif have_manifest and prior_fp == fp:
        deploy_decision = "reuse"
    elif have_manifest and prior_fp is None:
        # First round against a manifest the loop didn't deploy (no stored
        # fingerprint yet). Trust the existing deployment and REUSE it; the
        # fingerprint computed this round is stored at finish, so the NEXT round
        # detects any schema change normally.
        deploy_decision = "reuse"
    else:
        deploy_decision = "deploy"

    if deploy_decision == "deploy" and args.skip_deploy:
        _die(
            "--skip-deploy was passed but this round needs a redeploy "
            f"(schema fingerprint changed: {prior_fp} -> {fp}). Re-run "
            "without --skip-deploy and with --yes-deploy to redeploy."
        )

    print(
        f"[iterate_design] round {round_idx}: schema_fingerprint={fp} "
        f"(prior={prior_fp}) -> decision={deploy_decision}"
    )

    # --- 3. Calculator-only fast path: re-cost, record, STOP ---
    # (No AWS, no benchmark — calculate_costs reads --model only, so no config
    # overlay is needed on this path.)
    if deploy_decision == "calculator-only":
        cost_out = workdir / COST_REPORT
        _run(
            [
                "python3",
                str(_THIS / "calculate_costs.py"),
                "--model",
                str(model_path),
                "--output",
                str(cost_out),
            ],
            "calculate_costs (calculator-only)",
        )
        headline = _headline_from_artifacts(model, workdir, have_bench=False)
        _finish_round(
            loop_state,
            ls_path,
            round_idx,
            ts,
            args.mode,
            resolved_cfg,
            applied_diff,
            fp,
            deploy_decision,
            headline,
            prev_round,
            finding_signals=[],
            manifest=manifest,
            model=model,
        )
        _emit_summary(round_idx, deploy_decision, headline, prev_round, [], workdir, calc_only=True)
        return

    # Write the resolved-config overlay that deploy + benchmark will read. The
    # SAME file feeds both so the schema deployed and the load driven agree on
    # mode, scale, sampling, and provisioned capacity. Cleaned up in `finally`.
    cfg_overlay_path.write_text(json.dumps(resolved_cfg, indent=2))
    try:
        _run_round_body(
            args,
            model,
            model_path,
            workdir,
            cfg_overlay_path,
            resolved_cfg,
            manifest_path,
            manifest,
            loop_state,
            ls_path,
            round_idx,
            prev_round,
            ts,
            fp,
            prior_fp,
            have_manifest,
            deploy_decision,
            applied_diff,
        )
    finally:
        # Clean up both transient overlays — the main resolved-config overlay and
        # the dry-run variant — even if a subprocess died mid-round (a failed
        # _run raises SystemExit, which propagates through here).
        for transient in (cfg_overlay_path, workdir / ".iterate_dry_config.json"):
            if transient.exists():
                transient.unlink()


def _run_round_body(
    args,
    model,
    model_path,
    workdir,
    cfg_overlay_path,
    resolved_cfg,
    manifest_path,
    manifest,
    loop_state,
    ls_path,
    round_idx,
    prev_round,
    ts,
    fp,
    prior_fp,
    have_manifest,
    deploy_decision,
    applied_diff,
):
    """Deploy-or-reuse → benchmark → report → cost → record. Split out so the
    caller can guarantee overlay cleanup in a `finally`."""
    # --- 4. Deploy (gated) or reuse ---
    if deploy_decision == "deploy":
        if not args.yes_deploy:
            _die(
                "this round requires a real AWS deploy (schema changed or no "
                "active deployment), but --yes-deploy was not passed. Re-run "
                "with --yes-deploy after confirming the target is a sandbox "
                "account. (Existing deployments from a prior round are NOT "
                "torn down automatically — run the prior teardown.sh first if "
                "the schema changed.)",
                code=4,
            )
        if prior_fp is not None and prior_fp != fp and have_manifest:
            print(
                "[iterate_design] NOTE: schema changed since the last "
                "deployment. The prior resources are NOT torn down "
                "automatically — run the prior teardown.sh to avoid orphans."
            )
        deploy_cfg_path = cfg_overlay_path
        if args.dry_run:
            # dry_run is read from the config by deploy_model; layer it onto the
            # resolved overlay so we don't mutate the user's file but still carry
            # the resolved mode/scale into the dry-run preview.
            cfg_dry = dict(resolved_cfg)
            cfg_dry["dry_run"] = True
            deploy_cfg_path = workdir / ".iterate_dry_config.json"
            deploy_cfg_path.write_text(json.dumps(cfg_dry, indent=2))
        deploy_cmd = [
            "python3",
            str(_THIS / "deploy_model.py"),
            "--model",
            str(model_path),
            "--config",
            str(deploy_cfg_path),
            "--manifest-out",
            str(manifest_path),
            "--yes-deploy",
        ]
        _run(deploy_cmd, "deploy_model")
        if args.dry_run:
            # Clean up the temporary dry-run config overlay.
            if deploy_cfg_path.exists():
                deploy_cfg_path.unlink()
            print(
                "[iterate_design] dry-run: deploy rehearsed, no resources "
                "created; skipping benchmark."
            )
            headline = _headline_from_artifacts(model, workdir, have_bench=False)
            _finish_round(
                loop_state,
                ls_path,
                round_idx,
                ts,
                args.mode,
                resolved_cfg,
                applied_diff,
                fp,
                deploy_decision + "(dry-run)",
                headline,
                prev_round,
                finding_signals=[],
                manifest=manifest,
                model=model,
            )
            _emit_summary(
                round_idx,
                deploy_decision + "(dry-run)",
                headline,
                prev_round,
                [],
                workdir,
                calc_only=False,
            )
            return
        manifest = _load_json(manifest_path)
    else:
        print(
            f"[iterate_design] reusing existing deployment " f"(prefix={manifest.get('prefix')})."
        )

    # --- 5. Benchmark (cost guardrail lives inside benchmark_model) ---
    bench_cmd = [
        "python3",
        str(_THIS / "benchmark_model.py"),
        "--model",
        str(model_path),
        "--config",
        str(cfg_overlay_path),
        "--manifest",
        str(manifest_path),
        "--raw-out",
        str(workdir / PERF_RAW),
        "--summary-out",
        str(workdir / PERF_SUMMARY),
    ]
    if args.allow_spend:
        bench_cmd.append("--allow-spend")
    _run(bench_cmd, "benchmark_model")

    # --- 6. Report + 7. cost report ---
    _run(
        [
            "python3",
            str(_THIS / "generate_perf_report.py"),
            "--model",
            str(model_path),
            "--summary",
            str(workdir / PERF_SUMMARY),
            "--output",
            str(workdir / PERF_REPORT),
            "--findings-out",
            str(workdir / DESIGN_FINDINGS),
        ],
        "generate_perf_report",
    )
    _run(
        [
            "python3",
            str(_THIS / "calculate_costs.py"),
            "--model",
            str(model_path),
            "--output",
            str(workdir / COST_REPORT),
        ],
        "calculate_costs",
    )

    findings = _load_json(workdir / DESIGN_FINDINGS, default={})
    signals = sorted({f["signal"] for f in findings.get("classified_findings", [])})
    headline = _headline_from_artifacts(model, workdir, have_bench=True)

    # --- 8. Update loop_state + 9. emit summary + STOP ---
    _finish_round(
        loop_state,
        ls_path,
        round_idx,
        ts,
        args.mode,
        resolved_cfg,
        applied_diff,
        fp,
        deploy_decision,
        headline,
        prev_round,
        finding_signals=signals,
        manifest=manifest,
        model=model,
    )
    _emit_summary(
        round_idx, deploy_decision, headline, prev_round, signals, workdir, calc_only=False
    )


def _finish_round(
    loop_state,
    ls_path,
    round_idx,
    ts,
    mode,
    cfg,
    applied_diff,
    fp,
    deploy_decision,
    headline,
    prev_round,
    finding_signals,
    manifest,
    model,
):
    prev_headline = prev_round.get("headline") if prev_round else None
    entry = {
        "round": round_idx,
        "timestamp": ts,
        "mode": mode,
        "scale_factor": cfg.get("scale_factor"),
        "applied_diff": applied_diff,
        "schema_fingerprint": fp,
        "deploy_decision": deploy_decision,
        "headline": headline,
        "delta_vs_prev": _compute_deltas(headline, prev_headline),
        "finding_signals": finding_signals,
        "user_decision": None,
    }
    loop_state["rounds"].append(entry)
    loop_state["current_schema_fingerprint"] = fp
    if manifest.get("prefix"):
        loop_state["active_manifest"] = manifest.get("prefix")
    ls_path.write_text(json.dumps(loop_state, indent=2))


def _emit_summary(
    round_idx, deploy_decision, headline, prev_round, signals, workdir, calc_only=False
):
    print("\n" + "=" * 72)
    print(f"ROUND {round_idx} SUMMARY")
    print("=" * 72)
    print(f"  decision: {deploy_decision}")
    if headline.get("calculator_monthly_usd") is not None:
        print(f"  calculator monthly: ${headline['calculator_monthly_usd']:,.2f}")
    if headline.get("extrapolated_monthly_usd") is not None:
        print(f"  measured-extrapolated monthly: " f"${headline['extrapolated_monthly_usd']:,.2f}")
    if not calc_only:
        if headline.get("hot_pattern_throttles"):
            print(f"  hot-pattern throttles: {headline['hot_pattern_throttles']}")
        else:
            print("  hot-pattern throttles: none observed")
        if headline.get("max_gsi_amplification") is not None:
            print(f"  max GSI amplification: {headline['max_gsi_amplification']}×")
    if prev_round:
        delta = _compute_deltas(headline, prev_round.get("headline"))
        print(f"  delta vs round {prev_round['round']}: {json.dumps(delta)}")
    print(f"  design-finding signals: {signals or 'none (clean)'}")
    print(
        f"  artifacts: {DESIGN_FINDINGS}, {COST_REPORT}" + ("" if calc_only else f", {PERF_REPORT}")
    )
    print("=" * 72)
    print(
        f"=== ROUND {round_idx} COMPLETE — handing back to user. "
        "The loop does not self-iterate. Review the findings, decide a "
        "change, and re-run for the next round. ==="
    )


if __name__ == "__main__":
    main()
