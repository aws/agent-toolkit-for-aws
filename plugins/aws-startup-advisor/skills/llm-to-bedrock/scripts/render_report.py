# render_report.py
"""Summarize a completed Execute run (C7) for in-chat display.

Two input modes (mutually exclusive, exactly one required):

  render_report.py --phase-results <dir> --repo <repo> [--date-suffix YYYY-MM-DD]
      Reads rewrite.json + eval.json (+ delta-decisions.json) from the
      phase-results directory — the canonical C7 path; no LLM-assembled
      payload involved.

  render_report.py <payload.json>
      Legacy single-JSON mode ({rewrite, evalRes, repo, reportDateSuffix}),
      retained for tests.

`--results-dir` keeps its original meaning in BOTH modes: the directory the
report file is copied to (default ~/saws-migrate-results).

summarize(payload) -> str is pure (testable).
"""
import json, re, sys, shutil, pathlib, argparse


def summarize(payload: dict) -> str:
    rw = payload.get("rewrite") or {}
    ev = payload.get("evalRes") or {}
    rw = rw if isinstance(rw, dict) else {}
    ev = ev if isinstance(ev, dict) else {}

    files = rw.get("files_changed") or []
    notes = ev.get("notes") or ""

    # The evaluator emits pass_rate 1.0 with a `no_golden_cases: true` notes
    # prefix when the golden dataset was empty — rendering that as "100%"
    # would misrepresent a run with zero quality scoring.
    if "no_golden_cases: true" in notes:
        pass_line = "- Prompt eval pass rate: N/A (no golden cases — quality scoring skipped)"
    else:
        pass_rate = ev.get("pass_rate")
        if isinstance(pass_rate, (int, float)):
            pass_line = f"- Prompt eval pass rate: {round(pass_rate * 100)}% ({ev.get('total_cases', 0)} cases, {ev.get('failures', 0)} failures)"
            m = re.search(r"partial_coverage: (\S+)", notes)
            if m:
                pass_line += f" — partial coverage {m.group(1)} (throttled)"
        else:
            pass_line = "- Prompt eval pass rate: (unavailable)"

    # Test counts live only in the rewriter's free-text notes (e.g. "5 tests
    # generated, 5/5 passing"); show them when parseable, omit otherwise.
    m = re.search(r"(\d+)\s*/\s*(\d+)\s+passing", rw.get("notes") or "")
    test_line = f"- Tests: {m.group(1)}/{m.group(2)} passing" if m else None

    deltas = payload.get("deltaDecisions")
    delta_line = (f"- Behavior-delta decisions applied: {len(deltas)}"
                  if isinstance(deltas, list) and deltas else None)

    lines = [
        "AI Migration Complete!",
        f"- Branch: {rw.get('branch_name', '(none)')}",
        pass_line,
        f"- Files modified: {len(files)} files",
        test_line,
        delta_line,
        f"- Report: {find_report_path(payload) or '(see repository root: MIGRATION_REPORT_*.md)'}",
    ]
    return "\n".join(l for l in lines if l)


def find_report_path(payload: dict) -> str | None:
    """Locate MIGRATION_REPORT_<suffix>.md from the payload's repo path."""
    repo = payload.get("repo")
    suffix = payload.get("reportDateSuffix")
    if not repo:
        return None
    if suffix:
        p = pathlib.Path(repo) / f"MIGRATION_REPORT_{suffix}.md"
        if p.exists():
            return str(p)
    candidates = sorted(pathlib.Path(repo).glob("MIGRATION_REPORT_*.md"))
    return str(candidates[-1]) if candidates else None


def load_phase_results(results_dir: str, repo: str, date_suffix: str | None) -> dict:
    """Assemble the summarize() payload from phase-result files. Missing or
    control-state files degrade to empty dicts (summarize handles absence)."""
    d = pathlib.Path(results_dir)

    def read(name):
        try:
            data = json.loads((d / name).read_text())
        except (OSError, json.JSONDecodeError):
            return None
        # A blocked/partial control-state file is not a payload.
        if isinstance(data, dict) and ("blocked" in data or "partial" in data):
            return None
        return data

    return {
        "rewrite": read("rewrite.json") or {},
        "evalRes": read("eval.json") or {},
        "deltaDecisions": read("delta-decisions.json"),
        "repo": repo,
        "reportDateSuffix": date_suffix,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("payload_json", nargs="?",
                    help="legacy single-JSON payload path (mutually exclusive with --phase-results)")
    ap.add_argument("--phase-results", metavar="DIR",
                    help="phase-results directory (reads rewrite.json/eval.json/delta-decisions.json)")
    ap.add_argument("--repo", help="repository root (required with --phase-results)")
    ap.add_argument("--date-suffix", help="report date suffix YYYY-MM-DD (with --phase-results)")
    ap.add_argument("--results-dir", default=str(pathlib.Path.home() / "saws-migrate-results"),
                    help="directory the report file is copied to (both modes)")
    args = ap.parse_args(argv)

    if bool(args.payload_json) == bool(args.phase_results):
        ap.error("provide exactly one of: payload_json, --phase-results")

    if args.phase_results:
        if not args.repo:
            ap.error("--phase-results requires --repo")
        payload = load_phase_results(args.phase_results, args.repo, args.date_suffix)
    else:
        try:
            payload = json.loads(pathlib.Path(args.payload_json).read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"render_report: cannot read payload JSON: {e}", file=sys.stderr)
            return 1

    report_path = find_report_path(payload)
    if report_path:
        dest_dir = pathlib.Path(args.results_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(report_path, dest_dir / pathlib.Path(report_path).name)
    print(summarize(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
