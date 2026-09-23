#!/usr/bin/env python3
"""Assert the azure-to-aws ESTIMATE phase over the azure-iac-terraform corpus.

Sibling of check_expected_design.py, and it exists for the same reason: the DSL's
`_assert` prose is bound by CI but never evaluated, so the model both produces the
artifact and grades it. This script is the independent oracle.

Estimate is the first phase whose fixtures cannot use exact assertions -- AWS rates
change on AWS's cadence, so a committed exact total would go permanently red on the
next refresh. Tolerance is applied in three tiers, and the tiers are the point:

  TIER 1 (exact)      -- everything that is not a dollar figure: which lines exist,
                         which are excluded and why, the labels, the flags, run_mode.
                         Rates drift; contracts do not.
  TIER 2 (relational) -- arithmetic identities, exact to 1e-6 relative. Properties of
                         the ARTIFACT, not of the price list, so they survive refreshes.
  TIER 3 (banded)     -- per-line dollar figures against [min, max] RECORDED in
                         expected-estimate.json, never recomputed here. Recomputing
                         from the same rate card the run read would catch arithmetic
                         slips and nothing else -- not a Linux rate used for a Windows
                         box, not an RDS class read for a DocumentDB line.

Usage:
    python3 check_expected_estimate.py <migration_run_dir>

Exit 0 iff every check passes.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def load(path: Path) -> dict:
    if not path.exists():
        FAILS.append(f"missing {path.name}")
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        FAILS.append(f"{path.name} is not valid JSON: {e}")
        return {}


def num(v) -> float | None:
    """Coerce a cost value to float, tolerating '123.45' strings. None stays None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace("$", "").replace(",", "").strip())
        except ValueError:
            return None
    return None


def close(a: float, b: float, rel: float) -> bool:
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


def banded(label: str, got, lo: float, hi: float, basis: str) -> None:
    """TIER 3. Band is recorded, not computed."""
    g = num(got)
    if g is None:
        FAILS.append(f"{label}: expected a numeric cost in [{lo}, {hi}], got {got!r}")
        return
    if not (lo <= g <= hi):
        FAILS.append(
            f"{label}: {g} is outside the recorded band [{lo}, {hi}] "
            f"(basis {basis}). If a rate genuinely changed, edit expected-estimate.json "
            f"so the new band is a reviewable diff -- do not widen it to pass."
        )


def flatten(o) -> str:
    return json.dumps(o, ensure_ascii=False)


def main() -> int:  # noqa: C901 -- a fixture oracle is a checklist; splitting it hides the list
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run = Path(sys.argv[1])
    exp = load(HERE / "expected-estimate.json")
    if not exp:
        print("FAIL")
        for f in FAILS:
            print(" -", f)
        return 1

    def upstream(filename: str, sibling: str) -> dict:
        """Read a phase INPUT from the run dir, falling back to its committed golden.

        Same pattern as check_expected_design.py's inventory lookup: a live replay run
        carries every artifact, while a committed per-phase golden tree carries only the
        artifact that phase produced. Falling back keeps the goldens de-duplicated --
        copying aws-design.json into after-estimate/ would create a second copy to drift.
        """
        p = run / filename
        if not p.exists():
            p = HERE / sibling / filename
        return load(p)

    est = load(run / exp["estimate_file"])
    ph = load(run / exp["phase_status_file"])
    design = upstream(exp["design_file"], "after-design")
    prefs = upstream(exp["preferences_file"], "after-clarify-complete")

    if not est:
        print("FAIL")
        for f in FAILS:
            print(" -", f)
        return 1

    pc = est.get("projected_costs") or {}
    lift = pc.get("lift") or {}
    rs = pc.get("right_sized") or {}
    cc = est.get("cost_comparison") or {}

    # `breakdown` is an OBJECT keyed by service_id, per the shared schema
    # (projected_costs.breakdown type: object) and matching what the other skills emit.
    # An array here is a schema violation that `_validate_json` cannot catch, because it
    # checks parseability rather than conformance.
    raw_bd = pc.get("breakdown")
    check(
        isinstance(raw_bd, dict),
        f"projected_costs.breakdown is {type(raw_bd).__name__}, and the shared "
        f"estimation-infra.schema.json declares it type 'object' keyed by service_id with a "
        f"'total'. An array passes _validate_json and still violates the contract.",
    )
    by_id = {}
    if isinstance(raw_bd, dict):
        for sid, entry in raw_bd.items():
            if sid == "total" or sid.startswith("_"):
                continue
            by_id[sid] = {**entry, "service_id": sid}
    elif isinstance(raw_bd, list):  # tolerate, so the rest of the checks still report
        for entry in raw_bd:
            sid = entry.get("service_id")
            if sid in by_id:
                FAILS.append(f"breakdown has duplicate service_id {sid!r}")
            by_id[sid] = entry
    breakdown = list(by_id.values())

    # ---------------- TIER 1: dual output exists at all ----------------
    for p in exp["dual_output"]["required_paths"]:
        cur, ok = est, True
        for seg in p.split("."):
            if not isinstance(cur, dict) or seg not in cur:
                ok = False
                break
            cur = cur[seg]
        check(ok, f"dual_output: required path {p!r} is absent. {exp['dual_output']['must_not_be']} is not the specified shape.")

    # Tolerance for every TIER 2 identity. Defined ONCE, here, above its first use: it was
    # originally bound by a walrus inside an `if`, so an artifact that skipped that branch
    # crashed the oracle instead of being reported on. A crashing oracle is worse than a
    # failing one -- it says nothing about the artifact.
    rel = float(exp["relational"]["rel_tolerance"])

    # ---------------- TIER 1 + TIER 2: the three shared scenario keys ----------------
    # INTENSIONAL check against the vendored schema, not against a recorded value: read the
    # schema's own `required` list rather than restating it, so the two cannot drift apart.
    sc = exp["scenarios"]
    schema_path = HERE / exp["schema_relpath"]
    if schema_path.exists():
        schema = json.loads(schema_path.read_text())
        for key in (schema.get("properties", {}).get("projected_costs", {}).get("required") or []):
            check(
                key in pc,
                f"projected_costs is missing {key!r}, which the shared "
                f"estimation-infra.schema.json lists as REQUIRED. "
                f"No additionalProperties:false permits ADDING the azure lift/right_sized "
                f"keys; it does not permit omitting a required one.",
            )
        ac_type = schema.get("properties", {}).get("accuracy_confidence", {}).get("type")
        if ac_type == "string" and "accuracy_confidence" in est:
            check(
                isinstance(est["accuracy_confidence"], str),
                f"accuracy_confidence is {type(est['accuracy_confidence']).__name__}; the shared "
                f"schema declares it a string.",
            )
    else:
        FAILS.append(f"cannot reach the shared schema at {exp['schema_relpath']} to check conformance")

    bal, prem, opt = (num(pc.get(k)) for k in ("aws_monthly_balanced", "aws_monthly_premium", "aws_monthly_optimized"))
    rsm = num(rs.get("monthly"))
    if None not in (bal, rsm):
        check(
            close(bal, rsm, rel),
            f"aws_monthly_balanced is {bal} but right_sized.monthly is {rsm}. {sc['_anchor_why']}",
        )
    if None not in (prem, bal):
        check(prem >= bal, f"aws_monthly_premium {prem} is below Balanced {bal}; higher resilience costs more, not less")
    if None not in (opt, bal):
        check(opt <= bal, f"aws_monthly_optimized {opt} is above Balanced {bal}; a commitment discount cannot raise the bill")
    banded("aws_monthly_premium", prem, sc["premium_min"], sc["premium_max"], "total")
    banded("aws_monthly_optimized", opt, sc["optimized_min"], sc["optimized_max"], "total")
    if opt is not None and bal is not None and close(opt, round(bal * (1 - sc["blanket_discount"]), 2), 0.01):
        FAILS.append(
            f"aws_monthly_optimized {opt} equals Balanced x (1 - {sc['blanket_discount']}), i.e. a BLANKET "
            f"discount across the whole total. {sc['_blanket_why']}"
        )
    ann = num(pc.get("aws_annual_optimized"))
    if None not in (ann, opt):
        check(close(ann, opt * 12, rel), f"aws_annual_optimized is {ann}, expected {round(opt * 12, 2)}")
    check(bool(pc.get("_premium_basis")), f"projected_costs._premium_basis must show the uplift arithmetic. {sc['_show_work_why']}")
    check(bool(pc.get("_optimized_basis")), f"projected_costs._optimized_basis must show the two subtotals and the rate. {sc['_show_work_why']}")

    # ---------------- TIER 1: the line shape every line owes ----------------
    # estimate-infra.md § "The breakdown line shape" requires `basis` on EVERY line,
    # including the $0 ones, and requires `components` to sum to its own line.
    for line in breakdown:
        sid = line.get("service_id")
        check(
            bool((line.get("basis") or "").strip()),
            f"{sid!r}: basis is required on every line, including the $0 ones -- "
            f"'a VPC is not billed' is the answer to a question a reader otherwise has to assume.",
        )
        comps = line.get("components")
        if isinstance(comps, dict):
            cs = sum(num(v) or 0.0 for v in comps.values())
            lv = num(line.get("right_sized_monthly"))
            if lv is not None and any(num(v) is not None for v in comps.values()):
                check(
                    close(cs, lv, 1e-2),
                    f"{sid!r}: components sum to {round(cs, 2)} but the line is {lv}. "
                    f"A breakdown that contradicts itself is worse than one without components.",
                )

    # ---------------- TIER 3: priced line bands ----------------
    lb = exp["line_bands"]
    for spec in lb["priced"]:
        sid = spec["service_id"]
        line = by_id.get(sid)
        if line is None:
            FAILS.append(f"breakdown is missing priced line {sid!r}")
            continue
        banded(f"{sid}.right_sized_monthly", line.get("right_sized_monthly"), spec["min"], spec["max"], spec["basis"])
        if "must_not_be" in spec:
            g = num(line.get("right_sized_monthly"))
            if g is not None and close(g, float(spec["must_not_be"]), 0.02):
                FAILS.append(f"{sid}: {g} matches the known-wrong answer {spec['must_not_be']}. {spec['must_not_be_why']}")

    # zero-cost lines must be PRESENT at 0, not absent
    zc = lb["zero_cost"]
    for sid in zc["service_ids"]:
        line = by_id.get(sid)
        if line is None:
            FAILS.append(f"{sid}: absent from breakdown. It must appear at 0.00 -- a missing line is indistinguishable from a forgotten one.")
            continue
        g = num(line.get("right_sized_monthly"))
        check(g == 0.0, f"{sid}: expected 0.0, got {line.get('right_sized_monthly')!r}")

    # ---------------- TIER 1: exclusions, reasons, and the Windows rule ----------------
    excluded_ids: list[str] = []
    for spec in lb["excluded"]:
        sid = spec["service_id"]
        excluded_ids.append(sid)
        line = by_id.get(sid)
        if line is None:
            FAILS.append(f"{sid}: absent from breakdown. An excluded line must still appear, carrying its exclusion_reason -- dropping it makes the estate look smaller than it is.")
            continue
        got_reason = line.get("exclusion_reason")
        check(
            got_reason == spec["exclusion_reason"],
            f"{sid}: exclusion_reason is {got_reason!r}, expected {spec['exclusion_reason']!r}. {spec['_why']}",
        )
        check(
            line.get("pricing_source") == spec["pricing_source"],
            f"{sid}: pricing_source is {line.get('pricing_source')!r}, expected {spec['pricing_source']!r}",
        )
        check(line.get("excluded_from_total") is True, f"{sid}: excluded_from_total must be true")
        if spec.get("missing_component_substring"):
            mc = (line.get("missing_component") or "").lower()
            check(
                spec["missing_component_substring"].lower() in mc,
                f"{sid}: missing_component is {line.get('missing_component')!r} and must name the "
                f"missing piece (expected to contain {spec['missing_component_substring']!r}). {spec['_why']}",
            )
        if spec.get("floor") is not None:
            banded(f"{sid} floor", line.get("right_sized_monthly"), spec["floor_min"], spec["floor_max"], "rate_times_count")
        if spec.get("must_not_be_priced_from"):
            # The detectable signal is a line that ended up with a NUMBER while claiming
            # the wrong table. Forbidding the substring outright fails a correct artifact
            # that names the table in order to say it was NOT used -- the same defect as
            # an oracle that rejects a correctly-cased ARM type as a guess.
            priced = num(line.get("right_sized_monthly")) or num(line.get("lift_monthly"))
            if priced:
                check(
                    spec["must_not_be_priced_from"] not in flatten(line),
                    f"{sid}: carries a cost of {priced} and cites {spec['must_not_be_priced_from']!r}. {spec['_why']}",
                )

    # ---------------- TIER 2: totals reconcile against their own lines ----------------
    for key, obj, field in (("lift", lift, "lift_monthly"), ("right_sized", rs, "right_sized_monthly")):
        total = num(obj.get("monthly"))
        if total is None:
            FAILS.append(f"projected_costs.{key}.monthly is not numeric: {obj.get('monthly')!r}")
            continue
        s = 0.0
        for line in breakdown:
            if line.get("exclusion_reason"):
                continue
            v = num(line.get(field))
            if v is None:
                FAILS.append(f"{line.get('service_id')!r}: {field} is not numeric ({line.get(field)!r}) and carries no exclusion_reason")
                continue
            s += v
        check(
            close(total, s, rel),
            f"projected_costs.{key}.monthly is {total} but its non-excluded lines sum to {round(s, 2)}. "
            f"A total that does not reconcile is a gate failure, not a rounding note.",
        )
        # excluded lines must NOT be in the sum
        for sid in excluded_ids:
            line = by_id.get(sid) or {}
            v = num(line.get(field))
            if v:
                check(
                    not close(total, s + v, rel) or close(total, s, rel),
                    f"{key} total appears to include the excluded line {sid!r}",
                )

    tt = exp["totals"]
    banded("projected_costs.lift.monthly", lift.get("monthly"), tt["min"], tt["max"], tt["basis"])
    banded("projected_costs.right_sized.monthly", rs.get("monthly"), tt["min"], tt["max"], tt["basis"])
    for key, obj in (("lift", lift), ("right_sized", rs)):
        g = num(obj.get("monthly"))
        if g is not None and close(g, float(tt["must_not_be"]), 0.01):
            FAILS.append(f"projected_costs.{key}.monthly is {g}, the known-wrong total. {tt['must_not_be_why']}")

    # ---------------- TIER 1: a rate that describes the wrong configuration ----------------
    rcm = exp["rate_configuration_mismatch"]
    rl = by_id.get(rcm["service_id"]) or {}
    got_rcm = rl.get("rate_configuration_mismatch")
    check(
        isinstance(got_rcm, dict),
        f"{rcm['service_id']!r} has no rate_configuration_mismatch. {rcm['_why']}",
    )
    if isinstance(got_rcm, dict):
        for k in rcm["required_keys"]:
            check(k in got_rcm, f"{rcm['service_id']}.rate_configuration_mismatch is missing {k!r}")
        check(
            got_rcm.get("direction") == rcm["expected_direction"],
            f"{rcm['service_id']}: direction is {got_rcm.get('direction')!r}, expected "
            f"{rcm['expected_direction']!r} — a Multi-AZ rate on a single-AZ design overstates",
        )
    check(
        rl.get("is_ceiling") is rcm["expected_is_ceiling"],
        f"{rcm['service_id']}.is_ceiling must be {rcm['expected_is_ceiling']}: the figure is an upper "
        f"bound for that line even while the TOTAL is a lower bound. {rcm['_mixed_direction_why']}",
    )
    v = num(rl.get("right_sized_monthly"))
    if v is not None:
        for spec in lb["priced"]:
            if spec["service_id"] == rcm["service_id"]:
                if close(v, round(spec["expected"] / 2, 2), 0.02):
                    FAILS.append(f"{rcm['service_id']}: {v} is the Multi-AZ rate halved. {rcm['must_not_be_halved']}")
                break
    check(
        rl.get("exclusion_reason") is None,
        f"{rcm['service_id']} was excluded. {rcm['must_not_be_excluded']}",
    )
    # Must be ONE condition naming both the service and the mismatch. Matching "single-az"
    # anywhere in conditions[] was too weak: the availability condition already says
    # "answered single-az against a ZoneRedundant source", so dropping the repricing
    # condition entirely still passed.
    conds_l = [str(c).lower() for c in ((est.get("recommendation") or {}).get("conditions") or [])]
    check(
        any(rcm["service_id"].lower() in c and rcm["condition_must_mention"].lower() in c for c in conds_l),
        f"recommendation.conditions must carry ONE condition naming both {rcm['service_id']!r} and "
        f"{rcm['condition_must_mention']!r} — repricing it is the highest-value correction available "
        f"to this estimate and is invisible from the number. A mention of "
        f"{rcm['condition_must_mention']!r} in some other condition does not satisfy this.",
    )

    # ---------------- TIER 1: floor propagation ----------------
    fp = exp["floor_propagation"]
    any_excluded = any(line.get("exclusion_reason") for line in breakdown)
    check(
        any_excluded == fp["expected_is_floor"],
        f"expected {'some' if fp['expected_is_floor'] else 'no'} line to carry an exclusion_reason",
    )
    for key, obj in (("lift", lift), ("right_sized", rs)):
        check(
            obj.get("is_floor") is any_excluded,
            f"projected_costs.{key}.is_floor is {obj.get('is_floor')!r} but "
            f"{'some' if any_excluded else 'no'} line is excluded. {fp['_why']}",
        )

    # ---------------- TIER 2 + TIER 1: the rightsizing delta ----------------
    rd = cc.get("rightsizing_delta") or {}
    spec = exp["rightsizing_delta"]
    lm, rm, dm = num(lift.get("monthly")), num(rs.get("monthly")), num(rd.get("monthly"))
    if None not in (lm, rm, dm):
        check(
            close(dm, lm - rm, rel),
            f"rightsizing_delta.monthly is {dm} but lift - right_sized is {round(lm - rm, 2)}",
        )
    explanation = (rd.get("explanation") or "").strip()
    check(
        len(explanation) >= spec["explanation_min_length"],
        f"rightsizing_delta.explanation is {len(explanation)} chars, needs >= {spec['explanation_min_length']}. "
        f"{spec['must_not_be_bare_zero']}",
    )
    check(
        any(t.lower() in explanation.lower() for t in spec["explanation_must_mention_any"]),
        f"rightsizing_delta.explanation must say WHY the delta is what it is -- expected it to mention one of "
        f"{spec['explanation_must_mention_any']}. {spec['must_not_be_bare_zero']}",
    )
    check(
        rd.get("basis") in spec["allowed_basis"],
        f"rightsizing_delta.basis is {rd.get('basis')!r}, expected one of {spec['allowed_basis']}",
    )
    if spec["declared_waste_must_be_recorded"]:
        check(
            bool(rd.get("declared_waste_found")),
            "rightsizing_delta.declared_waste_found is empty. The idle Windows plan with zero apps is the "
            f"estate's clearest cost finding. {spec['declared_waste_why']}",
        )
    # the idle plan must not ALSO be an optimization opportunity
    opps = flatten(est.get("optimization_opportunities") or [])
    check(
        "idle" not in opps.lower(),
        f"the idle plan appears in optimization_opportunities. {spec['declared_waste_must_not_be_double_counted']}",
    )

    # ---------------- TIER 1: the licensing delta, gated on Clarify ----------------
    ls = exp["licensing_delta"]
    fired = None
    if prefs:
        cur = prefs
        for seg in ls["preferences_gate_path"].split("."):
            cur = cur.get(seg) if isinstance(cur, dict) else None
        fired = cur
        check(
            fired == ls["expected_fired"],
            f"preferences {ls['preferences_gate_path']} is {fired!r}, expected {ls['expected_fired']!r} "
            f"(the fixture's own premise -- if this fails the golden inputs drifted)",
        )
    ld = est.get("licensing_delta")
    gate = ls["expected_fired"] if fired is None else fired
    if gate:
        check(ld is not None, f"licensing_delta is absent but preferences {ls['preferences_gate_path']} is true. {ls['_why']}")
    else:
        check(ld is None, f"licensing_delta is present but preferences {ls['preferences_gate_path']} is not true. {ls['_why']}")
    if isinstance(ld, dict):
        check(
            ld.get("windows_model") == ls["expected_windows_model"],
            f"licensing_delta.windows_model is {ld.get('windows_model')!r}, expected {ls['expected_windows_model']!r}",
        )
        check(
            ld.get("monthly_delta") is None,
            f"licensing_delta.monthly_delta is {ld.get('monthly_delta')!r} and must be null. {ls['monthly_delta_must_be_null_why']}",
        )
        check(bool(ld.get("delta_basis")), "licensing_delta.delta_basis must state why monthly_delta is null")
        check(
            ld.get("ahub_in_use") == ls["expected_ahub_in_use"],
            f"licensing_delta.ahub_in_use is {ld.get('ahub_in_use')!r}, expected {ls['expected_ahub_in_use']!r}",
        )
        blk = ls["blockers_must_not_be_priced"]
        for entry in ld.get("blockers_are_not_costs") or []:
            if isinstance(entry, str) and blk["code"] in entry:
                break
        else:
            FAILS.append(f"licensing_delta must record the {blk['code']} blocker as a non-cost. {blk['_why']}")
        # a blocker must never carry a dollar figure
        for entry in ld.get("blockers_are_not_costs") or []:
            check("$" not in str(entry), f"a blocker entry carries a dollar figure: {entry!r}. {blk['_why']}")

    # ---------------- TIER 1: the baseline rung ----------------
    bs = exp["baseline"]
    cur_costs = est.get("current_costs") or {}
    check(
        cur_costs.get("source") in bs["allowed_sources"],
        f"current_costs.source is {cur_costs.get('source')!r}, expected one of {bs['allowed_sources']}",
    )
    check(
        cur_costs.get("source") == bs["expected_source"],
        f"current_costs.source is {cur_costs.get('source')!r}, expected {bs['expected_source']!r}",
    )
    if bs["baseline_note_required"] and cur_costs.get("source") != "cost_management_export":
        check(bool(cur_costs.get("baseline_note")), "current_costs.baseline_note is required for a non-invoice baseline")
    if prefs:
        cur = prefs
        for seg in bs["preferences_source_path"].split("."):
            cur = cur.get(seg) if isinstance(cur, dict) else None
        want = num(cur)
        got = num(cur_costs.get("azure_monthly"))
        if want is not None and got is not None:
            check(
                close(got, want, 1e-6),
                f"current_costs.azure_monthly is {got} but preferences {bs['preferences_source_path']} is {want}",
            )

    # ---------------- TIER 1: the reservation rule is present and vacuous ----------------
    rr = exp["reservation_rule"]
    subs = est.get(rr["required_path"])
    check(
        isinstance(subs, list),
        f"{rr['required_path']} must be present as an array. {rr['_why']}",
    )
    if isinstance(subs, list):
        check(
            len(subs) == rr["expected_length"],
            f"{rr['required_path']} has {len(subs)} entr(ies), expected {rr['expected_length']}. {rr['_why']}",
        )

    # ---------------- TIER 1: region and staleness ----------------
    rg = exp["region"]
    ps = est.get("pricing_source") or {}
    dtr = design.get(rg["design_target_region_path"]) if design else None
    if dtr:
        check(
            dtr == rg["expected_target_region"],
            f"design {rg['design_target_region_path']} is {dtr!r}, expected {rg['expected_target_region']!r} "
            f"(fixture premise -- the golden inputs drifted if this fails)",
        )
    check(
        ps.get("region_mismatch") is True,
        f"pricing_source.region_mismatch must be true. {rg['_why']}",
    )
    blob = flatten(est)
    check(rg["expected_cache_region"] in blob, f"the artifact must state the cache region {rg['expected_cache_region']!r}")
    check(rg["expected_target_region"] in blob, f"the artifact must state the target region {rg['expected_target_region']!r}")

    st = exp["staleness"]
    check(
        ps.get("status") in st["allowed_status"],
        f"pricing_source.status is {ps.get('status')!r}, expected one of {st['allowed_status']}",
    )
    check(
        ps.get("status") == st["expected_status"],
        f"pricing_source.status is {ps.get('status')!r}, expected {st['expected_status']!r}. {st['_why']}",
    )

    # ---------------- TIER 1: recommendation ----------------
    rc = exp["recommendation"]
    reco = est.get("recommendation") or {}
    check(
        reco.get("outcome") in rc["allowed_outcomes"],
        f"recommendation.outcome is {reco.get('outcome')!r}, expected one of {rc['allowed_outcomes']}",
    )
    check(
        reco.get("outcome") == rc["expected_outcome"],
        f"recommendation.outcome is {reco.get('outcome')!r}, expected {rc['expected_outcome']!r}. {rc['must_not_be_why']}",
    )
    conds = reco.get("conditions") or []
    if reco.get("outcome") == "conditional_go":
        check(
            len(conds) >= rc["conditions_min_length"],
            f"recommendation.conditions has {len(conds)} entr(ies), expected >= {rc['conditions_min_length']} "
            f"for a conditional_go",
        )
        cond_blob = flatten(conds).lower()
        check(
            any(t.lower() in cond_blob for t in rc["conditions_must_mention_any"]),
            f"conditions must name the unpriced/floor problem -- expected one of {rc['conditions_must_mention_any']}",
        )
        check(
            rg["condition_must_mention"].lower() in cond_blob,
            f"conditions must carry the region mismatch (expected {rg['condition_must_mention']!r}). {rg['_why']}",
        )
    if rc["stay_requires_path_stay"] and reco.get("outcome") == "stay":
        check(reco.get("path") == "stay", "outcome 'stay' only ever accompanies path 'stay'")
    check(
        len(reco.get("would_flip_if") or []) >= rc["would_flip_if_min_length"],
        "recommendation.would_flip_if must name at least one change that would alter the outcome",
    )
    db = reco.get("decision_basis") or {}
    for k in rc["decision_basis_required_keys"]:
        check(k in db, f"recommendation.decision_basis is missing {k!r}")

    # ---------------- TIER 1: complexity ----------------
    cx = exp["complexity"]
    check(
        est.get("complexity_tier") in cx["allowed_tiers"],
        f"complexity_tier is {est.get('complexity_tier')!r}, expected one of {cx['allowed_tiers']}",
    )
    check(
        est.get("complexity_tier") == cx["expected_tier"],
        f"complexity_tier is {est.get('complexity_tier')!r}, expected {cx['expected_tier']!r}. {cx['_why']}",
    )
    if cx["inputs_required"]:
        check(bool(est.get("complexity_inputs")), "complexity_inputs must record what the tier was derived from")

    # ---------------- TIER 1: accounting -- every designed service, exactly once ----------------
    ac = exp["accounting"]
    dsvc = [s.get("service_id") for s in (design.get("services") or [])]
    if design:
        check(
            len(dsvc) == ac["expected_design_service_count"],
            f"the design has {len(dsvc)} services[], expected {ac['expected_design_service_count']} "
            f"(fixture premise -- the golden inputs drifted if this fails)",
        )
        for sid in dsvc:
            check(sid in by_id, f"designed service {sid!r} has no line in the cost breakdown. {ac['_why']}")
    check(
        len(breakdown) == ac["expected_breakdown_line_count"],
        f"breakdown has {len(breakdown)} lines, expected {ac['expected_breakdown_line_count']}. {ac['_line_count_why']}",
    )
    dm_spec = ac["deferred_must_have_no_cost_line"]
    for d in design.get("deferred") or []:
        if d.get("azure_type") == dm_spec["azure_type"]:
            check("confidence" not in d, "a deferred entry must not carry confidence")
            break

    # ---------------- TIER 1: run_mode, the consent gate ----------------
    rmspec = exp["run_mode"]
    rm = ph.get("run_mode")
    check(rm is not None, f"run_mode is absent from .phase-status.json. {rmspec['_why']}")
    check(rm in rmspec["allowed"], f"run_mode is {rm!r}, expected one of {rmspec['allowed']}")
    check(
        rm == rmspec["expected"],
        f"run_mode is {rm!r}, expected {rmspec['expected']!r} for {rmspec['golden_branch']}. "
        f"{rmspec['must_not_be_decide_and_execute_why']}",
    )
    check(
        ph.get("current_phase") == rmspec["expected_current_phase"],
        f"current_phase is {ph.get('current_phase')!r}, expected {rmspec['expected_current_phase']!r}",
    )
    check(
        (ph.get("phases") or {}).get("generate") == rmspec["expected_generate_phase"],
        f"phases.generate is {(ph.get('phases') or {}).get('generate')!r}, "
        f"expected {rmspec['expected_generate_phase']!r}. {rmspec['_why_generate_pending']}",
    )

    # ---------------- TIER 1: the closed warning vocabulary ----------------
    wv = exp["warning_vocabulary"]
    src = HERE / wv["source_file_relpath"]
    declared = set()
    if src.exists():
        # read the codes out of the skill file's table, rather than restating them here
        declared = set(re.findall(r"^\| `([a-z0-9_]+)` +\|", src.read_text(), re.M))
        check(bool(declared), f"could not read any warning codes from {wv['source_file_relpath']}")
    else:
        FAILS.append(f"cannot reach {wv['source_file_relpath']} to read the closed vocabulary")
    warnings = est.get("warnings") or []
    for w in warnings:
        if not isinstance(w, dict):
            FAILS.append(f"warnings[] entry is a bare string: {str(w)[:60]!r}. {wv['must_not_be']}")
            continue
        code = w.get("code")
        check(bool(code), f"a warnings[] entry has no code. {wv['must_not_be']}")
        if code and declared:
            check(
                code in declared,
                f"warning code {code!r} is not a row in estimate-infra.md's closed vocabulary. "
                f"{wv['must_not_be']}",
            )
    seen = {w.get("code") for w in warnings if isinstance(w, dict)}
    for code in wv["expected_codes_present"]:
        check(code in seen, f"expected a {code!r} warning on this estate and found none")

    # ---------------- TIER 1: compliance was never asked ----------------
    cna = exp["compliance_never_asked"]
    got_comp = (est.get("complexity_inputs") or {}).get("compliance", "__absent__")
    check(
        got_comp is None,
        f"complexity_inputs.compliance is {got_comp!r} and must be null. {cna['must_not_be_why']}",
    )

    # ---------------- TIER 1: forbidden content ----------------
    fb = exp["forbidden"]
    for s in fb["substrings"]:
        check(s not in blob, f"forbidden substring {s!r} appears in the artifact. {fb['_app_runner_why']}")
    ng = fb["no_graviton_opportunity"]
    for o in est.get("optimization_opportunities") or []:
        check(
            o.get("type") not in ng["forbidden_opportunity_types"],
            f"optimization_opportunities carries a {o.get('type')!r} entry. {ng['_why']}",
        )
    for s in ng["forbidden_substrings_in_opportunities"]:
        check(
            s not in opps,
            f"{s!r} appears in optimization_opportunities. {ng['_why']}",
        )
    nl = fb["no_labor_costs"]

    # Scan the VALUE-BEARING content only. An artifact that correctly states "no
    # engineer-weeks appear here" necessarily contains the forbidden words, and an
    # oracle that fails it for saying so is the §16.1 defect: rejecting a correct
    # answer as fraud. So underscore-prefixed keys and the explicit disclaimers are
    # dropped before the scan.
    DISCLAIMER_KEYS = {"no_labor_costs", "no_dollar_values_assigned", "no_labour_costs"}

    def scrub(o):
        if isinstance(o, dict):
            return {k: scrub(v) for k, v in o.items() if not k.startswith("_") and k not in DISCLAIMER_KEYS}
        if isinstance(o, list):
            return [scrub(v) for v in o]
        return o

    cost_raw = flatten(
        scrub(
            {
                "migration_cost_considerations": est.get("migration_cost_considerations"),
                "projected_costs": pc,
                "cost_comparison": cc,
                "roi_analysis": est.get("roi_analysis"),
            }
        )
    )
    for s in nl["forbidden_substrings_in_costs"]:
        # An ALL-CAPS term is an acronym: match it whole-word and case-SENSITIVELY.
        # A case-insensitive substring match on "FTE" hits "aFTEr", "oFTEn" and "liFTEd",
        # which fails correct artifacts for containing ordinary English.
        if s.isupper():
            hit = re.search(rf"\b{re.escape(s)}\b", cost_raw) is not None
        else:
            hit = s.lower() in cost_raw.lower()
        check(not hit, f"{s!r} appears in a cost section. {nl['_why']}")

    # ---------------- TIER 2: the remaining relational identities ----------------
    az = num(cur_costs.get("azure_monthly"))
    for key, obj in (("lift", cc.get("lift") or {}), ("right_sized", cc.get("right_sized") or {})):
        aws = num(obj.get("aws_monthly"))
        md = num(obj.get("monthly_difference"))
        ad = num(obj.get("annual_difference"))
        src = num((lift if key == "lift" else rs).get("monthly"))
        if aws is not None and src is not None:
            check(close(aws, src, rel), f"cost_comparison.{key}.aws_monthly {aws} != projected_costs.{key}.monthly {src}")
        if None not in (aws, az, md):
            check(
                close(md, aws - az, rel),
                f"cost_comparison.{key}.monthly_difference is {md}, expected aws - azure = {round(aws - az, 2)} "
                f"(sign convention: difference = AWS minus Azure, so negative means AWS cheaper)",
            )
        if None not in (md, ad):
            check(close(ad, md * 12, rel), f"cost_comparison.{key}.annual_difference is {ad}, expected {round(md * 12, 2)}")

    fs = est.get("financial_summary") or {}
    rsd = num((cc.get("right_sized") or {}).get("monthly_difference"))
    sav = num(fs.get("monthly_savings_right_sized"))
    if None not in (rsd, sav):
        check(
            close(sav, -rsd, rel),
            f"financial_summary.monthly_savings_right_sized is {sav} but cost_comparison right_sized "
            f"monthly_difference is {rsd}. financial_summary uses savings = Azure - AWS, the OPPOSITE sign; "
            f"they must be negations of each other.",
        )

    # per-cluster sums to the right-sized total, and every cluster_id is real
    per_cluster = cc.get("per_cluster") or []
    if per_cluster:
        s = 0.0
        design_cluster_ids = {c.get("cluster_id") for c in (design.get("clusters") or [])}
        for entry in per_cluster:
            v = num(entry.get("right_sized_monthly"))
            if v is None:
                FAILS.append(f"per_cluster entry {entry.get('cluster_id')!r} has a non-numeric right_sized_monthly")
                continue
            s += v
            # estimate-infra.md: a $0.00 cluster figure needs its note, because a cluster
            # whose every line was excluded reads as free and is not -- it is unpriced.
            if v == 0.0:
                check(
                    bool((entry.get("note") or "").strip()),
                    f"per_cluster {entry.get('cluster_id')!r} is $0.00 with no note. "
                    f"A cluster whose every line was excluded is UNPRICED, not free, and the "
                    f"number alone cannot say which.",
                )
            cid = entry.get("cluster_id")
            if cid is not None and design_cluster_ids:
                check(
                    cid in design_cluster_ids,
                    f"per_cluster cluster_id {cid!r} does not appear in the design's clusters[]. "
                    f"Checked by MEMBERSHIP, not against literal strings, because cluster_id has no "
                    f"stability specification yet.",
                )
        total_rs = num(rs.get("monthly"))
        if total_rs is not None:
            check(
                close(s, total_rs, rel),
                f"per_cluster right_sized_monthly sums to {round(s, 2)} but projected_costs.right_sized.monthly "
                f"is {total_rs}. Every priced line belongs to exactly one cluster, or to the unattributed "
                f"estate-wide entry.",
            )

    # observability components must sum to its own figure
    obs = by_id.get("observability-cloudwatch")
    if obs and isinstance(obs.get("components"), dict):
        cs = sum(num(v) or 0.0 for v in obs["components"].values())
        ov = num(obs.get("right_sized_monthly"))
        if ov is not None:
            check(close(cs, ov, 1e-2), f"observability components sum to {round(cs, 2)} but the line is {ov}")

    if FAILS:
        print(f"FAIL — {len(FAILS)} problem(s)")
        for f in FAILS:
            print(" -", f)
        return 1
    print("PASS — estimate matches expected-estimate.json (tier 1 exact, tier 2 relational, tier 3 banded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
