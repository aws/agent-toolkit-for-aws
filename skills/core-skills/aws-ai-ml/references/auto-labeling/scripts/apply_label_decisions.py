#!/usr/bin/env python3
"""Apply the user's decisions on the contradiction list and save the next spec + seed.

    python apply_label_decisions.py --project-dir <proj> --spec <work/labeling_spec_iter_N.md> \
        --seed <review_seed.jsonl> --decided-by <handle> [--decisions <audit>/decisions.csv] [--out-dir <dir>]
        [--dry-run]
    python apply_label_decisions.py --project-dir <proj> --undo <review run id>

Writes labeling_spec_iter_{N+1}.md, seed_iter_{N+1}.jsonl and changelog_iter_{N+1}.json next to
the spec, then writes the relabels into a frozen split's dev.jsonl and val.jsonl (split_state.py
relabel, which rehashes it), then one run-log `decision` entry per new or changed decision. The
split is written last: if it fails, the split is left as it was and the three files are put back.
Before it relabels, it copies dev.jsonl and val.jsonl to
<proj>/work/review_jobs/<review run id>-split-before/; --undo <review run id> puts that copy back
and rehashes the split (refused when the copy is missing, test.jsonl changed, or the split's rows
changed since). --dry-run prints what would change and writes nothing. The spec, --seed and split
must be the ones the review read; no test row is read or written.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from io_utils import split_state  # noqa: E402
from io_utils import (  # noqa: E402
    _run_log,
    read_jsonl,
    sdk_missing,
    warn_client_read,
    write_text_atomic,
)
from labelcheck.lc_decide import apply_decisions  # noqa: E402
from labelcheck.lc_decide import (
    RUN_LOG_STEP,
    OverrideOutsideItem,
    logged_decisions,
    next_spec_name,
    read_decisions_csv,
    review_inputs,
    spec_iteration,
)

try:
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.review import decisions as _ld
    from sagemaker.ai_registry.data_preparer.exceptions import DataPreparerOperatorError
    from sagemaker.core import Attribution, set_attribution
except ImportError as e:
    sys.exit(sdk_missing(e))

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

SPLIT_FILES = ("dev.jsonl", "val.jsonl")  # the files a relabel rewrites; test never changes


def split_backup_dir(project_dir, run_id):
    """Where apply keeps the pre-apply dev.jsonl and val.jsonl of one review run."""
    return Path(project_dir, "work", "review_jobs", f"{run_id}-split-before")


def _ids(path):
    return [
        json.loads(x).get("id")
        for x in Path(path).read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]


def undo_split(project_dir, run_id):
    """Put back the dev.jsonl and val.jsonl apply copied before the review run's relabel,
    then rehash. Refused, changing nothing, when the copy is missing, test.jsonl changed, or
    the split's rows changed since (an undo restores labels, never drops a row added later)."""
    splits = split_state.find_splits_dir(None, project_dir)
    st = split_state.load_state(splits) if splits else None
    if st is None:
        sys.exit(
            "--undo needs the project's frozen split (split_state.py freeze). Nothing was changed."
        )
    backup = split_backup_dir(project_dir, run_id)
    missing = [f for f in SPLIT_FILES if not (backup / f).is_file()]
    if missing:
        sys.exit(
            f"--undo {run_id}: no copy of {', '.join(missing)} in {backup} (apply writes it before it "
            "relabels the split). Nothing was changed."
        )
    if (
        split_state.sha256_file(os.path.join(splits, "test.jsonl"))
        != st["splits"]["test"]["sha256"]
    ):
        sys.exit(
            "--undo: test.jsonl changed since the split was frozen; test rows never change, so restore "
            "it first. Nothing was changed."
        )
    moved = [f for f in SPLIT_FILES if _ids(backup / f) != _ids(os.path.join(splits, f))]
    if moved:
        sys.exit(
            f"--undo {run_id}: the rows of {', '.join(moved)} changed since that review (rows added, "
            "removed or moved); an undo restores labels only. Nothing was changed."
        )
    current = {f: Path(splits, f).read_bytes() for f in SPLIT_FILES}
    state_before = split_state.sha256_file(split_state.state_path(splits))
    try:
        for f in SPLIT_FILES:
            tmp = Path(splits, f + ".tmp")
            tmp.write_bytes((backup / f).read_bytes())
            os.replace(tmp, Path(splits, f))
        out = split_state.rehash(splits, f"label review undo, run {run_id}")
    except (OSError, ValueError, split_state.SplitGuardError) as e:
        if split_state.sha256_file(split_state.state_path(splits)) == state_before:
            for f, data in current.items():
                Path(splits, f).write_bytes(data)
            sys.exit(f"--undo {run_id}: {e}. The split is as it was before the undo.")
        sys.exit(f"--undo {run_id}: {e}. The split WAS restored from {backup} and rehashed.")
    _run_log().write_entry(
        project_dir,
        kind="artifact",
        step=RUN_LOG_STEP,
        iteration=0,
        status="undone",
        run_id=run_id,
        restored_from=str(backup),
    )
    print(json.dumps({"undone": run_id, "restored_from": str(backup), **out}, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument(
        "--project-dir",
        required=True,
        help="the project directory whose run-log.jsonl records the decisions",
    )
    ap.add_argument("--audit-dir", default=None, help="default: <project-dir>/audit")
    ap.add_argument("--spec", default=None, help="required unless --undo")
    ap.add_argument("--seed", default=None, help="required unless --undo")
    ap.add_argument("--decisions", default=None)
    ap.add_argument("--label-field", default="gt_label")
    ap.add_argument(
        "--label-set",
        default=None,
        help="JSON list (default: the spec's Label Set, else the seed's)",
    )
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--decided-by", default=None)
    ap.add_argument(
        "--dry-run", action="store_true", help="print what would change and write nothing"
    )
    ap.add_argument(
        "--undo",
        default=None,
        metavar="RUN_ID",
        help="put back the split as it was before that review run's apply, and rehash",
    )
    a = ap.parse_args(argv)
    if a.undo:
        return undo_split(a.project_dir, a.undo)
    if not (a.spec and a.seed):
        ap.error("--spec and --seed are required (or pass --undo <review run id>)")
    sdir = split_state.find_splits_dir(None, a.project_dir)
    st = split_state.load_state(sdir) if sdir else None
    if st and a.label_field != st["label_field"]:  # the relabel writes the split's own field
        sys.exit(
            f"--label-field {a.label_field!r} is not the frozen split's label field {st['label_field']!r}; "
            f"pass --label-field {st['label_field']}. Nothing was written."
        )
    audit_dir = a.audit_dir or os.path.join(a.project_dir, "audit")
    with open(os.path.join(audit_dir, "contradictions.jsonl"), encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]
    known = logged_decisions(a.project_dir, items)  # only for items that did not change
    dpath = a.decisions or os.path.join(audit_dir, "decisions.csv")
    if a.decisions and not os.path.exists(dpath):
        sys.exit(f"--decisions {dpath!r} does not exist. Nothing was written.")
    try:  # a blank CSV row is an explicit "no decision"
        decisions = _ld.merge_decisions(
            known, read_decisions_csv(dpath) if os.path.exists(dpath) else None, items, source=dpath
        )
    except DataPreparerOperatorError as e:
        sys.exit(str(e))
    rows = read_jsonl(a.seed)
    # A frozen split's test row in --seed stops the run; without one, split test rows (any case) are left out.
    frozen = split_state.test_ids(project_dir=a.project_dir)
    test = (
        frozen
        if frozen is not None
        else {str(r.get("id")) for r in rows if str(r.get("split")).strip().casefold() == "test"}
    )
    rows = rows if frozen is not None else [r for r in rows if str(r.get("id")) not in test]
    warn_client_read("apply_label_decisions", len(rows))
    try:
        split_state.guard_read(
            a.seed,
            RUN_LOG_STEP,
            {"dev", "val"},
            project_dir=a.project_dir,
            rows=rows,
            id_field="id",
        )
    except (OSError, ValueError, split_state.SplitGuardError) as e:
        sys.exit(f"split guard: {e}. Nothing was written.")
    summary = os.path.abspath(os.path.join(audit_dir, "summary.json"))
    review = [
        e
        for e in _run_log().read_entries(a.project_dir, kind="analysis", step=RUN_LOG_STEP)
        if e.get("status") in ("flagged", "estimate")
        and os.path.join(os.path.abspath(a.project_dir), e.get("summary") or "") == summary
    ]
    if not review or review[-1].get("inputs") != review_inputs(a.spec, a.seed, a.project_dir):
        sys.exit(
            f"--spec, --seed or the frozen split is not what the review that wrote {audit_dir} read; "
            "rerun review_labels.py on them and decide again. Nothing was written."
        )
    touched = _ld.touched_test_rows(items, decisions, test)
    if touched:
        sys.exit(
            f"the decisions change {len(touched)} frozen test row(s) (e.g. {touched[:3]}); a test row is "
            "changed only through Golden rows (references/label-review.md). Nothing was written."
        )
    with open(a.spec, encoding="utf-8") as f:
        spec_text = f.read()
    # The label set the review job checked against: the spec's, else the gold's. A
    # decision can never set a label outside it.
    label_set = (
        json.loads(a.label_set)
        if a.label_set
        else _ld.default_label_set(spec_text, rows, a.label_field)
    )
    v = spec_iteration(a.spec) + 1
    try:
        new_rows, new_spec, cl, led = apply_decisions(
            items,
            decisions,
            rows,
            spec_text,
            label_field=a.label_field,
            label_set=label_set,
            version=v,
            decided_by=a.decided_by,
        )
    except OverrideOutsideItem as e:
        sys.exit(f"{e}. Fix the overrides column in {dpath}; nothing was written.")
    if cl["labels_changed"] and not a.decided_by:
        sys.exit(
            "pass --decided-by <the user's handle>: a relabel records who decided. Nothing was written."
        )
    out = a.out_dir or os.path.dirname(os.path.abspath(a.spec))
    os.makedirs(out, exist_ok=True)
    spec_out = os.path.join(out, next_spec_name(a.spec))
    seed_out = os.path.join(out, f"seed_iter_{v}.jsonl")
    changelog_out = os.path.join(out, f"changelog_iter_{v}.json")
    run_log = _run_log()
    # The refine loop also writes labeling_spec_iter_{N+1}.md. Overwrite only a spec an
    # earlier label review wrote (the run log keeps paths relative to the project).
    root = os.path.abspath(a.project_dir)
    ours = {
        os.path.normpath(os.path.join(root, e["spec"]))
        for e in run_log.read_entries(a.project_dir, kind="artifact", step=RUN_LOG_STEP)
        if e.get("spec")
    }
    if os.path.exists(spec_out) and os.path.abspath(spec_out) not in ours:
        sys.exit(
            f"{spec_out} exists and no label review wrote it; pass --out-dir to write elsewhere."
        )
    splits = split_state.find_splits_dir(None, a.project_dir)
    relabel = bool(splits and cl["labels_changed"])  # the frozen split takes the person's relabels
    run_id = review[-1].get("run_id") or f"iter{v}"  # the review run whose decisions these are
    backup = split_backup_dir(a.project_dir, run_id)
    if a.dry_run:
        print(
            json.dumps(
                _ld.dry_run_summary(
                    v,
                    led,
                    cl,
                    [spec_out, seed_out, changelog_out],
                    split_files=[os.path.join(splits, f) for f in SPLIT_FILES] if relabel else [],
                    split_copy=str(backup) if relabel else None,
                ),
                ensure_ascii=False,
            )
        )
        return 0
    outputs = {
        spec_out: new_spec,
        seed_out: "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in new_rows),
        changelog_out: json.dumps(cl, indent=1, ensure_ascii=False),
    }
    prior = {p: (open(p, encoding="utf-8").read() if os.path.exists(p) else None) for p in outputs}

    def _undo():  # put back what this run replaced and remove what it created
        for p, text in prior.items():
            if text is not None:
                write_text_atomic(p, text)
            elif os.path.exists(p):
                os.remove(p)

    try:
        for p, text in outputs.items():
            write_text_atomic(p, text)  # each lands whole or not at all
    except OSError as e:
        _undo()
        sys.exit(f"writing {p}: {e}. The split is unchanged and nothing was written.")
    warning = None
    if relabel:  # the copy --undo restores, then the relabel, last: it moves the split sha
        try:
            backup.mkdir(parents=True, exist_ok=True)
            for name in SPLIT_FILES:
                shutil.copyfile(os.path.join(splits, name), backup / (name + ".tmp"))
                os.replace(backup / (name + ".tmp"), backup / name)
        except OSError as e:
            _undo()
            shutil.rmtree(backup, ignore_errors=True)
            sys.exit(
                f"copying the split to {backup}: {e}. The split is unchanged and nothing was written."
            )
        state_before = split_state.sha256_file(split_state.state_path(splits))
        try:
            split_state.relabel(
                splits,
                {c["id"]: c["to"] for c in cl["labels_changed"]},
                f"label review decisions, iteration {v}",
            )
        except (OSError, ValueError, split_state.SplitGuardError) as e:
            if split_state.sha256_file(split_state.state_path(splits)) == state_before:
                _undo()  # relabel put dev.jsonl and val.jsonl back
                shutil.rmtree(backup, ignore_errors=True)
                sys.exit(f"split_state: {e}. The split is unchanged and nothing was written.")
            # The state was rewritten, so the relabel is accepted; only a later step failed.
            warning = (
                f"split_state: {e}; the split WAS relabeled and rehashed ({changelog_out} lists "
                "each change); the decisions are logged below"
            )
            print(f"WARNING: {warning}", file=sys.stderr)
    iteration = spec_iteration(a.spec)
    decision_ids = [
        run_log.write_entry(a.project_dir, **ev)
        for ev in _ld.decision_events(led, known, iteration)
    ]
    entry = run_log.write_entry(
        a.project_dir,
        kind="artifact",
        step=RUN_LOG_STEP,
        iteration=iteration,
        status="written",
        spec=os.path.abspath(spec_out),
        seed=os.path.abspath(seed_out),
        changelog=os.path.abspath(changelog_out),
        decision_entries=decision_ids,
    )
    print(
        json.dumps(
            {
                "iteration": v,
                "spec": spec_out,
                "seed": seed_out,
                "run_log_entry": entry,
                "labels_changed": len(cl["labels_changed"]),
                "split_rehashed": relabel,
                **(
                    {
                        "split_copy": str(backup),
                        "undo": f"apply_label_decisions.py --project-dir {a.project_dir} "
                        f"--undo {run_id}",
                    }
                    if relabel
                    else {}
                ),
                "sentences_added": len(cl["sentences_added"]),
                "recheck": len(cl["recheck"]),
                "needs_a_decision": len(cl["needs_a_decision"]),
                "invalid_decisions": cl["invalid_decisions"],
                **({"warning": warning} if warning else {}),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
