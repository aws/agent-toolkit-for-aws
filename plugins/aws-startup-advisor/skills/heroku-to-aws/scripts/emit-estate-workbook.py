#!/usr/bin/env python3
"""Emit a reviewable spreadsheet of the discovered Heroku estate.

Customers review spreadsheets, not HTML. This script re-packages the run's
existing JSON artifacts into one `.xlsx` workbook — one tab per resource family,
plus a summary, the shared-data-store cohorts, the AWS mapping status per row,
and (when the Estimate ran) the cost picture. It GENERATES nothing: every cell is
copied from an artifact the phases already validated, or left blank.

Deliberately NOT included, matching the skill's discovery posture: config var
names or values, credentials, account emails, custom domain hostnames (counts
only), app/resource UUIDs, VPC/subnet identifiers.

The workbook is written with the standard library only (an .xlsx is a zip of
XML; inline strings need no shared-string table), so it works wherever the skill
runs. Fail-open: any missing or unreadable input prints the reason, writes no
file, and exits 0 — this is a convenience artifact, never a gate.

Usage:
  python3 scripts/emit-estate-workbook.py --migration-dir <dir> [--out <path>]

Reads:
  <dir>/heroku-resource-inventory.json   required
  <dir>/aws-design.json                  optional — proposed AWS target per resource, deferred[]
  <dir>/estimation-infra.json            optional — Heroku baseline vs AWS scenarios

Writes:
  <dir>/heroku-estate.xlsx               (or --out)

Status line (stdout):
  ESTATE_OK   | path=<file> | apps=<n> | resources=<n>
  ESTATE_SKIP | reason=<why>
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


def escape(text: str) -> str:
    """XML-escape a cell value (we only WRITE XML here; nothing is parsed)."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

DATA_STORES = ("heroku-postgresql", "heroku-redis", "heroku-kafka")

# Fields the workbook must never carry, by inventory location.
EXCLUDED_NOTE = (
    "Deliberately not included: config var names or values, credentials, account emails, "
    "custom domain hostnames (counts only), app and resource UUIDs, VPC/subnet identifiers."
)


# ----------------------------------------------------------------------------
# Minimal .xlsx writer (inline strings; numbers typed as numbers)
# ----------------------------------------------------------------------------
def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"><v>{1 if v else 0}</v></c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'


def _sheet_xml(rows: list[list]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           "<sheetData>"]
    for ri, row in enumerate(rows, start=1):
        cells = "".join(_cell(f"{_col(ci)}{ri}", v) for ci, v in enumerate(row))
        out.append(f'<row r="{ri}">{cells}</row>')
    out.append("</sheetData></worksheet>")
    return "".join(out)


def write_xlsx(path: Path, sheets: list[tuple[str, list[list]]]) -> None:
    def sheet_name(n: str) -> str:
        bad = '[]:*?/\\'
        n = "".join("_" if ch in bad else ch for ch in n)
        return n[:31]

    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>',
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>']
    wb = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
    wbrels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    files: list[tuple[str, str]] = []
    for i, (name, rows) in enumerate(sheets, start=1):
        ct.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                  'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        wb.append(f'<sheet name="{escape(sheet_name(name))}" sheetId="{i}" r:id="rId{i}"/>')
        wbrels.append(f'<Relationship Id="rId{i}" '
                      'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                      f'Target="worksheets/sheet{i}.xml"/>')
        files.append((f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows)))
    ct.append("</Types>")
    wb.append("</sheets></workbook>")
    wbrels.append("</Relationships>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>')
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "".join(ct))
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", "".join(wb))
        z.writestr("xl/_rels/workbook.xml.rels", "".join(wbrels))
        for n, body in files:
            z.writestr(n, body)
    tmp.replace(path)


# ----------------------------------------------------------------------------
# Artifact readers
# ----------------------------------------------------------------------------
def _load(path: Path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        return {"__error__": f"{path.name}: {e.__class__.__name__}"}


def _design_index(design) -> tuple[dict, dict]:
    """source_resource_id -> (aws_service, one-line sizing); addon (name, plan) -> deferred reason."""
    by_source: dict = {}
    deferred: dict = {}
    if not isinstance(design, dict):
        return by_source, deferred
    for svc in design.get("services") or []:
        if not isinstance(svc, dict):
            continue
        cfg = svc.get("aws_config") or {}
        size = (cfg.get("instance_class") or cfg.get("instance_type") or cfg.get("node_type")
                or cfg.get("broker_instance_type") or "")
        extra = []
        if cfg.get("multi_az") is True:
            extra.append("Multi-AZ")
        if cfg.get("broker_count"):
            extra.append(f"{cfg['broker_count']} brokers")
        if cfg.get("max_instances") or cfg.get("min_instances"):
            extra.append(f"{cfg.get('min_instances', 1)}-{cfg.get('max_instances', 1)} instances")
        if cfg.get("desired_count"):
            extra.append(f"x{cfg['desired_count']}")
        by_source[svc.get("source_resource_id")] = (svc.get("aws_service", ""), " ".join([size] + extra).strip())
    for d in design.get("deferred") or []:
        if isinstance(d, dict):
            deferred[(d.get("addon_name"), d.get("addon_plan"))] = d.get("reason", "Deferred")
    return by_source, deferred


# ----------------------------------------------------------------------------
# Sheet builders
# ----------------------------------------------------------------------------
def build_sheets(inv: dict, design, est) -> tuple[list[tuple[str, list[list]]], int, int]:
    apps = inv.get("apps") or []
    resources = inv.get("resources") or []
    meta = inv.get("metadata") or {}
    live = inv.get("live_metadata") or {}
    by_source, deferred = _design_index(design)
    has_design = bool(by_source or deferred)

    def status_for(res) -> tuple[str, str, str]:
        """(AWS status, proposed target, proposed sizing)"""
        hit = by_source.get(res.get("resource_id"))
        if hit:
            return "Mapped", hit[0], hit[1]
        cfg = res.get("config") or {}
        reason = deferred.get((cfg.get("addon_service"), cfg.get("plan")))
        if reason:
            return f"Deferred - {reason}", "", ""
        return ("Not in design" if has_design else "Design not run"), "", ""

    by_app: dict = defaultdict(lambda: defaultdict(list))
    for r in resources:
        by_app[r.get("heroku_app")][r.get("resource_type")].append(r)

    # ---- Apps
    app_rows = [["Heroku app", "Private Space", "Generation", "Environment tier", "Tier source",
                 "Running dynos", "Process types", "Add-ons owned", "Config vars (count only)",
                 "Custom domains (count)", "Cohort", "Has add-on not yet mapped to AWS"]]
    cohort_of: dict = {}
    for c in (inv.get("shared_data_stores") or {}).get("cohorts") or []:
        for a in c.get("apps") or []:
            cohort_of[a] = c.get("cohort_id")
    for a in sorted(apps, key=lambda x: x.get("app_name") or ""):
        name = a.get("app_name")
        forms = by_app[name].get("formation", [])
        addons = by_app[name].get("addon", [])
        cfgs = by_app[name].get("config", [])
        doms = by_app[name].get("domain", [])
        unmapped = any(status_for(x)[0].startswith("Deferred") for x in addons) if has_design else ""
        app_rows.append([
            name, a.get("space") or "(Common Runtime)", a.get("heroku_generation", ""),
            a.get("environment_tier", ""), a.get("environment_tier_source", ""),
            sum(int((f.get("config") or {}).get("quantity") or 0) for f in forms), len(forms), len(addons),
            sum(len((c.get("config") or {}).get("config_var_keys") or []) for c in cfgs), len(doms),
            cohort_of.get(name, ""), ("Yes" if unmapped else "No") if has_design else "",
        ])

    # ---- Formations
    form_rows = [["Heroku app", "Process type", "Dyno size", "Running dynos", "AWS status",
                  "Proposed AWS target", "Proposed AWS sizing"]]
    for r in sorted(resources, key=lambda x: x.get("resource_id") or ""):
        if r.get("resource_type") != "formation":
            continue
        c = r.get("config") or {}
        st, tgt, sz = status_for(r)
        form_rows.append([r.get("heroku_app"), c.get("process_type"), c.get("dyno_type"), c.get("quantity"), st, tgt, sz])

    # ---- Data stores
    pg_rows = [["Owning Heroku app", "Plan", "PG version", "Data size (GB, measured)", "Role", "Follows",
                "Connection pooling", "Attached from other apps", "Heroku $/mo (plan price)", "AWS status",
                "Proposed AWS target", "Proposed sizing"]]
    redis_rows = [["Owning Heroku app", "Plan", "Redis version", "HA on Heroku", "Attached from other apps",
                   "Heroku $/mo (plan price)", "AWS status", "Proposed AWS target", "Proposed sizing"]]
    kafka_rows = [["Owning Heroku app", "Plan", "Topics", "Partitions/topic", "Attached from other apps",
                   "Heroku $/mo (plan price)", "AWS status", "Proposed AWS target", "Proposed sizing"]]
    other_rows = [["Heroku app", "Add-on service", "Plan", "Heroku $/mo (plan price)", "AWS status",
                   "Proposed AWS service"]]
    for r in sorted(resources, key=lambda x: x.get("resource_id") or ""):
        if r.get("resource_type") != "addon":
            continue
        c = r.get("config") or {}
        svc = c.get("addon_service")
        st, tgt, sz = status_for(r)
        attached = len(c.get("attached_apps") or [])
        price = c.get("monthly_price_usd")
        if svc == "heroku-postgresql":
            pg_rows.append([r.get("heroku_app"), c.get("plan"), c.get("pg_version"), c.get("data_size_gb"),
                            c.get("pg_role", ""), c.get("pg_leader") or "", c.get("connection_pooling"),
                            attached, price, st, tgt, sz])
        elif svc == "heroku-redis":
            redis_rows.append([r.get("heroku_app"), c.get("plan"), c.get("redis_version"), c.get("ha_enabled"),
                               attached, price, st, tgt, sz])
        elif svc == "heroku-kafka":
            kafka_rows.append([r.get("heroku_app"), c.get("plan"), c.get("topic_count"), c.get("partitions_per_topic"),
                               attached, price, st, tgt, sz])
        else:
            other_rows.append([r.get("heroku_app"), svc, c.get("plan"), price, st, tgt])

    # ---- Cohorts
    cohort_rows = [["Cohort", "Apps", "Shared data stores", "Apps in cohort", "Shared stores (resource ids)"]]
    for c in (inv.get("shared_data_stores") or {}).get("cohorts") or []:
        cohort_rows.append([c.get("cohort_id"), len(c.get("apps") or []), len(c.get("shared_stores") or []),
                            ", ".join(c.get("apps") or []), ", ".join(c.get("shared_stores") or [])])
    if len(cohort_rows) == 1:
        cohort_rows.append(["(none)", "", "", "No add-on is attached to more than one app, or attachments were not captured.", ""])

    # ---- Summary
    tiers = Counter(a.get("environment_tier", "") or "(not inferred)" for a in apps)
    gens = Counter(a.get("heroku_generation", "") for a in apps)
    n_form = sum(1 for r in resources if r.get("resource_type") == "formation")
    n_dyno = sum(int((r.get("config") or {}).get("quantity") or 0) for r in resources if r.get("resource_type") == "formation")
    n_pg = sum(1 for r in resources if (r.get("config") or {}).get("addon_service") == "heroku-postgresql")
    n_rd = sum(1 for r in resources if (r.get("config") or {}).get("addon_service") == "heroku-redis")
    n_kf = sum(1 for r in resources if (r.get("config") or {}).get("addon_service") == "heroku-kafka")
    n_other = sum(1 for r in resources if r.get("resource_type") == "addon"
                  and (r.get("config") or {}).get("addon_service") not in DATA_STORES)
    n_deferred = sum(1 for r in resources if r.get("resource_type") == "addon" and status_for(r)[0].startswith("Deferred"))
    pg_total_gb = round(sum(float((r.get("config") or {}).get("data_size_gb") or 0) for r in resources
                            if (r.get("config") or {}).get("addon_service") == "heroku-postgresql"
                            and (r.get("config") or {}).get("pg_role") != "follower"), 2)
    cohorts = (inv.get("shared_data_stores") or {}).get("cohorts") or []
    summary = [["Heroku estate summary", "", ""],
               ["Discovery timestamp", meta.get("discovery_timestamp", ""), ""],
               ["Discovery sources", ", ".join(meta.get("discovery_sources") or []), ""],
               ["Confidence", meta.get("confidence", ""), meta.get("confidence_note", "") or ""],
               ["", "", ""],
               ["Heroku apps", len(apps), ""],
               ["Process types (formations)", n_form, ""],
               ["Running dynos", n_dyno, "Point-in-time; formations scaled to zero are not visible to live discovery"],
               ["Heroku Postgres databases", n_pg, ""],
               ["  measured data, leaders only (GB)", pg_total_gb, "Followers excluded; forks included"],
               ["Heroku Redis instances", n_rd, ""],
               ["Heroku Kafka add-ons", n_kf, ""],
               ["Other add-ons", n_other, ""],
               ["  add-ons deferred (no AWS mapping yet)", n_deferred if has_design else "", "" if has_design else "Design not run"],
               ["Cohorts (apps linked by a shared data store)", len(cohorts), ""],
               ["Apps in a cohort", len({a for c in cohorts for a in (c.get("apps") or [])}), ""],
               ["", "", ""],
               ["Environment tier (inferred)", "", ""]]
    for t, n in sorted(tiers.items(), key=lambda kv: -kv[1]):
        summary.append([f"  {t}", n, ""])
    summary.append(["", "", ""])
    summary.append(["Heroku generation", "", ""])
    for g, n in sorted(gens.items(), key=lambda kv: -kv[1]):
        summary.append([f"  {g or '(unknown)'}", n, ""])

    # ---- Cost estimate (optional)
    cost_rows: list[list] = []
    if isinstance(est, dict):
        cur = est.get("current_costs") or {}
        proj = est.get("projected_costs") or {}
        comp = est.get("cost_comparison") or {}
        baseline = comp.get("heroku_monthly_baseline")
        if baseline is None:
            baseline = cur.get("heroku_monthly") or cur.get("heroku_monthly_estimated")
        cost_rows = [["Heroku baseline vs preliminary AWS cost (USD / month)", "", ""],
                     ["Figures are copied from estimation-infra.json. The Heroku baseline is derived unless its source is billing_data.", "", ""],
                     ["", "", ""],
                     ["Heroku baseline", baseline, f"source: {cur.get('source', '')}; {cur.get('accuracy', '')}".rstrip("; ")],
                     ["  note", cur.get("baseline_note") or "", ""],
                     ["AWS Premium", proj.get("aws_monthly_premium"), ""],
                     ["AWS Balanced (primary)", proj.get("aws_monthly_balanced"), ""],
                     ["AWS Optimized", proj.get("aws_monthly_optimized"), ""],
                     ["Pricing source", (est.get("pricing_source") or {}).get("status", ""), (est.get("pricing_source") or {}).get("note", "") or ""]]
        contract = cur.get("contract")
        if isinstance(contract, dict):
            cost_rows += [["", "", ""],
                          ["Contract reconciliation (monthly)", "", ""],
                          ["Contract term", f"{contract.get('term_start', '')} to {contract.get('term_end', '')}", ""],
                          ["Contract run-rate", contract.get("monthly_run_rate"), "Committed spend / term months"],
                          ["Discovered (derived)", contract.get("discovered_monthly"), "Same figure as the Heroku baseline above"],
                          ["Gap", contract.get("gap_monthly"), contract.get("gap_explanation", "") or ""]]
            for line in contract.get("lines") or []:
                cost_rows.append([f"  {line.get('category', '')}", line.get("monthly_usd"), line.get("note", "") or ""])
        for w in est.get("warnings") or []:
            cost_rows.append(["warning", str(w), ""])

    readme = [["Heroku estate data for AWS"],
              ["Generated by the heroku-to-aws migration skill from the run's discovery, design and estimate artifacts. Draft for review — every figure is copied from those artifacts, none is computed here."],
              [""],
              ["Tabs"],
              ["Summary: headline counts."],
              ["Apps: one row per Heroku app with tier, dynos, add-ons, cohort and AWS mapping status."],
              ["Formations: process types and dyno sizes with the proposed AWS target."],
              ["Postgres / Redis / Kafka / Other add-ons: every add-on, its plan, measured size where captured, and AWS mapping status."],
              ["Shared data stores: apps linked by an add-on attached to more than one app (cohorts). Apps in a cohort cannot move strictly one at a time without cross-cloud access to the shared store."],
              ["Cost estimate: present only when the Estimate phase ran."],
              [""],
              ["Read this before relying on the numbers"],
              ["Dyno counts and database sizes are point-in-time values from the discovery timestamp. Formations scaled to zero are not visible to live discovery."],
              ["Environment tier is inferred from pipeline stage or the app name; it is a label, not a fact."],
              ["'Deferred' rows have no AWS sizing yet and are excluded from any AWS cost shown."],
              [EXCLUDED_NOTE]]
    for lim in live.get("limitations") or []:
        readme.append([f"Limitation: {lim}"])

    sheets = [("Read Me", readme), ("Summary", summary), ("Apps", app_rows), ("Formations", form_rows),
              ("Postgres", pg_rows), ("Redis", redis_rows), ("Kafka", kafka_rows), ("Other add-ons", other_rows),
              ("Shared data stores", cohort_rows)]
    if cost_rows:
        sheets.append(("Cost estimate", cost_rows))
    return sheets, len(apps), len(resources)


# ----------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--migration-dir", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    mdir = Path(args.migration_dir)
    if not mdir.is_dir():
        print(f"ESTATE_SKIP | reason=migration dir not found: {mdir}")
        return 0
    inv = _load(mdir / "heroku-resource-inventory.json")
    if inv is None:
        print("ESTATE_SKIP | reason=heroku-resource-inventory.json missing")
        return 0
    if not isinstance(inv, dict) or "__error__" in inv:
        print(f"ESTATE_SKIP | reason=inventory unreadable ({inv.get('__error__') if isinstance(inv, dict) else 'not an object'})")
        return 0
    design = _load(mdir / "aws-design.json")
    if isinstance(design, dict) and "__error__" in design:
        design = None
    est = _load(mdir / "estimation-infra.json")
    if isinstance(est, dict) and "__error__" in est:
        est = None
    try:
        sheets, n_apps, n_res = build_sheets(inv, design, est)
        out = Path(args.out) if args.out else mdir / "heroku-estate.xlsx"
        write_xlsx(out, sheets)
    except Exception as e:  # fail-open: this is a convenience artifact
        print(f"ESTATE_SKIP | reason={e.__class__.__name__}: {e}")
        return 0
    print(f"ESTATE_OK | path={out} | apps={n_apps} | resources={n_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
