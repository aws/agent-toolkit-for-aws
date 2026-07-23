# Orchestration — phase workflow & state model

> AI-facing knowledge (the AI reads this to drive the migration); it is **not** executed code.
> The patterns below were proven in the pre-restructure `tools/orchestrator.py` engine; here
> they are guidance for how *you (the AI)* sequence phases and persist state in files.

## Purpose
Describe how the AI sequences a Teradata→Redshift migration end to end, how state is
persisted so work is resumable, and how execution adapts to the customer's connectivity.

## Phases
Run in order; each phase's `result/` is the durable hand-off that feeds the next.

| # | Phase | Reads | Produces (`output/<phase>/result/`) |
|---|-------|-------|-------------------------------------|
| 1 | **Discovery** | `references/teradata/discovery-queries.md` | `discovery/result/inventory.json` |
| 2 | **Conversion** (incl. code review) | `conversion-rules.md`, `data-type-mapping.md`, `architecture-mapping.md`, `stored-procedure-migration.md`, `bteq-to-rsql.md`, `common-errors.md` | `conversion/result/{ddl,sql,procedures,rsql}/`, `manual_review.json` |
| 3 | **Data migration** | `data-migration-patterns.md`, `inventory.json` | `data_migration/result/{extract,load,templates}/`, `migration_manifest.json` |
| 4 | **Validation** | `validation-patterns.md`, `migration_manifest.json` | `validation/result/validation_report.json` |
| 5 | **Performance** | `performance.md` | `performance/result/{perf_baseline,perf_compare}.json` |
| 6 | **Reporting** | `reporting.md` + every prior `result/` | `reporting/result/migration_report.md` |

> Conversion folds in a **code-review gate**: low conversion confidence (scored per the rubric
> in `conversion-rules.md`) or constructs with no deterministic rule (functions, triggers, join
> indexes, `RESET WHEN`) are written to `manual_review.json` and pause the run — see
> *HITL gate* below.

## Phase status lifecycle
Every phase has exactly one explicit status. Record it in `state.md` so the run is observable.

```
PENDING ──▶ RUNNING ──▶ SUCCESS        (continue to next phase)
                   │
                   ├──▶ SKIPPED         (phase not applicable this run; continue)
                   ├──▶ NEEDS_REVIEW    (HITL pause — a human must decide, then resume)
                   └──▶ FAILED          (stop — diagnose, fix, resume)
```

- **SUCCESS / SKIPPED** let the pipeline proceed.
- **NEEDS_REVIEW / FAILED** stop the run. Resume re-enters at the first non-`SUCCESS` phase,
  which is what makes resume idempotent (already-`SUCCESS` phases are not redone).

## HITL gate (when to pause for human review)
Pause the phase as `NEEDS_REVIEW` — do **not** silently proceed — when:

- **Conversion:** an object's **conversion confidence < threshold** (default `0.70`, matching the rubric's High-weight auto-flag ceiling in `conversion-rules.md`; scored per
  the rubric in `conversion-rules.md`), any **manual-review items** are flagged, or the object
  kind has no deterministic rule (function / trigger / join index). Summarize as
  `{objects, needs_review, min_confidence}`.
- **Data migration:** **any** table failed to extract/stage/load. Validating a partial load
  as if it were complete hides real problems — pause instead.
- **Validation:** any table's status is `fail` and the operator has not accepted the diff.

After a human decides, record the decision and call resume.

## State model (resumability)

- All generated artifacts live under `output/` (git-ignored) in the user's working dir.
- `output/state.md` is the **single source of truth** for progress — the durable cursor that
  survives process restarts, machine changes, and disconnected copy-backs.
- **Durable vs ephemeral:** the per-phase status + the pointer to each phase's `result/` are
  durable (written to `state.md` / files). Live in-memory objects (the discovery `inventory`,
  the migration `manifest`) are **ephemeral** — intentionally not persisted. On a resumed run
  the AI re-derives them by reading the prior phase's `result/` (e.g. re-read `inventory.json`)
  rather than expecting them in memory.
- After every phase transition, update `state.md` **before** starting the next phase.

### `state.md` schema (example)

```markdown
# Migration run state
run_id: acme-edw-2026-06-29
source_db: teradata
strategy: full-load
updated: 2026-06-29T17:40:00Z

| phase          | status        | result pointer                                   | note |
|----------------|---------------|--------------------------------------------------|------|
| discovery      | success       | output/discovery/result/inventory.json           | 3 schemas, 214 tables |
| conversion     | needs_review  | output/conversion/result/manual_review.json      | 7 objects < 0.8 confidence |
| data_migration | pending       | —                                                | |
| validation     | pending       | —                                                | |
| performance    | pending       | —                                                | |
| reporting      | pending       | —                                                | |
```

Keep one row per phase. `result pointer` is the relative path the next phase reads.

## Hand-off contract between phases

- A phase may start only when the **previous phase's status is `SUCCESS`** (or `SKIPPED` when
  not applicable) and its `result/` artifact exists and is readable.
- Each phase reads **only** its declared inputs (see the Phases table) — never another phase's
  in-memory state. This keeps every phase independently runnable and testable.
- A phase writes its outputs to `result/` **before** marking itself `SUCCESS`, so a crash
  between "wrote files" and "marked success" simply re-runs the phase (idempotent).

## Decision points (guidance for the AI)

- **Full vs incremental load** — default to `full-load` (truncate-and-reload, idempotent). Use
  incremental/CDC only when the table is too large to reload in the cutover window *and* a
  reliable high-water-mark column exists. See `data-migration-patterns.md`.
- **Connected vs disconnected** — see Execution modes. Decide once at run start; it changes
  whether you run scripts in place or emit a bundle.
- **Stop vs continue on a failed object** — a single failed table or low-confidence conversion
  pauses the run for review; it does not abort the whole migration. Other tables already
  `SUCCESS` are preserved.

## Execution modes

- **Connected** — agent host can reach TD/RS → it runs generated scripts in place and writes
  `result/` directly.
- **Disconnected** — agent emits a self-contained `output/<phase>/` bundle (script + co-located
  creds template + relative `result/` + `run-instructions.md`); the operator runs it on a
  reachable host and copies `result/` back. The copied-back `result/` (+ `state.md`) is the
  durable state — read it and continue from the first non-`SUCCESS` phase.

## See also

- `SKILL.md` — phase list and project-workspace layout (keep this table in sync with it).
- `data-migration-patterns.md` — `migration_manifest.json` contract consumed by validation.
- `validation-patterns.md` — `validation_report.json` consumed by reporting.
