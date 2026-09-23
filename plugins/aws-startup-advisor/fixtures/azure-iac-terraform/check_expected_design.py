#!/usr/bin/env python3
"""Assert an azure-to-aws Design run (pass 1) over the azure-iac-terraform corpus.

The external oracle for the mapping algorithm, and the companion to
check_expected_iac_terraform.py. It exists for the same reason: the DSL's `_assert`
postconditions verify SHAPE, never correctness, and the model both produces
`aws-design.json` and evaluates the assertions against it. A design that routes a
Mongo-API Cosmos account to DynamoDB, an SMB share to EFS, and a Kafka-enabled Event
Hubs namespace to Kinesis is well-formed, satisfies every postcondition, and is wrong
in three places that each cost a rewrite.

Every check pins a fact where a plausible improvisation and the correct answer DIVERGE:

  * the three protocol/API-conditioned Direct Mappings rows, each of which has a
    famous wrong answer (DynamoDB, EFS, Kinesis);
  * the App Service Plan fan-in, where a per-app mapping is a 5x estimate error;
  * the untranslated cost-bearing type, where warn-and-skip is the silent failure;
  * the `deterministic` label itself, checked in BOTH directions against the table;
  * the table's own row set, because a design is only as trustworthy as the rows it
    claims to have read.

Facts a model gets right by accident are deliberately NOT asserted.

Identity is the Terraform ADDRESS, resolved to an `azure_id` through the run's own
inventory. Design artifacts key on `azure_id`, but most Terraform-sourced ids in this
corpus carry a synthetic `tf:<local>` name segment (every resource is named with
${var.prefix}), so hard-coding them here would couple these expectations to an id
reconstruction that is expected to change when the live `az` path lands.

Usage:
    python3 check_expected_design.py <migration_run_dir>

Exits 0 on PASS, 1 on FAIL. Stdlib only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAILS: list[str] = []
NOTES: list[str] = []

SERVERFARMS = "Microsoft.Web/serverfarms"
SITES = "Microsoft.Web/sites"


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def load(path: Path, label: str) -> dict | None:
    if not path.exists():
        FAILS.append(f"missing {label} at {path}")
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        FAILS.append(f"{label} is not valid JSON: {e}")
        return None


def real_keys(d: dict) -> list[str]:
    """Table keys, minus the leading-underscore documentation keys."""
    return [k for k in d if not k.startswith("_")]


# --------------------------------------------------------------------------- table


def check_table(table: dict, exp: dict) -> None:
    """Validate the disposition table itself, before trusting a design that cites it.

    A design row saying `confidence: deterministic, fast_path_row: X` is only
    meaningful if X exists. And the precedence order is only coherent if a type
    resolves to at most one disposition.
    """
    spec = exp["table_self_checks"]
    direct = table.get("direct_mappings") or {}
    skips = table.get("skip_mappings") or {}
    gates = table.get("specialist_gates") or {}

    for t in spec["required_direct_rows"]:
        check(
            t in direct,
            f"direct_mappings has no row for {t!r}. {spec['_required_direct_rows_why']}",
        )
    for t in spec["must_not_be_direct_rows"]:
        check(
            t not in direct,
            f"{t!r} is a direct_mappings row and must not be. "
            f"{spec['_must_not_be_direct_rows_why']}",
        )
    for t in spec["required_skip_rows"]:
        check(t in skips, f"skip_mappings has no row for {t!r}")
    for t in spec["required_gate_rows"]:
        check(t in gates, f"specialist_gates has no row for {t!r}")

    # Precedence invariant: at most one disposition per canonical type. A conditional
    # gate key carries a '#suffix' (Microsoft.Compute/virtualMachines#sql_on_vm) and is
    # deliberately exempt — it fires on config, not on the type, so the base type
    # legitimately also lives on the rubric path.
    seen: dict[str, str] = {}
    for label, tbl in (("direct_mappings", direct), ("skip_mappings", skips), ("specialist_gates", gates)):
        for t in real_keys(tbl):
            if "#" in t:
                continue
            if t in seen:
                FAILS.append(
                    f"{t!r} appears in both {seen[t]} and {label}. A canonical type must "
                    f"resolve to AT MOST ONE disposition — two makes the precedence order "
                    f"depend on iteration order rather than on the documented sequence."
                )
            seen[t] = label

    banned = spec["banned_substring"]
    check(
        banned not in json.dumps(table),
        f"{banned!r} appears in the disposition table. {spec['_banned_substring_why']}",
    )
    NOTES.append(f"table: {len(real_keys(direct))} direct, {len(real_keys(skips))} skip, {len(real_keys(gates))} gate rows")


# ---------------------------------------------------------------------- design body


def entries(design: dict) -> list[dict]:
    """Every per-resource entry, whatever section it landed in."""
    out: list[dict] = []
    for section in ("services", "pending_rubric", "deferred"):
        for e in design.get(section) or []:
            if isinstance(e, dict):
                out.append({**e, "_section": section})
    return out


def check_deterministic(design: dict, table: dict, id_of: dict[str, str], exp: dict) -> None:
    direct = table.get("direct_mappings") or {}
    services = {e.get("azure_id"): e for e in (design.get("services") or []) if isinstance(e, dict)}
    want_label = exp["confidence"]["expected_value"]

    for tf_addr, spec in exp["deterministic_mappings"].items():
        if tf_addr.startswith("_"):
            continue
        aid = id_of.get(tf_addr)
        if aid is None:
            FAILS.append(f"no inventory resource with Terraform address {tf_addr!r} — cannot check its mapping")
            continue
        e = services.get(aid)
        if e is None:
            FAILS.append(
                f"{tf_addr!r}: no services[] entry. It matches a Direct Mappings row, so it "
                f"must be mapped rather than deferred, skipped, or left pending."
            )
            continue

        got = e.get("aws_service")
        check(
            got == spec["aws_service"],
            f"{tf_addr!r}: aws_service is {got!r}, expected {spec['aws_service']!r}."
            + (f" {spec['why']}" if spec.get("why") else ""),
        )
        for bad in spec.get("must_not_be", []):
            check(
                got != bad,
                f"{tf_addr!r}: aws_service is {bad!r}, which is the plausible-but-wrong answer. "
                + (spec.get("why") or ""),
            )
        check(
            e.get("confidence") == want_label,
            f"{tf_addr!r}: confidence is {e.get('confidence')!r}, expected {want_label!r} — it "
            f"came from a table row, so no rubric ran.",
        )

    # The direction that catches a fabricated label: anything claiming `deterministic`
    # must name a type that really is in the table, with a target the row allows.
    for e in design.get("services") or []:
        if e.get("confidence") != want_label:
            continue
        t = e.get("azure_type")
        row = direct.get(t)
        if row is None:
            FAILS.append(
                f"{t!r} is labelled {want_label!r} but has NO direct_mappings row. This is the "
                f"signature of an improvised label: the target may even be reasonable, but it "
                f"came from a prior rather than a table, so it is unreproducible and the "
                f"user-facing 'Standard pairing' claim is false."
            )
            continue
        allowed = {row.get("aws_service")} | {a.get("aws_service") for a in (row.get("alternatives") or [])}
        check(
            e.get("aws_service") in allowed,
            f"{t!r} is labelled {want_label!r} with aws_service {e.get('aws_service')!r}, which "
            f"is not the row's target or any of its alternatives ({sorted(x for x in allowed if x)}).",
        )
        check(
            e.get("confidence") in exp["confidence"]["allowed_values"],
            f"{t!r}: confidence {e.get('confidence')!r} is not one of {exp['confidence']['allowed_values']}",
        )


def check_fan_in(design: dict, inv: dict, id_of: dict[str, str], exp: dict) -> None:
    spec = exp["app_service_plan_fan_in"]
    all_entries = entries(design)

    plans = [e for e in all_entries if e.get("azure_type") == SERVERFARMS]
    check(
        len(plans) == spec["expected_compute_unit_count"],
        f"{len(plans)} {SERVERFARMS} entr(ies), expected {spec['expected_compute_unit_count']} — "
        f"one compute unit per PLAN. {spec['_why']}",
    )

    sites = [e for e in all_entries if e.get("azure_type") == SITES]
    check(
        len(sites) == spec["expected_site_entry_count"],
        f"{len(sites)} {SITES} entr(ies) in services[]/pending_rubric[]/deferred[], expected "
        f"{spec['expected_site_entry_count']}. {spec['_expected_site_entry_count_why']} "
        f"{spec['_why']}",
    )

    by_id = {e.get("azure_id"): e for e in all_entries}
    for key, want_count in (
        ("web_plan_tf_address", spec["web_plan_expected_hosted_app_count"]),
        ("idle_plan_tf_address", spec["idle_plan_expected_hosted_app_count"]),
    ):
        aid = id_of.get(spec[key])
        plan = by_id.get(aid)
        if plan is None:
            FAILS.append(f"no design entry for plan {spec[key]!r}")
            continue
        hosted = plan.get("hosted_app_azure_ids")
        if hosted is None:
            FAILS.append(
                f"plan {spec[key]!r} has no hosted_app_azure_ids. It is the record of WHICH apps "
                f"fanned in; without it the one-compute-unit-per-plan rule cannot be audited, and "
                f"an app silently dropped from the plan's aws_config is undetectable."
            )
            continue
        check(
            len(hosted) == want_count,
            f"plan {spec[key]!r} lists {len(hosted)} hosted app(s), expected {want_count}. "
            f"{spec['_why']}",
        )
        known = set(id_of.values())
        for h in hosted:
            check(h in known, f"plan {spec[key]!r} lists hosted app {h!r}, which is not in the inventory")

    web = by_id.get(id_of.get(spec["web_plan_tf_address"]))
    if web is not None:
        sizing = web.get("sizing_source") or web.get("aws_config") or {}
        check(
            sizing.get("sku_name") == spec["web_plan_expected_sku"],
            f"web plan sku is {sizing.get('sku_name')!r}, expected {spec['web_plan_expected_sku']!r} "
            f"— sizing comes from the plan's SKU, never from the app count",
        )
        check(
            sizing.get("worker_count") == spec["web_plan_expected_worker_count"],
            f"web plan worker_count is {sizing.get('worker_count')!r}, expected "
            f"{spec['web_plan_expected_worker_count']!r}",
        )

    warnings = design.get("warnings") or []
    consumed = [w for w in warnings if w.get("code") == spec["consumed_app_warning_code"]]
    check(
        len(consumed) == spec["expected_consumed_app_count"],
        f"{len(consumed)} {spec['consumed_app_warning_code']!r} warning(s), expected "
        f"{spec['expected_consumed_app_count']} — one per app consumed by a plan. Every site must "
        f"be accounted for; an app with no entry and no warning is indistinguishable from one the "
        f"design forgot.",
    )

    idle_aid = id_of.get(spec["idle_plan_tf_address"])
    check(
        any(w.get("code") == spec["idle_plan_warning_code"] and w.get("azure_id") == idle_aid for w in warnings),
        f"no {spec['idle_plan_warning_code']!r} warning for {spec['idle_plan_tf_address']!r}. A plan "
        f"with zero apps is purchased capacity with no workload — money already being spent, and a "
        f"cost-optimization finding the customer cannot get anywhere else.",
    )


def check_unknown_stop(design: dict, exp: dict) -> None:
    """The derived type must be DEFERRED — not halted on, and not silently skipped."""
    spec = exp["unknown_type_stop"]
    halt = design.get("halt")
    blocking = (halt or {}).get("blocking") or [] if isinstance(halt, dict) else []

    if spec.get("halt_required"):
        if not isinstance(halt, dict):
            FAILS.append(f"no `halt` object, and one is required. {spec['_why']}")
            return
        hit = [b for b in blocking
               if b.get("kind") == spec["expected_halt_kind"]
               and spec["expected_identifier_substring"] in json.dumps(b)]
        check(bool(hit),
              f"halt.blocking has no {spec['expected_halt_kind']!r} entry naming "
              f"{spec['expected_identifier_substring']!r}. {spec['_why']}")
    else:
        forbidden = spec.get("forbidden_halt_kind")
        bad = [b for b in blocking if b.get("kind") == forbidden]
        check(not bad,
              f"halt.blocking carries a {forbidden!r} entry {bad!r}, but that halt is "
              f"UNREACHABLE on this corpus now. {spec['_forbidden_halt_why']}")

    disp = spec.get("derived_type_disposition")
    if disp:
        want_type = disp["azure_type"].lower()
        where = disp["expected_in"]
        pool = design.get(where) or []
        hit = [e for e in pool if (e.get("azure_type") or "").lower() == want_type]
        check(bool(hit),
              f"{disp['azure_type']} is not in {where}[]. A derived type must reach a real "
              f"disposition — mapped, or deferred — never vanish. {disp['_why']}")
        for e in hit:
            check("confidence" not in e,
                  f"{disp['azure_type']} is deferred but carries a confidence field. "
                  f"A deferral did not come from a rubric (13.1e).")

    ident = spec.get("identifier_substring") or spec.get("expected_identifier_substring")
    for w in design.get("warnings") or []:
        if w.get("code") in spec["must_not_appear_as_benign_skip_codes"]:
            check(
                ident not in json.dumps(w).lower(),
                f"{ident!r} is recorded as a benign skip ({w.get('code')!r}). A cost-bearing "
                f"derived type may be MAPPED or DEFERRED, never quietly skipped. "
                f"{spec['_must_not_appear_why']}",
            )


def check_pending_rubric(design: dict, id_of: dict[str, str], exp: dict) -> None:
    """Pass 2 exists now, so pending_rubric[] must be EMPTY.

    This is the inverse of what it checked at build step 3. Then, a resource mapped past a
    missing rubric file was improvisation. Now, a resource still PARKED as pending is a run
    that did not load rubric files that are on disk — the same defect from the other side.
    """
    spec = exp["missing_rubric_halt"]
    pending = design.get("pending_rubric") or []
    check(
        len(pending) == spec["expected_pending_rubric_count"],
        f"pending_rubric[] has {len(pending)} entr(ies), expected "
        f"{spec['expected_pending_rubric_count']}: "
        f"{[e.get('azure_type') for e in pending]}. {spec['_why']}",
    )
    for b in (design.get("halt") or {}).get("blocking") or []:
        check(
            b.get("kind") != spec["forbidden_halt_kind"],
            f"halt.blocking still carries a {spec['forbidden_halt_kind']!r} entry "
            f"({b.get('identifier')!r}), but that file is on disk. {spec['_why']}",
        )


def check_rubric_mappings(design: dict, id_of: dict[str, str], exp: dict) -> None:
    spec = exp.get("rubric_mappings")
    if not spec:
        return
    services = {e.get("azure_id"): e for e in (design.get("services") or []) if isinstance(e, dict)}
    want_conf = spec["expected_confidence"]
    for tf_addr, row in spec.items():
        if tf_addr.startswith("_") or not isinstance(row, dict) or "aws_service" not in row:
            continue
        aid = id_of.get(tf_addr)
        if aid is None:
            FAILS.append(f"no inventory resource with Terraform address {tf_addr!r}")
            continue
        e = services.get(aid)
        if e is None:
            FAILS.append(
                f"{tf_addr!r}: no services[] entry. Its rubric file is on disk, so it must be "
                f"MAPPED — not pending, not deferred. {row['why']}"
            )
            continue
        got = e.get("aws_service")
        check(
            got == row["aws_service"],
            f"{tf_addr!r}: aws_service is {got!r}, expected {row['aws_service']!r}. {row['why']}",
        )
        for bad in row.get("must_not_be", []):
            check(
                got != bad,
                f"{tf_addr!r}: aws_service is {bad!r}, the plausible-but-wrong answer. {row['why']}",
            )
        check(
            e.get("confidence") == want_conf,
            f"{tf_addr!r}: confidence is {e.get('confidence')!r}, expected {want_conf!r} — a rubric "
            f"ran, so it is not deterministic; that tier is only for fast-path rows.",
        )
        check(
            bool(e.get("rubric_applied")),
            f"{tf_addr!r}: no rubric_applied field, so which rubric produced this target is unauditable.",
        )


def check_architecture_default(design: dict, id_of: dict[str, str], exp: dict) -> None:
    spec = exp.get("architecture_default")
    if not spec:
        return
    services = {e.get("azure_id"): e for e in (design.get("services") or []) if isinstance(e, dict)}
    for tf_addr in spec["tf_addresses"]:
        e = services.get(id_of.get(tf_addr))
        if e is None:
            FAILS.append(f"no services[] entry for {tf_addr!r} — cannot check its architecture")
            continue
        cfg = e.get("aws_config") or {}
        # Scan only the architecture-bearing KEYS, not the whole config blob. A rationale
        # or a `graviton_reason` field that explains why Graviton was NOT chosen
        # legitimately contains the word, and a blunt substring check over the whole
        # object would push authors to stop explaining themselves — which is backwards,
        # because that explanation is the thing that stops the x86 default reading as a bug.
        arch_keys = [k for k in cfg if "architecture" in k.lower() or k.lower() in ("arch", "cpu")]
        arch_values = " ".join(str(cfg[k]) for k in arch_keys)
        check(
            bool(arch_keys),
            f"{tf_addr!r}: aws_config has no architecture field at all, so the x86_64 default "
            f"is unrecorded and unverifiable. {spec['_why']}",
        )
        check(
            spec["expected_value"] in arch_values,
            f"{tf_addr!r}: architecture field(s) {arch_keys} say {arch_values!r}, expected "
            f"{spec['expected_value']!r}. {spec['_why']}",
        )
        for bad in spec["forbidden_values"]:
            check(
                bad not in arch_values,
                f"{tf_addr!r}: an architecture field is set to {bad!r}. {spec['_why']}",
            )


def check_source_ha_finding(design: dict, id_of: dict[str, str], exp: dict) -> None:
    spec = exp.get("source_ha_finding")
    if not spec:
        return
    aid = id_of.get(spec["tf_address"])
    check(
        any(
            w.get("code") == spec["expected_warning_code"] and w.get("azure_id") == aid
            for w in (design.get("warnings") or [])
        ),
        f"no {spec['expected_warning_code']!r} warning for {spec['tf_address']!r}. {spec['_why']}",
    )


def check_canonical_type_coverage(exp: dict) -> None:
    """Every canonical type must have a disposition. Nothing else catches this.

    A coverage pass over the canonicalization table improves the INVENTORY and silently
    degrades DESIGN: each newly-translatable type is now discovered, finds no row, matches
    the cost-bearing namespace clause, and halts. The corpus cannot catch it — it contains
    a dozen types out of 137 — so the check has to read both files directly.
    """
    spec = exp.get("canonical_type_coverage")
    if not spec:
        return
    canon_path = HERE / spec["canon_relpath"]
    index_path = HERE / spec["index_relpath"]
    table_path = HERE / exp["fast_path_table_relpath"]
    for pth in (canon_path, index_path, table_path):
        if not pth.exists():
            FAILS.append(f"cannot check canonical-type coverage: missing {pth}")
            return

    # Only TABLE ROWS count. A type named in prose (an example, a trap explanation) is not a
    # canonicalization row and must not be demanded a disposition -- reading the whole file
    # made a prose example look like a row and reported a false orphan.
    canon = set()
    for line in canon_path.read_text().splitlines():
        if not line.startswith("|"):
            continue
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not re.search(r"`azurerm_[a-z0-9_]+`", cells[0]):
            continue
        for m in re.findall(r"`(Microsoft\.[A-Za-z0-9./]+)`", cells[1]):
            if "/" in m and m not in set(spec["exempt"]):
                canon.add(m)
    table = json.loads(table_path.read_text())
    disposed: set[str] = set()
    for section in ("direct_mappings", "skip_mappings", "specialist_gates", "hard_blockers"):
        disposed |= {t.split("#")[0] for t in real_keys(table.get(section) or {})}
    index_text = index_path.read_text()
    routed = {t for t in canon if f"`{t}`" in index_text}

    orphans = sorted(canon - disposed - routed)
    check(
        len(orphans) <= spec["max_orphans"],
        f"{len(orphans)} canonical type(s) have NO disposition — not a fast-path row, not an "
        f"index.md Reference row: {orphans}. {spec['_why']}",
    )
    NOTES.append(f"canonical-type coverage: {len(canon)} types, {len(orphans)} orphan(s)")


def check_index_reference_files_exist(exp: dict) -> None:
    """Every rubric file index.md ROUTES to must be on disk, or declared pending.

    index.md carries a HALT: a resource routed to a Reference file that is not on disk
    stops the design. That is correct behaviour, but it made two very different situations
    identical at runtime -- a rubric deliberately not written yet, and a filename typo. A
    typo would be diagnosed as "write that rubric", and the rubric already existed.

    No run input is needed, which is the point: this is a relationship between two files.
    """
    spec = exp.get("index_reference_files")
    if not spec:
        return
    index_path = HERE / spec["index_relpath"]
    refs_dir = HERE / spec["design_refs_relpath"]
    if not index_path.exists() or not refs_dir.is_dir():
        FAILS.append("cannot check index.md Reference files: index.md or design-refs/ missing")
        return

    pending = set(spec["known_pending"])
    on_disk = {p.name for p in refs_dir.glob("*.md")}

    routed: set[str] = set()
    for line in index_path.read_text().splitlines():
        if not line.startswith("|"):
            continue
        for f in re.findall(r"`([a-z0-9-]+\.md)`", line):
            routed.add(f)
    # vendored/ai/*.md live outside design-refs/ and are not this check's business
    routed -= {f for f in routed if f"`vendored/ai/{f}`" in index_path.read_text()}

    missing = sorted(f for f in routed if f not in on_disk and f not in pending)
    check(
        not missing,
        f"index.md routes to {missing} which are NOT on disk and NOT declared in "
        f"known_pending. Either the rubric is missing (write it, or add it to "
        f"known_pending with a reason) or the filename is wrong. {spec['_why']}",
    )

    # Anti-rot: a pending entry that has since been written must be removed, or the next
    # reader trusts a stale list.
    landed = sorted(f for f in pending if f in on_disk)
    check(
        not landed,
        f"known_pending still lists {landed}, but those files now EXIST. Remove them from "
        f"expected-design.json -- a pending list that is never pruned stops meaning anything.",
    )
    NOTES.append(
        f"index.md Reference files: {len(routed)} routed, {len(routed) - len(pending & routed)} on disk, "
        f"{sorted(pending & routed)} declared pending"
    )


def check_sizing_provenance(design: dict, exp: dict) -> None:
    """A size with no declared origin is indistinguishable from a looked-up one.

    Before the knowledge/design tables landed, every instance size in this golden was a
    model prior: sizing_source recorded the Azure INPUT so the output looked sourced, and
    nothing pinned the output. Two of the three were wrong -- S1 mapped to double its
    memory and GP_Standard_D2s_v3 to half of its. This check pins the corrected values and
    requires every sized entry to say where its number came from.
    """
    spec = exp.get("sizing_provenance")
    if not spec:
        return
    size_keys = set(spec["size_keys"])
    allowed = set(spec["allowed_provenance"])

    for entry in design.get("services") or []:
        cfg = entry.get("aws_config") or {}
        sized = sorted(size_keys & {k for k, v in cfg.items() if v is not None})
        if not sized:
            continue
        sid = entry.get("service_id")
        prov = entry.get("sizing_provenance")
        check(
            prov in allowed,
            f"{sid}: aws_config carries {sized} but sizing_provenance is {prov!r}, not one "
            f"of {sorted(allowed)}. {spec['_why']}",
        )

    pin_key = spec.get("pinned_by", "azure_id")
    for ident, want in spec["pinned"].items():
        entry = next((e for e in (design.get("services") or []) if e.get(pin_key) == ident), None)
        if entry is None:
            FAILS.append(
                f"no services[] entry with {pin_key}={ident!r} to check its pinned size. "
                f"NOTE: pins are keyed on {pin_key} deliberately -- service_id is per-run and "
                f"two valid runs name the same resource differently."
            )
            continue
        sid = entry.get("service_id")
        cfg = entry.get("aws_config") or {}
        for key, expected in want.items():
            if key.startswith("_"):
                continue
            check(
                cfg.get(key) == expected,
                f"{sid}.{key} is {cfg.get(key)!r}, expected {expected!r}. {want['_why']}",
            )
    NOTES.append(
        f"sizing_provenance: {len(spec['pinned'])} size(s) pinned against the knowledge/design tables"
    )


def check_routing_provenance(design: dict, exp: dict) -> None:
    """Every disposition must say how it was reached, and a DERIVED route is not deterministic.

    namespace_routing and child_type_rule exist so coverage can grow without an authored row
    per type. The risk is that a derived mapping looks identical to a curated one in the
    artifact. This makes the difference explicit and stops a derived route claiming the
    deterministic tier, which requires a direct_mappings row it does not have.
    """
    spec = exp.get("routing_provenance")
    if not spec:
        return
    allowed = set(spec["allowed"])
    derived = set(spec["derived"])
    counts: dict[str, int] = {}
    for entry in design.get("services") or []:
        sid = entry.get("service_id")
        prov = entry.get("routing_provenance")
        check(prov in allowed, f"{sid}: routing_provenance is {prov!r}, not one of {sorted(allowed)}. {spec['_why']}")
        counts[prov] = counts.get(prov, 0) + 1
        if prov in derived:
            check(
                entry.get("confidence") != "deterministic",
                f"{sid}: routing_provenance is {prov!r} (DERIVED) but confidence is "
                f"'deterministic'. That tier requires an authored direct_mappings row and a "
                f"fast_path_row naming it; a derived route cannot earn it.",
            )
    NOTES.append(f"routing_provenance: {counts}")


def check_namespace_routing_targets(exp: dict) -> None:
    """Every rubric file namespace_routing names must exist, or be declared pending.

    Same guard as check_index_reference_files_exist, for the second thing that can route a
    resource to a rubric. Adding a namespace rule that points at an unwritten file turns a
    STOP into a HALT and moves the failure rather than fixing it.
    """
    spec = exp.get("routing_provenance")
    pending_spec = exp.get("index_reference_files")
    if not spec or not pending_spec:
        return
    tbl_path = HERE / spec["namespace_routing_relpath"]
    refs_dir = HERE / spec["design_refs_relpath"]
    if not tbl_path.exists() or not refs_dir.is_dir():
        FAILS.append("cannot check namespace_routing targets: table or design-refs/ missing")
        return
    table = json.loads(tbl_path.read_text())
    rules = (table.get("namespace_routing") or {}).get("rules") or {}
    on_disk = {p.name for p in refs_dir.glob("*.md")}
    pending = set(pending_spec["known_pending"])
    missing = sorted({
        v["route"] for v in rules.values()
        if v.get("route") and v["route"] not in on_disk and v["route"] not in pending
    })
    check(
        not missing,
        f"namespace_routing routes to {missing}, which are NOT on disk and NOT in "
        f"known_pending. A namespace rule pointing at an unwritten rubric converts the "
        f"unknown-type STOP into a missing-rubric HALT -- it moves the failure, it does not fix it.",
    )
    NOTES.append(f"namespace_routing: {len(rules)} namespaces, all routes resolvable")


def _camel(sn: str) -> str:
    parts = sn.split("_")
    return parts[0] + "".join(x.capitalize() for x in parts[1:])


def _plural(w: str) -> str:
    if w.endswith("y") and not w.endswith(("ay", "ey", "oy", "uy")):
        return w[:-1] + "ies"
    if w.endswith(("s", "x", "z", "ch", "sh")):
        return w + "es"
    return w + "s"


def _segment_derivable(tf_type: str, arm_type: str) -> bool:
    """Would the pattern rule produce this ARM type's last segment from the azurerm name?"""
    suffix = tf_type[len("azurerm_"):]
    last = arm_type.split("/")[-1]
    cand = {_plural(_camel(suffix)), _camel(suffix)}
    for i in range(1, suffix.count("_") + 1):
        tail = "_".join(suffix.split("_")[i:])
        if tail:
            cand |= {_plural(_camel(tail)), _camel(tail)}
    return last.lower() in {x.lower() for x in cand}


def check_canonicalization_governance(exp: dict) -> None:
    """Cap the DERIVABLE rows so the exception list cannot become a coverage list again.

    The file reached 132 rows of which 104 were fully redundant. Derivation is now the
    default path, so a new row is only justified where derivation would be WRONG. Nothing
    else would notice the file quietly growing back.
    """
    spec = exp.get("canonicalization_governance")
    if not spec:
        return
    canon_path = HERE / spec["canon_relpath"]
    ns_path = HERE / spec["namespace_table_relpath"]
    if not canon_path.exists() or not ns_path.exists():
        FAILS.append("cannot check canonicalization governance: a source file is missing")
        return

    rows: list[tuple[str, str]] = []
    for line in canon_path.read_text().splitlines():
        if not line.startswith("|"):
            continue
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        arms = re.findall(r"`(Microsoft\.[A-Za-z0-9./]+)`", cells[1])
        tfs = re.findall(r"`(azurerm_[a-z0-9_]+)`", cells[0])
        if tfs and arms:
            rows += [(t, arms[0]) for t in tfs]

    derivable = [r for r in rows if _segment_derivable(*r)]
    divergent = [r for r in rows if not _segment_derivable(*r)]

    check(
        len(derivable) <= spec["max_derivable_rows"],
        f"{len(derivable)} DERIVABLE rows in arm-type-canonicalization.md, ceiling is "
        f"{spec['max_derivable_rows']}. A derivable row restates the pattern rule instead of "
        f"recording an exception. {spec['_max_derivable_why']}",
    )
    check(
        len(divergent) >= spec["min_divergent_rows"],
        f"only {len(divergent)} DIVERGENT rows, floor is {spec['min_divergent_rows']}. "
        f"Pruning has removed rows that carry information. {spec['_min_divergent_why']}",
    )

    if spec.get("require_all_namespaces_routable"):
        ns_rules = set(((json.loads(ns_path.read_text()).get("namespace_routing") or {}).get("rules") or {}))
        orphan_ns = sorted({a.split("/")[0] for _, a in rows} - ns_rules)
        check(
            not orphan_ns,
            f"namespaces {orphan_ns} appear in arm-type-canonicalization.md but NOT in "
            f"namespace_routing. Derivation cross-checks the namespace against that table, so "
            f"the two artefacts contradict each other. {spec['_require_all_namespaces_routable_why']}",
        )
    NOTES.append(
        f"canonicalization: {len(rows)} rows = {len(divergent)} divergent (kept) + "
        f"{len(derivable)} derivable (capped at {spec['max_derivable_rows']})"
    )


def check_halt_not_stale(design: dict, exp: dict) -> None:
    """An untranslated-type halt is stale if that type's namespace is now routable.

    Derivation resolves an unlisted type and only STOPs when the derived NAMESPACE is
    unrecognised. So a golden halting on a type whose namespace namespace_routing now
    carries is describing behaviour the skill no longer produces -- and every shape
    assertion still passes, because the artifact is well-formed. Only reading the rule and
    the artifact together catches it.
    """
    spec = exp.get("canonicalization_governance")
    if not spec or not spec.get("assert_halt_not_stale"):
        return
    ns_path = HERE / spec["namespace_table_relpath"]
    if not ns_path.exists():
        return
    ns_rules = set(((json.loads(ns_path.read_text()).get("namespace_routing") or {}).get("rules") or {}))
    canon = (HERE / spec["canon_relpath"]).read_text()

    for blocker in ((design.get("halt") or {}).get("blocking") or []):
        if blocker.get("kind") != "untranslated_terraform_type":
            continue
        m = re.match(r"(azurerm_[a-z0-9_]+)", blocker.get("identifier", ""))
        if not m:
            continue
        tf = m.group(1)
        if f"`{tf}`" in canon:
            FAILS.append(
                f"halt names {tf} as untranslated, but it IS in arm-type-canonicalization.md"
            )
            continue
        derived_ns = sorted(n for n in ns_rules if _plausible_namespace(tf, n))
        check(
            not derived_ns,
            f"STALE HALT: {tf} halts as untranslated, but derivation would place it in "
            f"{derived_ns} which namespace_routing RECOGNISES, so it now resolves instead of "
            f"stopping. This golden needs regenerating by a capability run. "
            f"{spec['_assert_halt_not_stale_why']}",
        )


def _plausible_namespace(tf_type: str, namespace: str) -> bool:
    """Would this azurerm type plausibly derive into this namespace? Conservative."""
    HINTS = {
        "Microsoft.Devices": ("iothub", "iot_"),
        "Microsoft.Maps": ("maps_",),
        "Microsoft.NotificationHubs": ("notification_hub",),
        "Microsoft.Kusto": ("kusto",),
        "Microsoft.HDInsight": ("hdinsight",),
        "Microsoft.Purview": ("purview",),
        "Microsoft.Relay": ("relay",),
        "Microsoft.NetApp": ("netapp",),
    }
    suffix = tf_type[len("azurerm_"):]
    return any(h in suffix for h in HINTS.get(namespace, ()))


def check_inline_os_disk(design: dict, exp: dict) -> None:
    """The VM's root volume must be in aws_config, and must not be its own service entry."""
    spec = exp.get("inline_os_disk")
    if not spec:
        return
    hits = [e for e in (design.get("services") or []) if e.get("aws_service") == spec["aws_service"]]
    check(bool(hits), f"no {spec['aws_service']} entry to check its root volume")
    for e in hits:
        cfg = e.get("aws_config") or {}
        rv = cfg.get(spec["required_aws_config_key"])
        check(
            isinstance(rv, dict),
            f"{e.get('service_id')}: aws_config has no {spec['required_aws_config_key']!r}. "
            f"{spec['_why']}",
        )
        for bad in spec["forbidden_keys"]:
            check(bad not in cfg,
                  f"{e.get('service_id')}: aws_config carries {bad!r}. {spec['_forbidden_why']}")
        if isinstance(rv, dict):
            check(rv.get("volume_type") == spec["expected_volume_type"],
                  f"root_volume.volume_type is {rv.get('volume_type')!r}, expected "
                  f"{spec['expected_volume_type']!r} — a tier_mapping lookup, not a judgement.")
            if spec.get("size_gib_must_be_null"):
                check(rv.get("size_gib") is None,
                      f"root_volume.size_gib is {rv.get('size_gib')!r}, expected null. The source "
                      f"sets no disk_size_gb, so the size is the image default and is not "
                      f"discoverable — a remembered number would be priced as fact.")
    forbidden_type = spec["must_not_be_own_service_entry"]
    own = [e for e in (design.get("services") or []) if e.get("azure_type") == forbidden_type]
    check(not own,
          f"{forbidden_type} appears as its own services[] entry {[e.get('service_id') for e in own]}. "
          f"{spec['_must_not_why']}")


def check_cluster_pattern_status(design: dict, exp: dict) -> None:
    """Assert the honest 'no pattern catalog' state, not a plausible architecture string.

    design.md's cluster postcondition demands target_architecture while patterns.md does
    not exist. An agent optimising for a green gate writes a convincing string there and
    nothing downstream can catch it, so the honest state has to be BOTH expressible and
    asserted.
    """
    spec = exp.get("cluster_pattern_status")
    if not spec:
        return
    clusters = {c.get("cluster_id"): c for c in (design.get("clusters") or []) if isinstance(c, dict)}
    for cid in spec["expected_cluster_ids"]:
        c = clusters.get(cid)
        if c is None:
            FAILS.append(f"no clusters[] entry for {cid!r}. {spec['_why']}")
            continue
        check(
            c.get("pattern_status") == spec["expected_status"],
            f"cluster {cid!r}: pattern_status is {c.get('pattern_status')!r}, expected "
            f"{spec['expected_status']!r} — design-refs/patterns.md is not on disk, so no "
            f"recognition was ATTEMPTED, which is a different fact from 'nothing matched'.",
        )
        if spec.get("target_architecture_must_be_null"):
            check(
                c.get("target_architecture") is None,
                f"cluster {cid!r}: target_architecture is "
                f"{c.get('target_architecture')!r}, expected null. {spec['_why']}",
            )


def check_compute_unit_fields(design: dict, exp: dict) -> None:
    spec = exp.get("compute_unit_required_fields")
    if not spec:
        return
    for e in entries(design):
        if e.get("azure_type") != spec["azure_type"]:
            continue
        for field in spec["required"]:
            check(
                field in e,
                f"{spec['azure_type']} entry {e.get('azure_id')!r} is missing {field!r} "
                f"(section {e.get('_section')}). {spec['_why']}",
            )


def check_halt_covers_pending(design: dict, exp: dict) -> None:
    spec = exp["missing_rubric_halt"]
    if not spec.get("require_halt_entry_per_ref_file"):
        return
    refs = {e.get("ref_file") for e in (design.get("pending_rubric") or []) if e.get("ref_file")}
    named = json.dumps((design.get("halt") or {}).get("blocking") or [])
    for r in sorted(refs):
        check(
            r in named,
            f"{r!r} appears in pending_rubric[] but no halt.blocking entry names it. "
            f"{spec['_require_halt_entry_why']}",
        )


def check_skips(design: dict, id_of: dict[str, str], exp: dict) -> None:
    spec = exp["skips"]
    warnings = design.get("warnings") or []
    mapped = {e.get("azure_id") for e in entries(design)}
    blob_by_id: dict[str, str] = {}
    for w in warnings:
        aid = w.get("azure_id")
        if aid:
            blob_by_id[aid] = blob_by_id.get(aid, "") + json.dumps(w)

    for tf_addr in spec["expected_skipped_tf_addresses"]:
        aid = id_of.get(tf_addr)
        if aid is None:
            FAILS.append(f"no inventory resource with Terraform address {tf_addr!r}")
            continue
        check(
            aid in blob_by_id,
            f"{tf_addr!r} is a Skip Mapping but has no warnings[] entry. A resource with no entry "
            f"and no warning is indistinguishable from one the design forgot.",
        )
        check(
            aid not in mapped,
            f"{tf_addr!r} is a Skip Mapping but was given a target. Observability in particular has "
            f"no import path, so a CloudWatch TARGET would claim a migration that cannot happen — "
            f"the CloudWatch fallback is a report note, not a mapping.",
        )

    for tf_addr in spec["config_source_tf_addresses"]:
        aid = id_of.get(tf_addr)
        blob = blob_by_id.get(aid, "")
        check(
            "config_source" in blob or "consumed" in blob or "edge" in blob,
            f"{tf_addr!r} is a CONFIG SOURCE skip, but its warning does not say what it "
            f"contributed. {spec['_config_source_why']}",
        )


def check_hard_blocker(design: dict, id_of: dict[str, str], exp: dict) -> None:
    spec = exp["hard_blocker"]
    aid = id_of.get(spec["tf_address"])
    hit = [
        w for w in (design.get("warnings") or [])
        if w.get("code") == spec["expected_warning_code"] and w.get("azure_id") == aid
    ]
    check(
        bool(hit),
        f"no {spec['expected_warning_code']!r} warning for {spec['tf_address']!r}. {spec['_why']}",
    )
    if hit:
        check(
            hit[0].get("severity") == spec["expected_severity"],
            f"{spec['expected_warning_code']!r} severity is {hit[0].get('severity')!r}, expected "
            f"{spec['expected_severity']!r} — MGN refuses the image, so this is not advisory",
        )


def check_deferred_shape(design: dict, exp: dict) -> None:
    spec = exp["deferred_shape"]
    deferred = design.get("deferred") or []
    for d in deferred:
        check(
            d.get("aws_service") == spec["expected_aws_service"],
            f"deferred entry aws_service is {d.get('aws_service')!r}, expected "
            f"{spec['expected_aws_service']!r}",
        )
        check(
            spec["forbidden_field"] not in d,
            f"deferred entry carries a {spec['forbidden_field']!r} field. {spec['_why']}",
        )
    if not deferred:
        NOTES.append("deferred[] is empty — no specialist gate fires on this corpus (expected)")


def check_accounting(design: dict, inv: dict, id_of: dict[str, str], exp: dict) -> None:
    spec = exp["accounting"]
    n = len(inv.get("resources") or [])
    check(
        n == spec["expected_inventory_resource_count"],
        f"the run's inventory has {n} resources, expected "
        f"{spec['expected_inventory_resource_count']} — the design is being checked against the "
        f"wrong inventory",
    )

    accounted = {e.get("azure_id") for e in entries(design)}
    warned = {w.get("azure_id") for w in (design.get("warnings") or []) if w.get("azure_id")}
    accounted |= warned

    for tf_addr, aid in id_of.items():
        check(
            aid in accounted,
            f"{tf_addr!r} appears NOWHERE in the design — not mapped, not pending, not deferred, "
            f"not skipped. {spec['_why']}",
        )


def check_forbidden(design: dict, exp: dict) -> None:
    blob = json.dumps(design)
    for bad in exp["forbidden_substrings"]["values"]:
        check(
            bad not in blob,
            f"{bad!r} appears in aws-design.json. {exp['forbidden_substrings']['_why']}",
        )


# ---------------------------------------------------------------------------- main


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run_dir = Path(sys.argv[1])

    exp = load(HERE / "expected-design.json", "expected-design.json")
    if exp is None:
        _report()
        return 1

    design = load(run_dir / exp["design_file"], exp["design_file"])
    if design is None:
        _report()
        return 1

    inv_path = run_dir / exp["inventory_file"]
    if not inv_path.exists():
        # The golden design tree does not duplicate the 23k inventory. A REAL run always
        # has both in the same directory; this fallback exists only so the committed
        # golden tree can be checked without a second copy of the same bytes.
        inv_path = HERE / "after-discover" / exp["inventory_file"]
        NOTES.append(f"no inventory in the run dir; using the fixture's own golden at {inv_path.name}")
    inv = load(inv_path, exp["inventory_file"])
    if inv is None:
        _report()
        return 1

    table = load(HERE / exp["fast_path_table_relpath"], "fast-path-services.json")
    if table is None:
        _report()
        return 1

    # tf_address -> azure_id, from the inventory the design was built from.
    id_of: dict[str, str] = {}
    for r in inv.get("resources") or []:
        addr = (r.get("config") or {}).get("tf_address")
        aid = r.get("azure_id")
        if addr and aid:
            id_of[addr] = aid
    if not id_of:
        FAILS.append("no resource in the inventory carries config.tf_address — cannot resolve identity")
        _report()
        return 1

    check_table(table, exp)
    check_canonical_type_coverage(exp)
    check_index_reference_files_exist(exp)
    check_sizing_provenance(design, exp)
    check_routing_provenance(design, exp)
    check_namespace_routing_targets(exp)
    check_canonicalization_governance(exp)
    check_halt_not_stale(design, exp)
    check_deterministic(design, table, id_of, exp)
    check_fan_in(design, inv, id_of, exp)
    check_unknown_stop(design, exp)
    check_inline_os_disk(design, exp)
    check_pending_rubric(design, id_of, exp)
    check_rubric_mappings(design, id_of, exp)
    check_architecture_default(design, id_of, exp)
    check_source_ha_finding(design, id_of, exp)
    check_halt_covers_pending(design, exp)
    check_cluster_pattern_status(design, exp)
    check_compute_unit_fields(design, exp)
    check_skips(design, id_of, exp)
    check_hard_blocker(design, id_of, exp)
    check_deferred_shape(design, exp)
    check_accounting(design, inv, id_of, exp)
    check_forbidden(design, exp)

    if FAILS:
        _report()
        return 1
    _print_notes()
    print("PASS — expected-design.json assertions hold")
    return 0


def _print_notes() -> None:
    for n in NOTES:
        print(f"note: {n}")


def _report() -> None:
    _print_notes()
    print(f"FAIL ({len(FAILS)}):")
    for f in FAILS:
        print(f"  - {f}")


if __name__ == "__main__":
    sys.exit(main())
