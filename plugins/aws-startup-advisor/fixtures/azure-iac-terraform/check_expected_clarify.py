#!/usr/bin/env python3
"""Assert an azure-to-aws Clarify run over the azure-iac-terraform corpus.

Clarify is the one phase the capability-test method cannot reach: it is
`_interactive: true`, so a dispatched isolated agent has no user to answer the
assumption sheet. `clarify-answers.json` substitutes for that user, and this asserter
checks what a scripted user CAN check — the sheet's **branching**.

That is a real limitation, stated up front: nothing here tests wording, batching, tone,
or whether the sheet reads well. Those need a human. What it does test is which rows
fire, which are ESSENTIAL versus PROPOSED, and which are N/A — and that is where the
defects live, because a firing rule is a judgement and prose cannot check itself.

Every check pins a fact where a plausible improvisation and the correct answer DIVERGE:

  * licensing FIRES on one Windows VM, and `sql_model` is N/A while it does — the
    category and its sub-questions have different trigger conditions;
  * the isolation row exists for the 5-app plan and is N/A for the 1-app and 0-app
    plans — asking about all three is the obvious wrong behaviour;
  * `cosmos_rw_split` is N/A because the account is Mongo API, not Core;
  * `availability` is ESSENTIAL, not PROPOSED, because the source is zone-redundant;
  * `cpu_architecture` is DETECTED, not PROPOSED, because Windows removes the choice;
  * an ESSENTIAL row with a null value BLOCKS the phase;
  * a value taken from its default stays PROPOSED and is never promoted to DETECTED;
  * `metadata.questions_defaulted[]` and `metadata.deferred_to_generate[]` are DISJOINT
    and every defaulted key resolves (index notation for array rows) to an untouched
    PROPOSED row;
  * `data.db_cutover.default` / `size_coverage` follow Q-D2's size rule from the
    inventory — 100 GiB inclusive, and `dump_restore` + "unknown" when no size was
    measured, rather than an invented size or an escalation to ESSENTIAL.

Usage:
    python3 check_expected_clarify.py <migration_run_dir> [expected-spec.json]

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


_INDEX_SEG = re.compile(r"^([^\[\]]+)\[(\d+)\]$")

RELATIONAL_TYPES = {
    "Microsoft.DBforPostgreSQL/flexibleServers",
    "Microsoft.DBforMySQL/flexibleServers",
    "Microsoft.Sql/servers/databases",
}
GIB_MB = 1024
DUMP_RESTORE_MAX_GIB = 100


def get(prefs: dict, dotted: str) -> dict | None:
    """`data.availability` -> that row, or None.

    Array rows use the index notation `questions_defaulted[]` records them under
    (schema-preferences.md § Shape): `app_service_plans[0].isolation_split`,
    `clusters[1].pattern_id`. One lookup resolves either shape.
    """
    node: object = prefs
    for part in dotted.split("."):
        m = _INDEX_SEG.match(part)
        if m:
            if not isinstance(node, dict):
                return None
            arr = node.get(m.group(1))
            idx = int(m.group(2))
            if not isinstance(arr, list) or idx >= len(arr):
                return None
            node = arr[idx]
            continue
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node if isinstance(node, dict) else None


def expected_db_cutover_default(sizes_mb: list[int | None]) -> tuple[str, str]:
    """clarify-database.md § Q-D2's three-branch rule, as a pure function.

    Returns `(default, size_coverage)`. The boundary is 100 GiB INCLUSIVE on the
    dump_restore side (102400 MB -> dump_restore, 102401 MB -> dms). With no measured
    size at all the default is dump_restore with coverage "unknown" — the runbook with no
    AWS charge, so an unmeasured database never invents cost. A mix of measured and
    unmeasured servers applies the rule to the measured maximum with coverage "partial".
    """
    measured = [s for s in sizes_mb if isinstance(s, (int, float)) and not isinstance(s, bool)]
    if not measured:
        return "dump_restore", "unknown"
    coverage = "complete" if len(measured) == len(sizes_mb) else "partial"
    largest_gib = max(measured) / GIB_MB
    return ("dump_restore" if largest_gib <= DUMP_RESTORE_MAX_GIB else "dms"), coverage


def check_dispositions(prefs: dict, exp: dict) -> None:
    for dotted, spec in exp["row_dispositions"].items():
        if dotted.startswith("_"):
            continue
        r = get(prefs, dotted)
        if r is None:
            FAILS.append(f"{dotted!r}: no row at all. {spec['why']}")
            continue
        check(
            r.get("disposition") == spec["disposition"],
            f"{dotted!r}: disposition is {r.get('disposition')!r}, expected "
            f"{spec['disposition']!r}. {spec['why']}",
        )
        if "value" in spec:
            check(
                r.get("value") == spec["value"],
                f"{dotted!r}: value is {r.get('value')!r}, expected {spec['value']!r}. {spec['why']}",
            )
        for bad in spec.get("must_not_be_disposition", []):
            check(
                r.get("disposition") != bad,
                f"{dotted!r}: disposition is {bad!r}, the plausible-but-wrong answer. {spec['why']}",
            )
        for key in spec.get("requires_keys", []):
            check(
                bool(r.get(key)),
                f"{dotted!r}: has no {key!r}. An ESSENTIAL question without its context is "
                f"unanswerable, and an N/A without a reason is indistinguishable from an omission.",
            )


def check_conflicting_answer(prefs: dict, exp: dict) -> None:
    """A user answer a hard_blocker suppresses is recorded AS GIVEN, and does not gate."""
    spec = exp.get("conflicting_answer")
    if not spec:
        return
    row = get(prefs, spec["row"])
    if row is None:
        FAILS.append(f"no row at {spec['row']!r} to check the conflicting answer. {spec['_why']}")
        return
    check(row.get("value") == spec["expected_value"],
          f"{spec['row']}: value is {row.get('value')!r}, expected {spec['expected_value']!r}. "
          f"The answer is recorded AS GIVEN — silently substituting a different one hides a "
          f"decision the customer has to make. {spec['_why']}")
    for k in spec.get("requires_keys", []):
        check(bool(row.get(k)),
              f"{spec['row']}: has no {k!r}. Recording the answer without recording what "
              f"suppresses it leaves the conflict invisible. {spec['_why']}")
    node: object = prefs
    for part in spec["blocker_code_in"].split("."):
        node = node.get(part) if isinstance(node, dict) else None
    blockers = node if isinstance(node, list) else []
    codes = {b.get("code") for b in blockers if isinstance(b, dict)}
    check(spec["expected_blocker_code"] in codes,
          f"{spec['blocker_code_in']} has no {spec['expected_blocker_code']!r} entry (got {sorted(codes)}). "
          f"The blocker is a PREREQUISITE and must be recorded even though it does not change the answer.")
    check(prefs.get("clarify_status") == spec["status_must_remain"],
          f"clarify_status is {prefs.get('clarify_status')!r}, expected "
          f"{spec['status_must_remain']!r}. A conflicting answer does NOT gate the phase.")


def check_essential_gate(prefs: dict, exp: dict) -> None:
    spec = exp["essential_gate"]
    unanswered: list[str] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            if node.get("disposition") == "ESSENTIAL":
                if node.get("value") is None:
                    unanswered.append(path)
                return
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for n, v in enumerate(node):
                walk(v, f"{path}[{n}]")

    walk(prefs, "")
    check(
        sorted(unanswered) == sorted(spec["expected_unanswered"]),
        f"unanswered ESSENTIAL rows are {sorted(unanswered)}, expected "
        f"{sorted(spec['expected_unanswered'])}. {spec['_why']}",
    )
    check(
        prefs.get("clarify_status") == spec["expected_status"],
        f"clarify_status is {prefs.get('clarify_status')!r}, expected "
        f"{spec['expected_status']!r}. {spec['_why']}",
    )
    NOTES.append(f"essential gate: {len(unanswered)} unanswered — phase must GATE_FAIL")


def check_defaults_not_promoted(prefs: dict, exp: dict) -> None:
    """A value equal to its default must still read PROPOSED."""
    spec = exp["defaults_not_promoted"]
    offenders: list[str] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            if "disposition" in node and "default" in node:
                if (
                    node.get("disposition") == "DETECTED"
                    and node.get("value") == node.get("default")
                    and node.get("default") is not None
                    and not node.get("source")
                    and not node.get("forced_by")
                ):
                    offenders.append(path)
                return
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for n, v in enumerate(node):
                walk(v, f"{path}[{n}]")

    walk(prefs, "")
    check(
        not offenders,
        f"{offenders} are DETECTED with value == default and carry no `source`. "
        f"The key is `source` for a DETECTED row and `forced_by` when a blocker removed the "
        f"choice — see schema-preferences.md. NOT `note`, `reason`, `mapped_from` or `detail`: "
        f"capability run 5 used `note` for nine rows whose content was entirely correct and this "
        f"failed on the key NAME, because nothing specified it. {spec['_why']}")


def check_isolation_rows(prefs: dict, inv: dict, exp: dict) -> None:
    """Keyed on `config.tf_address` when the inventory carries one (IaC source), else on
    `azure_id` (live source, where there is no Terraform address to key on)."""
    spec = exp["isolation_rows"]
    by_id = {
        r["azure_id"]: (r.get("config") or {}).get("tf_address") or r["azure_id"]
        for r in inv.get("resources") or []
    }
    got = {
        by_id.get(p.get("plan_azure_id")): (
            p.get("hosted_app_count"),
            (p.get("isolation_split") or {}).get("disposition"),
        )
        for p in prefs.get("app_service_plans") or []
    }
    for addr, want in spec["expected"].items():
        if addr.startswith("_"):
            continue
        if addr not in got:
            FAILS.append(f"no app_service_plans[] row for {addr!r}. {spec['_why']}")
            continue
        count, disp = got[addr]
        check(count == want["hosted_app_count"],
              f"{addr!r}: hosted_app_count is {count!r}, expected {want['hosted_app_count']!r}")
        check(disp == want["disposition"],
              f"{addr!r} (hosts {count}): isolation disposition is {disp!r}, expected "
              f"{want['disposition']!r}. {want['why']}")


def check_licensing_firing(prefs: dict, exp: dict) -> None:
    spec = exp["licensing_firing"]
    lic = prefs.get("licensing") or {}
    check(lic.get("_fired") == spec["expected_fired"],
          f"licensing._fired is {lic.get('_fired')!r}, expected {spec['expected_fired']!r}. {spec['_why']}")
    if spec["expected_fired"] is False:
        # The category did not fire: clarify-assemble.md § Assembly rule 3 requires an
        # EXPLICIT N/A stub with a reason, not an absent key. No blocker to look for.
        check(lic.get("disposition") == "N/A" and bool(lic.get("reason")),
              f"licensing did not fire but is not written as an explicit N/A with a reason "
              f"(got disposition={lic.get('disposition')!r}, reason={lic.get('reason')!r}). "
              f"An absent key and a considered N/A are different facts.")
        return
    check(bool(lic.get("_firing_reason")),
          "licensing fired with no _firing_reason — which VM or SQL resource triggered it must be recorded, "
          "or the user cannot tell why they are being asked")
    blockers = lic.get("blockers") or []
    hit = [b for b in blockers if b.get("code") == spec["expected_blocker_code"]]
    check(bool(hit),
          f"no {spec['expected_blocker_code']!r} blocker. {spec['_blocker_why']}")
    if hit:
        check(hit[0].get("severity") == "blocker",
              f"the Azure Edition entry has severity {hit[0].get('severity')!r}, expected 'blocker' — "
              f"MGN refuses the image, so it is not advisory")


def check_clarify_mode(prefs: dict, exp: dict) -> None:
    """preferences.json metadata.clarify_mode (clarify-assemble.md § Assembly rule 0).

    This corpus is ineligible for the Step 0.5 fast path (VMs, ZoneRedundant Postgres,
    five clusters), so a run that reports `fast_path` here either ignored Discover's
    verdict or re-derived eligibility itself — both are exactly what clarify.md § Step 0.5
    forbids, and neither produces a malformed artifact.
    """
    spec = exp["clarify_mode"]
    meta = prefs.get("metadata") or {}
    mode = meta.get("clarify_mode")
    check(mode == spec["expected"],
          f"metadata.clarify_mode is {mode!r}, expected {spec['expected']!r}. {spec['_why']}")
    check(meta.get("fast_path_eligible") is spec["expected_fast_path_eligible"],
          f"metadata.fast_path_eligible is {meta.get('fast_path_eligible')!r}, expected "
          f"{spec['expected_fast_path_eligible']!r} — it must be copied from the inventory's "
          f"metadata.clarify_fast_path.eligible, not re-decided by Clarify")
    check(isinstance(meta.get("questions_defaulted"), list),
          f"metadata.questions_defaulted is {meta.get('questions_defaulted')!r}, expected a list "
          f"(possibly empty) of dotted row keys that took their documented default")
    want_deferred = spec.get("expected_deferred_to_generate")
    if want_deferred is not None:
        deferred = meta.get("deferred_to_generate")
        check(sorted(deferred or []) == sorted(want_deferred),
              f"metadata.deferred_to_generate is {deferred!r}, expected {want_deferred!r}. "
              f"{spec.get('_deferred_why', '')}")
        for dotted in want_deferred:
            r = get(prefs, dotted) or {}
            check(r.get("deferred_to_generate") is True,
                  f"{dotted!r}: listed in metadata.deferred_to_generate but the row does not carry "
                  f"deferred_to_generate: true — generate.md's precondition and estimate-assemble.md "
                  f"Step 3b both key off the row flag")
            check(r.get("default") is not None and r.get("value") == r.get("default"),
                  f"{dotted!r}: a deferred row must carry a non-null default and (before Step 3b) "
                  f"value == default; got value={r.get('value')!r} default={r.get('default')!r}")


def check_provenance_lists(prefs: dict, exp: dict) -> None:
    """The two metadata lists are DISJOINT and every `questions_defaulted[]` key resolves.

    schema-preferences.md § Shape: a row is in exactly one list. Before this rule a
    fast-path `db_cutover` sat in both, rendered twice in the Estimate assumptions block,
    and left Step 3b two entries to clear. Every `questions_defaulted[]` key must resolve
    (index notation for array rows) to a PROPOSED row whose value equals its default and
    carries no `source` — anything else is either a correction that forgot to leave the
    list or a key the Estimate block cannot look up. Runs on EVERY spec: the wizard goldens
    carry `[]` / `["data.db_cutover"]` and must hold too.
    """
    meta = prefs.get("metadata") or {}
    defaulted = meta.get("questions_defaulted") or []
    deferred = meta.get("deferred_to_generate") or []
    overlap = sorted(set(defaulted) & set(deferred))
    check(not overlap,
          f"{overlap} appear in BOTH metadata.questions_defaulted and metadata.deferred_to_generate. "
          f"The lists are disjoint (clarify-assemble.md § Assembly rule 0): a deferred row renders "
          f"once in the Estimate block and Step 3b has one entry to clear.")
    for dotted in defaulted:
        r = get(prefs, dotted)
        if r is None:
            FAILS.append(f"{dotted!r} is in metadata.questions_defaulted but resolves to no row. "
                         f"Array rows use index notation (app_service_plans[0].isolation_split) so one "
                         f"lookup finds them; a key the Estimate block cannot resolve is a row it cannot show.")
            continue
        check(r.get("disposition") == "PROPOSED",
              f"{dotted!r} is in questions_defaulted but its disposition is {r.get('disposition')!r}; "
              f"only PROPOSED rows take a default without being asked (DETECTED rows were READ).")
        check(r.get("value") == r.get("default"),
              f"{dotted!r} is in questions_defaulted but value={r.get('value')!r} != default="
              f"{r.get('default')!r}. A corrected row must leave the list (schema-preferences.md § "
              f"Correction provenance) or Step 2 re-lists the user's choice as an assumption.")
        check(not r.get("source"),
              f"{dotted!r} is in questions_defaulted but carries source={r.get('source')!r}. A row "
              f"with a correction/confirmation source is no longer a silent default.")
    for dotted in deferred:
        r = get(prefs, dotted) or {}
        check(r.get("deferred_to_generate") is True,
              f"{dotted!r} is listed in metadata.deferred_to_generate but the row flag is "
              f"{r.get('deferred_to_generate')!r}; Part 4's label and Step 3b key off the row flag.")
    spec = exp.get("fast_path_provenance")
    if spec:
        missing = [k for k in spec.get("expected_defaulted_keys", []) if k not in defaulted]
        check(not missing,
              f"{missing} are missing from metadata.questions_defaulted. {spec['_why']}")
        wrongly_listed = [k for k in spec.get("must_not_be_defaulted", []) if k in defaulted]
        check(not wrongly_listed,
              f"{wrongly_listed} appear in metadata.questions_defaulted but were asked (ESSENTIAL) or "
              f"deferred (asked at Step 3b) — neither is a silent default. {spec['_why']}")


def check_db_cutover_default_rule(prefs: dict, inv: dict, exp: dict) -> None:
    """`data.db_cutover.default` and `.size_coverage` follow Q-D2's rule from the inventory.

    Collects `config.storage_mb` from every relational server in the inventory (None when
    absent — live enrichment skipped, or the Terraform attribute unset) and derives what
    the default and coverage MUST be. A fixed expected value would pin one estate; the
    rule pins the behaviour, including the missing-size case where a plausible
    improvisation invents a size or escalates to ESSENTIAL.
    """
    spec = exp.get("db_cutover_default_rule")
    if not spec:
        return
    row = get(prefs, "data.db_cutover")
    if row is None:
        FAILS.append(f"no data.db_cutover row to check the size rule against. {spec['_why']}")
        return
    sizes: list[int | None] = []
    names: list[str] = []
    for r in inv.get("resources") or []:
        if r.get("azure_type") in RELATIONAL_TYPES:
            sizes.append((r.get("config") or {}).get("storage_mb"))
            names.append(r.get("name") or r.get("azure_id"))
    if not sizes:
        check(row.get("disposition") == "N/A",
              f"no relational database in the inventory, but data.db_cutover is "
              f"{row.get('disposition')!r} rather than N/A")
        return
    want_default, want_coverage = expected_db_cutover_default(sizes)
    check(row.get("default") == want_default,
          f"data.db_cutover.default is {row.get('default')!r}, expected {want_default!r} from "
          f"relational storage_mb {sizes} on {names}. {spec['_why']}")
    check(row.get("size_coverage") == want_coverage,
          f"data.db_cutover.size_coverage is {row.get('size_coverage')!r}, expected {want_coverage!r} "
          f"from relational storage_mb {sizes}. The uncertainty travels on the row; it is never "
          f"papered over by inventing a size.")
    measured = [s for s in sizes if isinstance(s, (int, float)) and not isinstance(s, bool)]
    want_gib = (max(measured) / GIB_MB) if measured else None
    check(row.get("largest_relational_db_gib") == want_gib,
          f"data.db_cutover.largest_relational_db_gib is {row.get('largest_relational_db_gib')!r}, "
          f"expected {want_gib!r} (null when nothing was measured).")
    check(bool(row.get("default_basis")),
          "data.db_cutover has no default_basis — the rule and what it was applied to must be on the row "
          "so Step 3b can say why the default was chosen")
    NOTES.append(f"db_cutover rule: sizes_mb={sizes} -> default={want_default} coverage={want_coverage}")


def check_cluster_rows(prefs: dict, run_dir: Path, exp: dict) -> None:
    spec = exp["cluster_rows"]
    clusters = load(run_dir / spec["clusters_file"], spec["clusters_file"])
    if clusters is None:
        return
    want = {c.get("cluster_id") for c in clusters.get("clusters") or []}
    got = {c.get("cluster_id") for c in prefs.get("clusters") or []}
    check(got == want,
          f"preferences clusters {sorted(got)} do not match the clusters artifact {sorted(want)}. "
          f"{spec['_why']}")


def check_no_secrets(prefs: dict, exp: dict) -> None:
    blob = json.dumps(prefs)
    for bad in exp["forbidden_substrings"]["values"]:
        check(bad not in blob,
              f"{bad!r} appears in preferences.json. {exp['forbidden_substrings']['_why']}")


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    run_dir = Path(sys.argv[1])

    # Optional 2nd arg selects the expectation set, so one asserter serves both the BLOCKED
    # and the COMPLETING branch. Defaults to the blocked one, which is the historical behaviour.
    spec_name = sys.argv[2] if len(sys.argv) == 3 else "expected-clarify.json"
    exp = load(HERE / spec_name, spec_name)
    if exp is None:
        _report()
        return 1
    prefs = load(run_dir / exp["preferences_file"], exp["preferences_file"])
    if prefs is None:
        _report()
        return 1

    inv_path = run_dir / exp["inventory_file"]
    if not inv_path.exists():
        inv_path = HERE / "after-discover" / exp["inventory_file"]
        NOTES.append(f"no inventory in the run dir; using the fixture's golden at {inv_path.name}")
    inv = load(inv_path, exp["inventory_file"])
    if inv is None:
        _report()
        return 1
    cl_dir = run_dir if (run_dir / exp["cluster_rows"]["clusters_file"]).exists() else HERE / "after-discover"

    check_dispositions(prefs, exp)
    check_essential_gate(prefs, exp)
    check_defaults_not_promoted(prefs, exp)
    check_conflicting_answer(prefs, exp)
    check_isolation_rows(prefs, inv, exp)
    check_licensing_firing(prefs, exp)
    check_clarify_mode(prefs, exp)
    check_provenance_lists(prefs, exp)
    check_db_cutover_default_rule(prefs, inv, exp)
    check_cluster_rows(prefs, cl_dir, exp)
    check_no_secrets(prefs, exp)

    if FAILS:
        _report()
        return 1
    _print_notes()
    print(f"PASS — {spec_name} assertions hold")
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
