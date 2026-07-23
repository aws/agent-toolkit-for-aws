# Reporting — migration status report

> AI-facing knowledge: how to aggregate every phase's artifacts into a single report.

## Purpose

Roll up the per-phase `result/` artifacts into one customer-facing migration report at
`output/reporting/result/migration_report.md` (plus optional `.json` for machines / `.html` for
sharing). The report answers: what was migrated, how much was automated, what passed validation,
how performance compares, and what manual work remains.

## Inputs (the data contracts it aggregates)

| Phase | Artifact | What the report pulls |
|-------|----------|------------------------|
| Discovery | `discovery/result/inventory.json` | object counts by type, total tables/rows/size |
| Conversion | converted DDL/SQL/RSQL + `conversion/result/manual_review.json` | objects converted, confidence scores, manual-review backlog |
| Data migration | `data_migration/result/migration_manifest.json` | tables loaded, row counts, bytes, per-table status |
| Validation | `validation/result/validation_report.json` | per-table pass/fail, mismatches |
| Performance | `performance/result/perf_baseline.json`, `perf_compare.json` | TD vs RS runtimes, regressions |

Read whatever artifacts exist (a partial run still produces a partial report — note missing phases
rather than failing).

## Report sections

1. **Executive summary** — scope (databases/objects/rows), **% automated** (objects converted at
   high confidence with no manual-review items ÷ total), validation pass rate, headline perf delta,
   count of open manual items.
2. **Discovery** — inventory snapshot (objects by type, largest tables).
3. **Conversion** — converted vs flagged, confidence distribution, unconvertible kinds
   (function/trigger/join-index). Pull the backlog from `manual_review.json`.
4. **Data migration** — tables migrated, total rows/bytes, failures (from the manifest).
5. **Validation** — pass/fail per table, summary of mismatches and tolerances applied.
6. **Performance** — per-query and aggregate TD→RS deltas; call out regressions.
7. **Manual-review backlog** — consolidated list (construct, location, suggested fix, owner)
   sourced from conversion confidence + flagged items.
8. **Risks & next steps** — anything blocking cutover.

## `migration_report.json` (machine-readable shape)

```json
{
  "generated_at": "ISO-8601",
  "scope": {"databases": 2, "tables": 31, "rows": 19500000},
  "summary": {
    "objects_total": 0, "objects_converted": 0, "pct_automated": 0.0,
    "validation_pass_rate": 0.0, "manual_review_items": 0,
    "perf_delta_pct_median": 0.0
  },
  "phases": {
    "discovery":   {"status": "complete", "artifact": "discovery/result/inventory.json"},
    "conversion":  {"status": "complete", "converted": 0, "flagged": 0, "low_confidence": 0},
    "data_migration": {"status": "complete", "tables_loaded": 0, "tables_failed": 0, "rows": 0},
    "validation":  {"status": "complete", "tables_passed": 0, "tables_failed": 0},
    "performance": {"status": "complete", "regressions": 0}
  },
  "manual_review": [
    {"object": "db.proc_x", "construct": "QUALIFY+GROUP BY", "confidence": 0.7, "suggestion": "…"}
  ],
  "risks": []
}
```

## How automation % + backlog roll up

- The conversion phase assigns a **confidence score** (per the rubric in
  `conversion-rules.md`) and **manual-review items** per object. Count an object as "automated"
  when confidence is high **and** it has zero manual-review items **and** it isn't an
  unconvertible kind. `pct_automated` = automated ÷ total objects.
- The **backlog** = union of all objects with manual-review items or below the confidence threshold,
  carrying the construct + suggested fix straight from the conversion output (`manual_review.json`) — that's the actionable
  to-do list for the team.

## Generation notes

- The AI generates the report script/templating at runtime; this doc is the **structure + contract**,
  not code.
- Keep numbers traceable: every figure should be derivable from a named artifact above.

## TODO / extend

- `manual_review.json` schema is defined in `conversion-rules.md` (producer). The report reads its `items[]` (object, object_kind, construct, suggested_rewrite, confidence, status) + `summary` for the backlog and % automated.
- Add an HTML template once a sample full run exists.
