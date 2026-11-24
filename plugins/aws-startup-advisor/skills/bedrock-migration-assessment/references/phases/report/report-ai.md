# Report: migration-report.html

Writes `$MIGRATION_DIR/migration-report.html`, a single self-contained HTML report for a run this skill started on its own. `scripts/report-ai.py` renders the whole document from the checked artifacts: do not write or edit the HTML yourself, and do not add narrative to it. Costs and the recommendation come from `estimation-ai.json`, the model mapping, workloads and design risks from `aws-design-ai.json`, and the answers from `preferences.json`. When Generate completed, the plan, its key risks and the file list come from `generation-ai.json` and `ai-migration/`. Every string from those files is HTML-escaped.

The report is not a phase and does not gate anything. If a step below fails, the phase that called it stays `completed`: tell the user the report was not written, quote the `error` and `detail` (from `check`, each `errors[]` entry), and carry on. `readiness.py` never lists the report, so no other skill reads or copies it.

Never in a combined run (`initiated_by` in `.phase-status.json`, or `host-answers.json` in the run directory): there the host skill writes the report. Each command refuses such a run with `combined_run` and writes nothing.

## Step 1: Plan

```bash
python3 <SKILL_BASE>/scripts/report-ai.py plan $MIGRATION_DIR
```

It checks the run through Estimate, and through Generate when `phases.generate` is `completed`, then prints the inputs with their SHA-256, the sections, and the existing report's `state`, `sha256` and `current`:

| `state`     | Meaning                                                              | Step 2                                                                         |
| ----------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `absent`    | No report yet                                                        | `write` with no hash                                                           |
| `unchanged` | This skill wrote the file and nobody changed it since                 | When `current` is true, nothing to do. Otherwise `write --expected-sha256 <sha256>` |
| `edited`    | Someone changed the file after this skill wrote it, or another tool wrote it | Ask: "migration-report.html was changed outside this skill. Replace it with a fresh report?" On yes, `write --expected-sha256 <sha256>`. On no, leave it and say the report was not updated |

## Step 2: Write

```bash
python3 <SKILL_BASE>/scripts/report-ai.py write $MIGRATION_DIR [--expected-sha256 <sha256 from plan>]
```

Pass `--expected-sha256` whenever the file exists, with the exact value `plan` printed. The script renders the document, then replaces the file in one step only when its current bytes still have that hash. Every refusal leaves the run directory unchanged.

## Step 3: Check

```bash
python3 <SKILL_BASE>/scripts/report-ai.py check $MIGRATION_DIR
```

It renders the report again from the current artifacts and compares bytes. `"ok": true` means the file is exactly what this skill would write now. Then tell the user, in one line, where the report is and that it is a draft for review.

## Errors

| Code                                                    | Where             | What to do                                                                 |
| ------------------------------------------------------- | ----------------- | -------------------------------------------------------------------------- |
| `combined_run`                                          | all               | Nothing: the host skill writes the report for a combined run                |
| `phase_incomplete`, `estimate_invalid`, `generate_invalid`, `design_invalid`, `preferences_invalid`, `profile_invalid`, `artifact_missing`, `artifact_unreadable`, and the other `readiness.py` reasons | all | The run is not complete or an artifact fails its check. Resume the run at the phase Step 0 picks; the report is written when that phase completes |
| `artifact_changed`                                      | all               | An artifact changed while the report was rendered. Run the command again   |
| `report_render_failed`                                  | all               | An artifact passed its phase check but has a shape the report cannot read; nothing was written. Quote `detail`, which names the section and the files it reads, and redo the phase that wrote that file (Clarify for `preferences.json`, Design, Estimate or Generate for their own file), then run Step 1 again |
| `report_target_invalid`                                 | all               | `migration-report.html` is a symlink, a directory or another non-regular file. Ask the user to move it away, then run Step 1 again |
| `report_unreadable`                                     | plan, write, check | The file exists but cannot be read (for example its permissions). Ask the user to fix its permissions or move it away, then run Step 1 again |
| `report_exists`                                         | write             | The file exists and no hash was passed. Run Step 1 and follow its row      |
| `report_hash_mismatch`                                  | write             | The file changed since `plan` read it. Run Step 1 again                    |
| `report_hash_unexpected`                                | write             | A hash was passed but there is no file. Run Step 1 again                   |
| `report_write_failed`                                   | write             | The file could not be written (disk full, permissions). Quote `detail`; the old report, if any, is unchanged |
| `report_not_found`                                      | check             | Run Step 2                                                                 |
| `report_section_missing`, `report_section_duplicate`, `report_toc_broken`, `report_edited` | check | The file was changed after it was written. Run Step 1; it reports `edited` |
| `report_stale`                                          | check             | An input changed after the report was written. Run Steps 1 and 2 again     |
