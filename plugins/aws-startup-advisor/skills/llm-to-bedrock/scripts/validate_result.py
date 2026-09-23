# validate_result.py
"""Deterministic gate for phase-result files and run-context comparison.

Two modes (design doc: docs/design-execute-orchestration-v2.md §4.2, §5.1):

1. Phase-result validation:
     validate_result.py --schema {analysis,ingestion,eval,rewrite,delta-decisions} <file>
   stdout:  RESULT=valid CONTROL=ok
            RESULT=valid CONTROL=blocked REASON=<reason>
            RESULT=valid CONTROL=partial COMPLETED=<n> TOTAL=<m>
            RESULT=invalid  + one line per error (payload-branch errors for oneOf)
   exit:    0 valid · 1 invalid · 2 file missing/unreadable/not-JSON

2. Run-context comparison:
     validate_result.py --check-run-context <saved.json> --current <current.json>
   stdout:  RUN_CONTEXT=match
            RUN_CONTEXT=mismatch + MISMATCH <path> saved=<v> current=<v> per field
            (source_key_sha256 prints only "differs" — never the hash values)
   exit:    0 match · 1 mismatch · 2 file missing/unreadable/not-JSON

Pure: argv -> stdout/exit code. No network, no AWS.
"""
import argparse
import json
import pathlib
import sys

import jsonschema

SCHEMA_NAMES = ("analysis", "ingestion", "eval", "rewrite", "delta-decisions")
SCHEMAS_DIR = pathlib.Path(__file__).parent / "schemas"

# Run metadata, not run identity — excluded from the mismatch comparison
# (design §5.1: a resume on a later calendar day must not invalidate anything).
COMPARE_EXCLUDED_FIELDS = {"report_date_suffix"}

# Fields whose values must never be printed side by side (secret fingerprints).
REDACTED_FIELDS = {"source_key_sha256"}


def load_json(path: str):
    """Returns (data, error_message). error_message is None on success."""
    p = pathlib.Path(path)
    try:
        return json.loads(p.read_text()), None
    except OSError as e:
        return None, f"cannot read {path}: {e}"
    except json.JSONDecodeError as e:
        return None, f"not valid JSON: {path}: {e}"


def control_state(data) -> tuple:
    """Pure: classify a (already schema-valid) result. Returns (control, extra)."""
    if isinstance(data, dict):
        if "blocked" in data:
            return "blocked", {"reason": data["blocked"].get("reason", "")}
        if "partial" in data:
            return "partial", {"completed": data["partial"].get("completed", 0),
                               "total": data["partial"].get("total", 0)}
    return "ok", {}


def payload_branch_errors(schema: dict, data) -> list:
    """For oneOf schemas, report errors against the payload branch (the branch
    users intend most of the time); plain schemas report directly."""
    branches = schema.get("oneOf")
    if branches and isinstance(data, dict) and ("blocked" in data or "partial" in data):
        # The user clearly intended a control state — report against that branch.
        key = "blocked" if "blocked" in data else "partial"
        for b in branches:
            if key in b.get("properties", {}):
                schema = b
                break
    elif branches:
        schema = branches[0]
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path = "$" + "".join(f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in err.absolute_path)
        errors.append(f"{path}: {err.message}")
    return errors


def validate_phase(schema_name: str, file_path: str) -> int:
    data, err = load_json(file_path)
    if err:
        print(f"RESULT=error {err}")
        return 2
    schema, err = load_json(str(SCHEMAS_DIR / f"{schema_name}.json"))
    if err:
        print(f"RESULT=error schema load failed: {err}")
        return 2

    validator = jsonschema.Draft202012Validator(schema)
    if validator.is_valid(data):
        control, extra = control_state(data)
        if control == "blocked":
            print(f"RESULT=valid CONTROL=blocked REASON={extra['reason']}")
        elif control == "partial":
            print(f"RESULT=valid CONTROL=partial COMPLETED={extra['completed']} TOTAL={extra['total']}")
        else:
            print("RESULT=valid CONTROL=ok")
        return 0

    print("RESULT=invalid")
    for line in payload_branch_errors(schema, data):
        print(line)
    return 1


def flatten(obj, prefix="$"):
    """Pure: flatten nested JSON into {path: leaf-value} for field-wise diff.
    Empty containers are recorded as sentinel values so structural differences
    (e.g. key present with {} vs key absent) are detected."""
    out = {}
    if isinstance(obj, dict):
        if not obj:
            out[prefix] = "__empty_object__"
        else:
            for k, v in obj.items():
                out.update(flatten(v, f"{prefix}.{k}"))
    elif isinstance(obj, list):
        if not obj:
            out[prefix] = "__empty_array__"
        else:
            for i, v in enumerate(obj):
                out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def top_key(path: str) -> str:
    """'$.log_files[0].sha256' -> 'log_files'."""
    rest = path[2:]
    for i, ch in enumerate(rest):
        if ch in ".[":
            return rest[:i]
    return rest


def compare_run_contexts(saved, current) -> list:
    """Pure: list of MISMATCH lines (empty = match). Strict deep equality over
    all fields minus COMPARE_EXCLUDED_FIELDS; unknown extra keys mismatch."""
    flat_saved = {p: v for p, v in flatten(saved).items()
                  if top_key(p) not in COMPARE_EXCLUDED_FIELDS}
    flat_current = {p: v for p, v in flatten(current).items()
                    if top_key(p) not in COMPARE_EXCLUDED_FIELDS}
    lines = []
    for path in sorted(set(flat_saved) | set(flat_current)):
        sv = flat_saved.get(path, "<absent>")
        cv = flat_current.get(path, "<absent>")
        if sv != cv:
            if top_key(path) in REDACTED_FIELDS:
                lines.append(f"MISMATCH {path} differs")
            else:
                lines.append(f"MISMATCH {path} saved={json.dumps(sv)} current={json.dumps(cv)}")
    return lines


def check_run_context(saved_path: str, current_path: str) -> int:
    saved, err = load_json(saved_path)
    if err:
        print(f"RUN_CONTEXT=error {err}")
        return 2
    current, err = load_json(current_path)
    if err:
        print(f"RUN_CONTEXT=error {err}")
        return 2
    lines = compare_run_contexts(saved, current)
    if not lines:
        print("RUN_CONTEXT=match")
        return 0
    print("RUN_CONTEXT=mismatch")
    for line in lines:
        print(line)
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--schema", choices=SCHEMA_NAMES)
    group.add_argument("--check-run-context", metavar="SAVED_JSON")
    ap.add_argument("--current", metavar="CURRENT_JSON",
                    help="required with --check-run-context")
    ap.add_argument("file", nargs="?", help="phase-result file (with --schema)")
    args = ap.parse_args(argv)

    if args.schema:
        if not args.file:
            ap.error("--schema requires a phase-result file argument")
        return validate_phase(args.schema, args.file)
    if not args.current:
        ap.error("--check-run-context requires --current")
    return check_run_context(args.check_run_context, args.current)


if __name__ == "__main__":
    sys.exit(main())
