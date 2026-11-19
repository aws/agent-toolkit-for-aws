#!/usr/bin/env python3
"""Print every `quality_report.json` field the report template's named sections do not render.

    python3 <skill-root>/references/dataset-quality/scripts/other_aggregate_fields.py \\
        <path to quality_report.json>
    python3 .../other_aggregate_fields.py quality_report.json --covered my_covered_paths.txt

Reads a local copy of the job's aggregate `quality_report.json` (never the row-level
file), walks every family in it (the top level, each operator's runs, `spec_eval[0].result`
whole) and prints the leaves whose path no named section of `report-template.md`
renders, as one Markdown table `| Field (path) | Value |`. One row per leaf; a nested
object is flattened to a dotted path; a list of scalars is one row holding the JSON list
verbatim; a list of objects is one row per element index (`warnings[0].code`). `null` is
printed as `null`, a string whole, never cut (`|` is written `\\|` and a line break `<br>`
so the table stays a table). When every leaf is covered the output is the one word
`none`. `COVERED` below is the one place that lists the paths the template's named
sections already render, built from the template's Sources table and sections; `--covered
FILE` (one path pattern per line, `*` matching one key or index) replaces it. A pattern is
per path, not per criterion: a path stays in `COVERED` only while the named section renders
it for every criterion. So the Checks row states a `context: documents` criterion's
`row_level_criteria.<id>` `pass_count` / `n_evaluated` / `pass_rate` (0 / 0 / null) beside
its `context_criteria.<id>` result, the Measurements row states a metric criterion's
`row_level_criteria.<id>` `pass_count` / `n_evaluated` / `pass_rate` (0 / 0 / null too: a
measurement grades no row; the summary key carries the measurement) beside the summary
fields of its entry, and the Coverage line prints `verifier_integrity`'s
`verifiers_missing` and `verifiers_errored` as JSON lists; those paths are covered and are
not repeated here. For a `context: documents` criterion, check or metric, the same Result or
Summary cell also states the two counts of rows the documents grading did not grade,
`context_criteria.<id>` `n_not_applicable` / `n_not_evaluable`, and `n_without_evidence`, the
graded rows whose cited evidence was not verified against the documents, so those three paths
are covered too while the entry's other counts stay rows.
An empty container (`{}` or `[]`) whose path is a proper prefix of a
`COVERED` pattern is covered too (the named section renders that family, empty or not, so
`aggregate_criteria: {}` is no row); an empty container no pattern's family names stays a row
(`{}` says the family is present and empty). Used by `report-template.md` "Other aggregate
fields": run it and paste the output whole.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterator, List, Sequence, Tuple, Union

Segment = Union[str, int]
Path = Tuple[Segment, ...]

# The paths the template's named sections render, by section (report-template.md).
# A pattern covers the leaf it names and every leaf below it; `*` matches one key or index.
COVERED = (
    # Header: Rows, Format
    "total_samples",
    "derived_inputs.format",
    # Spec-driven evaluation: the Spec, Coverage and Rows lines (the Coverage line renders
    # all_criteria_covered as its word and the two verifier arrays as JSON lists)
    "spec_eval[*].result.judge_model_id",
    "spec_eval[*].result.grading_criteria_declared",
    "spec_eval[*].result.metric_criteria_declared",
    "spec_eval[*].result.codegen_attempts",
    "spec_eval[*].result.verifier_integrity.verifiers_missing",
    "spec_eval[*].result.verifier_integrity.verifiers_errored",
    "spec_eval[*].result.verifier_integrity.all_criteria_covered",
    "spec_eval[*].result.rows_passed",
    "spec_eval[*].result.rows_failed",
    "spec_eval[*].result.rows_not_evaluable",
    "spec_eval[*].result.llm_api_calls",
    "spec_eval[*].result.row_level_criteria.*.n_field_too_long",
    "spec_eval[*].result.row_level_criteria.*.n_row_too_large",
    "spec_eval[*].result.context_criteria.*.n_field_too_long",
    "spec_eval[*].result.context_criteria.*.n_row_too_large",
    # Checks and Measurements: per row criterion (for a `context: documents` criterion the
    # Checks row states pass_count / n_evaluated / pass_rate of this entry beside the
    # context_criteria result, and for a metric criterion the Measurements row states them
    # beside the summary fields, so the three stay covered)
    "spec_eval[*].result.row_level_criteria.*.type",
    "spec_eval[*].result.row_level_criteria.*.justification",
    "spec_eval[*].result.row_level_criteria.*.reads",
    "spec_eval[*].result.row_level_criteria.*.pass_rate",
    "spec_eval[*].result.row_level_criteria.*.pass_count",
    "spec_eval[*].result.row_level_criteria.*.n_evaluated",
    # (the bare top_failure_modes path covers the `null` of a criterion with no failures)
    "spec_eval[*].result.row_level_criteria.*.top_failure_modes",
    "spec_eval[*].result.row_level_criteria.*.top_failure_modes.*.reason",
    "spec_eval[*].result.row_level_criteria.*.top_failure_modes.*.count",
    "spec_eval[*].result.row_level_criteria.*.top_failure_modes.*.fraction",
    "spec_eval[*].result.row_level_criteria.*.is_metric",
    "spec_eval[*].result.row_level_criteria.*.values",
    "spec_eval[*].result.row_level_criteria.*.value_summary",
    # Checks and Measurements: a `context: documents` criterion's Result and summary
    "spec_eval[*].result.context_criteria.*.pass_rate",
    "spec_eval[*].result.context_criteria.*.n_pass",
    "spec_eval[*].result.context_criteria.*.pass_rate_denominator",
    "spec_eval[*].result.context_criteria.*.top_failure_modes",
    "spec_eval[*].result.context_criteria.*.top_failure_modes.*.reason",
    "spec_eval[*].result.context_criteria.*.top_failure_modes.*.count",
    "spec_eval[*].result.context_criteria.*.top_failure_modes.*.fraction",
    "spec_eval[*].result.context_criteria.*.values",
    "spec_eval[*].result.context_criteria.*.value_summary",
    "spec_eval[*].result.context_criteria.*.n_measured",
    # (the same cell states the two counts of rows the documents grading did not grade —
    # n_not_applicable / n_not_evaluable, outside pass_rate_denominator — and, apart,
    # n_without_evidence, the graded rows whose cited evidence was not verified against the
    # documents — so the three are covered; the entry's other counts — n_fail,
    # n_not_applicable_no_claim, n_evidence_verified, quote_verified.*, ... — stay rows)
    "spec_eval[*].result.context_criteria.*.n_not_applicable",
    "spec_eval[*].result.context_criteria.*.n_not_evaluable",
    "spec_eval[*].result.context_criteria.*.n_without_evidence",
    # Aggregate criteria
    "spec_eval[*].result.aggregate_criteria.*.type",
    "spec_eval[*].result.aggregate_criteria.*.justification",
    "spec_eval[*].result.aggregate_criteria.*.reads",
    "spec_eval[*].result.aggregate_criteria.*.pass_rate",
    "spec_eval[*].result.aggregate_criteria.*.top_failure_modes",
    "spec_eval[*].result.aggregate_criteria.*.top_failure_modes.*.reason",
    "spec_eval[*].result.aggregate_criteria.*.top_failure_modes.*.count",
    "spec_eval[*].result.aggregate_criteria.*.top_failure_modes.*.fraction",
    "spec_eval[*].result.aggregate_criteria.*.is_metric",
    "spec_eval[*].result.aggregate_criteria.*.value",
    "spec_eval[*].result.aggregate_criteria.*.verdict",
    # Duplicate detection
    "exact_dedup[*].view",
    "exact_dedup[*].params",
    "exact_dedup[*].result.input_count",
    "exact_dedup[*].result.duplicate_count",
    "exact_dedup[*].result.duplicate_groups",
    "exact_dedup[*].result.distinct_count",
    "exact_dedup[*].result.duplicate_rate",
    "fuzzy_dedup[*].view",
    "fuzzy_dedup[*].params",
    "fuzzy_dedup[*].result.input_count",
    "fuzzy_dedup[*].result.duplicate_count",
    "fuzzy_dedup[*].result.duplicate_groups",
    "fuzzy_dedup[*].result.distinct_count",
    "fuzzy_dedup[*].result.duplicate_rate",
    # Dataset taxonomy
    "taxonomy[*].view",
    "taxonomy[*].params",
    "taxonomy[*].result.taxonomy_run_id",
    "taxonomy[*].result.input_count",
    "taxonomy[*].result.output_count",
    "taxonomy[*].result.excluded_count",
    "taxonomy[*].result.count_anomaly",
    "taxonomy[*].result.framings.*.l1_count",
    "taxonomy[*].result.framings.*.l2_count",
    "taxonomy[*].result.framings.*.l3_count",
    "taxonomy[*].result.framings.*.classified_count",
    "taxonomy[*].result.framings.*.low_confidence_count",
    "taxonomy[*].result.taxonomy_report_path",
    # Exploratory findings are presented in the conversation, never in the report
    "exploratory_analysis",
)
# Every other top-level operator is a deterministic metric: its Deterministic row renders
# the view (Bound to), the params (Parameters) and the result fields verbatim (Result).
NAMED_FAMILIES = ("spec_eval", "exact_dedup", "fuzzy_dedup", "taxonomy", "exploratory_analysis")
DETERMINISTIC_RUN_FIELDS = ("view", "params", "result")


def _parse_pattern(text: str) -> Path:
    segments: List[Segment] = []
    for piece in text.strip().split("."):
        name, _, rest = piece.partition("[")
        if name:
            segments.append(name)
        while rest:
            index, _, rest = rest.partition("]")
            segments.append("*" if index == "*" else int(index))
            rest = rest.lstrip("[")
    return tuple(segments)


def _is_empty_container(value: Any) -> bool:
    return isinstance(value, (dict, list)) and not value


def _matches(pattern: Path, path: Path, value: Any = None) -> bool:
    # A pattern covers the leaf it names and everything below it, and an empty container
    # (`{}` or `[]`) whose path is a proper prefix of the pattern: the pattern's family,
    # which the named section renders whether empty or not.
    if len(pattern) > len(path) and not _is_empty_container(value):
        return False
    return all(want == "*" or want == got for want, got in zip(pattern, path))


def _is_run_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(run, dict) for run in value)


def covered_patterns(report: dict, covered: Sequence[str]) -> List[Path]:
    patterns = [_parse_pattern(text) for text in covered if text.strip()]
    for key, value in report.items():
        if key not in NAMED_FAMILIES and _is_run_list(value):
            patterns.extend((key, "*", field) for field in DETERMINISTIC_RUN_FIELDS)
    return patterns


def _scalar_list(value: Any) -> bool:
    return isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value)


def leaves(value: Any, path: Path = ()) -> Iterator[Tuple[Path, Any]]:
    """Every leaf of `value` with its path: scalars, lists of scalars, empty objects and lists."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from leaves(item, path + (key,))
    elif isinstance(value, list) and value and not _scalar_list(value):
        for index, item in enumerate(value):
            yield from leaves(item, path + (index,))
    else:
        yield path, value


def render_path(path: Path) -> str:
    text = ""
    for segment in path:
        text += f"[{segment}]" if isinstance(segment, int) else (f".{segment}" if text else segment)
    return text


def render_value(value: Any) -> str:
    # A string whole, never cut; everything else as JSON (`null`, `true`, numbers, a list verbatim)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def other_fields(report: dict, covered: Sequence[str] = COVERED) -> List[Tuple[str, Any]]:
    """The (path, value) leaves of `report` no covered pattern matches, in file order."""
    patterns = covered_patterns(report, covered)
    return [
        (render_path(path), value)
        for path, value in leaves(report)
        if not any(_matches(pattern, path, value) for pattern in patterns)
    ]


def table(rows: Sequence[Tuple[str, Any]]) -> str:
    if not rows:
        return "none"
    lines = ["| Field (path) | Value |", "|---|---|"]
    lines.extend(f"| `{path}` | {render_value(value)} |" for path, value in rows)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", help="local path to the job's aggregate quality_report.json")
    parser.add_argument(
        "--covered",
        metavar="FILE",
        help="one covered path pattern per line; replaces the built-in list",
    )
    args = parser.parse_args(argv)
    with open(args.report, encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise SystemExit(f"not an aggregate report (expected a JSON object): {args.report}")
    covered: Sequence[str] = COVERED
    if args.covered:
        with open(args.covered, encoding="utf-8") as handle:
            covered = [
                line
                for line in handle.read().splitlines()
                if line.strip() and not line.startswith("#")
            ]
    print(table(other_fields(report, covered)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
