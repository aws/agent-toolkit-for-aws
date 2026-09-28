#!/usr/bin/env python3
"""Score every agent_session unit in answers.json and print scoring-result JSON.

Thin driver over scoring.py (which stays a pure function): loops units, merges
system + unit answers, loads run-materialized verification evidence, and mirrors
the primary unit's result at the top level so single-unit consumers that read
`scoring-result.verdict` keep working.

Usage: uv run score_units.py /path/to/answers.json > scoring-result.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scoring  # noqa: E402

RUN_EVIDENCE_FILENAME = "current-run-verifications.json"


def _load_run_evidence(answers_path: Path):
    """Load evidence created for this run, or return no evidence when absent."""
    evidence_path = answers_path.parent / RUN_EVIDENCE_FILENAME
    if not evidence_path.exists():
        return None
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not scoring.is_run_materialized_evidence(evidence):
        raise ValueError(f"{evidence_path}: invalid run-materialized evidence")
    if evidence["run_id"] != answers_path.parent.name:
        raise ValueError(
            f"{evidence_path}: run_id must match the answers.json run directory"
        )
    return evidence


def main(argv=None) -> int:
    if argv is None:
        if len(sys.argv) != 2:
            print(__doc__.strip().splitlines()[-1], file=sys.stderr)
            return 2
        answers_path = Path(sys.argv[1])
    else:
        if len(argv) != 1:
            print(__doc__.strip().splitlines()[-1], file=sys.stderr)
            return 2
        answers_path = Path(argv[0])
    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    run_evidence = _load_run_evidence(answers_path)
    entry_point = answers.get("entry_point", "build_scratch")
    system_answers = {
        key: value
        for key, value in answers["system"].items()
        if key not in ("current_run_verifications", "provenance")
    }
    units = {
        unit_id: scoring.score(
            {
                "entry_point": entry_point,
                "answers": {
                    **system_answers,
                    **{
                        k: v
                        for k, v in info.items()
                        if k not in ("workload_class", "provenance")
                    },
                },
            },
            run_evidence=run_evidence,
        )
        for unit_id, info in answers["units"].items()
        if info.get("workload_class") == "agent_session"
    }
    out = {"units": units}
    # Collapse mirror: the scope gate guarantees >=1 agent_session unit, so
    # `units` is non-empty and a mirror always exists.
    primary = answers.get("primary_unit")
    mirror = units.get(primary) or next(iter(units.values()))
    out.update(mirror)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
