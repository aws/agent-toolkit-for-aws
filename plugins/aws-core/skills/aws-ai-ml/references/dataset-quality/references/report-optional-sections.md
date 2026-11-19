# Report Template: Duplicate Detection and Dataset Taxonomy

Read this page when writing the report of a job in which `exact_dedup`, `fuzzy_dedup` or `taxonomy` ran. `report-template.md` keeps the two section headings and their `_Not run_` lines; this page fills a section whose family ran, in place of its `_Not run_` line. The Rules of `report-template.md` apply here too.

## Duplicate detection

When `exact_dedup` or `fuzzy_dedup` ran, the section reads:

```markdown
_Identification only — nothing has been removed._

| Operator | Field | Parameters | Input rows | Flagged | Rate | Groups | Would remain |
|---|---|---|---|---|---|---|---|
| `[exact_dedup / fuzzy_dedup]` | [field] | [params from result] | [n] | [n] | [%] | [n] | [n] |

[Band flags and fuzzy caveats per deduplication/references/result-interpretation.md; row-column names (`dq_<operator>_<field>__<column>`) and the join rule.]
```

## Dataset taxonomy

When `taxonomy` ran, the section holds:

[From `quality_report.json` → `taxonomy` only. Per bound column: `taxonomy_run_id`, `input_count`, `output_count`, `excluded_count`, `count_anomaly`. Per framing (task, domain, quality): `l1_count`, `l2_count`, `l3_count`, `classified_count`, `low_confidence_count`. HTML report path: `taxonomy_report_path`. One line that the category trees are built from the scored rows when the user asks (`taxonomy/overview.md` Step 8), not here. Category-name instability caveat per taxonomy/references/result-interpretation.md.]
