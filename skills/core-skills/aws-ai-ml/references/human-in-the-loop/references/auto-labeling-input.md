# Auto-Labeling Input

Used by `overview.md` when the data file comes from `auto-labeling`: its review set (`review.jsonl`: the rows below the cutoff, and the spot-check rows drawn from the auto-accepted rows) or its cold-start sample (rows people label from scratch). Auto-labeling's side of the seam is `auto-labeling/references/input-output-contract.md`, "Human-in-the-loop hand-off". This skill shows the rows blind, collects one answer per row and hands the export back; auto-labeling folds it onto its rows by the id field and scores it. Who applies the corrections to the labeled dataset depends on the hand-off (After the review, below). For this input, `<project-dir>` is auto-labeling's project directory (`<proj>`), so the hand-off files and `data/hil/` sit in one directory.

## The hand-off spec

Auto-labeling can hand over a spec with the review set, a JSON file in its project such as `<proj>/hil_handoff.json`. Its path is the one auto-labeling gives when it hands over the review set, else `<proj>/hil_handoff.json`; when there is no such file, take the no-spec path below. Its keys supply the inputs of `overview.md` → Inputs:

| Key | What it gives |
|---|---|
| `ProjectName` | The project name |
| `TaskDescription` | The task description |
| `Recommendation` | The recommendation: which field the annotator writes |
| `QuestionContext` | The question context: the label set and its one-line definitions, the only part of the labeling spec annotators see |
| `Data.LowConfidence` | The data file: the review DataSet ARN, an S3 URI, or a local review file |
| `Contract.task` | The labeling task: `classification`, `ner`, `qa`, `ordinal`, `llm_judge` or `summarization` |
| `Contract.prediction_field` | The field that holds the annotator's answer |
| `Contract.id_field` | The record id field |
| `Contract.text_fields` | The input fields annotators see |
| `Contract.hidden_fields` | Fields never shown to an annotator or uploaded: the model's answer and outputs, and the routing tags `split` and `_review_reason` |

`Contract.corrections`, when present, says that auto-labeling applies the corrections itself (After the review, below); this skill reads only its presence. The other keys (`Data.Dataset`, the labeled DataSet; `Data.Format`; and `Contract`'s split, export, scoring, fold, overlay and check keys) are for auto-labeling's side; this skill does not read them. Without a spec, or when `Contract.text_fields` is empty, the task and input fields are the labeling run's `--task` and `--text-fields`, the id field is `id`, the prediction field is the task's (`auto-labeling/references/input-output-contract.md`, "is task-specific (`--task`)"), and the label set and definitions come from the labeling spec's Label Set section.

When `Data.LowConfidence` is the review DataSet ARN, its document names the labeling job's `review/` folder. The job writes only the review rows there (`review_rows.jsonl`), and their side file under its `labeling/` folder; auto-labeling owns that layout. `read_records()` reads the one `.jsonl` in `review/`, so a folder with none or several stops at the Step 1 question. The side file with the model's answers, whichever layout wrote it (`review.model_output.jsonl` next to a `route_to_review.py` review file, or the job's `labeling/review_rows.model_output.jsonl`), stays out of the review (`references/local-review-guide.md` → Step 3b: Per-record display in the review loop).

## Record ids

The id field is `Contract.id_field` (default `id`; below, "the id field"). Every row needs a non-empty value in it that no other row shares, because the fold puts each answer on the row with that id. Step 1 checks the rows with `python scripts/record_ids.py <file> --id-field <the id field>`, where `<file>` is the local data file, or, for an S3 or DataSet input, `<project-dir>/data/hil/review_records.jsonl` with the rows it read written there (exit 1: the output names the rows and ids; exit 2: the file could not be read, handled as a failed read at the Step 1 question), and Step 3a.7 passes the same `--id-field`, so `setup` refuses the same rows too (`references/label-studio-space.md` → Troubleshooting, exit 4). Never fill in, renumber or deduplicate an id: the export carries each id exactly as the row has it. Every join of the export to the rows (Step 6) matches on the id field alone (a local row's `record_id`, or a Label Studio row's `data.<id field>`, holds the row's id field value), compared as strings, with no content-hash or position fallback.

## What annotators see and answer

Annotators see the id field and the input fields only (`references/local-review-guide.md` → Step 3b: Per-record display in the review loop). The one annotation question asks for the value of the prediction field, from `QuestionContext`. There is no question about whether a label is right, and no issue tags or correction text, because no model answer is shown. When auto-labeling or its plan asks for an annotator score as well (a 1-to-5 rating, or a question the user wrote), it is one more question after the label; in Label Studio, a control named `consensus_score` (a `Rating` for 1 to 5).

| Task | The annotator gives | Local review: `corrected_completion` holds | Label Studio control, and the `references/label-config-templates.md` example to start from |
|---|---|---|---|
| `classification` | One label from the label set | The label | `<Choices name="label" choice="single">`, one `<Choice>` per label spelled as in the label set; Text classification |
| `ner` | Every entity span in the text, with its type | A JSON array of `{"type", "text"}` objects (not a string), `[]` when the text has none | `<Labels name="entities">`, one `<Label>` per entity type, on the field that holds the entities (its spans also carry `start` and `end`); Named Entity Recognition |
| `qa` | The answer copied exactly from the passage | The answer text, `""` when the passage has none | `<TextArea name="answer" maxSubmissions="1">`; Extractive question answering |
| `ordinal` | A score on the labeling spec's scale | The score | `<Number name="score">`, `min` and `max` the ends of the scale; Numeric score |
| `llm_judge` | A score on the rubric's scale | The score | `<Number name="judge_score">`, the ends of the rubric's scale; Numeric score |
| `summarization` | A summary of the text | The summary | `<TextArea name="summary" maxSubmissions="1">`; Summary authoring |

In the Label Studio config, the answer control's `name` is the prediction field: `Contract.prediction_field`, or, in the cases the hand-off spec section above names (no spec, or an empty `Contract.text_fields`), the task's default shown in the table. The config has one `<Text>` per input field, named after the field (`value="$<field>"`), and nothing else of the record, with no pre-annotations (`predictions`). The approved question and the label definitions from `QuestionContext` go where the note under `references/label-config-templates.md` → Text classification says. Mark the answer control `required="true"`, except for `qa` and `ner`, whose empty answer is valid.

The fold compares a `qa` answer exactly by default, so annotators copy the answer from the passage rather than retyping it. Label Studio exports no value for an empty text box, so a `qa` row whose passage has no answer comes back unlabeled from Label Studio; local review records it as `""`. For `qa`, recommend local review at the Step 2 checkpoint and let the user confirm; this overrides `references/local-review-guide.md` → Step 0c (always recommend Label Studio, and only when asked) for this task.

Every row is reviewed: offer no subset at Step 3b.1, because the fold counts each unreturned spot-check row as an error and the cold-start check needs every sample row back. A row the annotator can't decide is skipped (local review: `status: skipped`; Label Studio: Skip), which the fold counts as an error on a spot-check row; the Step 2 checkpoint says so with the row count. For the cold-start sample, the Step 2 checkpoint also shows what `auto-labeling/references/cold-start.md`, Step B asks for.

## The export

- **Local review:** one row per reviewed record, schema in `references/local-review-guide.md` → Auto-labeling rows.
- **Label Studio:** the `ls_space_client.py export` file as it is. The fold reads each task's id field from its `data`, and the answer from the control named after the prediction field, so do not rename or remap any field.

In both cases the export carries no `split`: auto-labeling reads it from its own records. The confirmed, corrected and spot-check counts come from auto-labeling's fold, not from this skill (`references/post-hil-metrics.md`, Auto-labeling input).

## After the review (Steps 7 and 8)

**When the hand-off spec carries `Contract.corrections`,** auto-labeling folds the export and writes the people's labels onto its labeled dataset itself, so this skill does not apply them: there is no edit plan, and Step 8 does not run.

- **Step 7** asks only about the rows it flags, and only when there are any: in Label Studio mode its attribution question and relabel round (`overview.md`, Step 7), and in either mode the rows Principle 4 flags (in local review, the user keeps such a row's answer or labels the row again in chat). When no row is flagged, Step 7 asks nothing and records nothing.
- **Step 8:** only its last paragraph applies: in Label Studio mode, tell the user what `references/label-studio-space.md` → Stopping and cleaning up says about the app's and the space's charges.

**Otherwise** (no hand-off spec, or one without `Contract.corrections`), the cold-start sample ends the same way, and for the review set this skill merges the corrections in Steps 7 and 8:

| Outcome | Edit to the labeled dataset (auto-labeling's `labels.jsonl`) |
|---|---|
| The annotator answered (`status: completed`; `""` for `qa` and `[]` for `ner` are answers) | Replace the row's prediction field with it, on the row with the same id |
| Skipped, or not returned | Keep the row unchanged: it keeps the model's label |

No row is removed, no other field changes, and no `split` is added. The Step 7 checkpoint shows how many rows will be replaced and kept, and that the edited file then replaces auto-labeling's `labels.jsonl`, with the current file kept as the backup that Replace `labels.jsonl` (below) names, so this round's replacement can be undone from it; the model's labels also stay in the labeling job's output. Step 8's Transformation Spec:

- `input`: auto-labeling's `labels.jsonl`; `output`: `<project-dir>/data/hil/updated_dataset.jsonl`.
- Join each export row to a dataset row as in Record ids above.
- Copy the value exactly as the export holds it: `corrected_completion` from local review, or the answer to the control named after the prediction field from Label Studio (for `ner`, one `{"text", "type", "start", "end"}` per label of each span, `type` being that label). Do not normalize one review mode's shape to the other's: auto-labeling's fold check compares the labeled dataset's value with the export's value as it is, and its NER scoring reads only `type` and `text`, so the extra `start` and `end` change no score. Ignore skipped annotations. When a task has several submitted annotations that agree, use that value; when they disagree, keep the row unchanged and report its id.
- Keep every row, in order, and every other column. `dataset-transformation` reports the counts replaced and kept.

### Replace `labels.jsonl`

This is the replacement the Step 7 checkpoint approved, made because auto-labeling continues with the merged `labels.jsonl` (`auto-labeling/references/full-loop.md`, Step 7b). This is the one exception to Step 8's rule that this skill does not modify the dataset itself: it moves `dataset-transformation`'s output and changes no row.

1. Confirm that `dataset-transformation` wrote `<project-dir>/data/hil/updated_dataset.jsonl` and that its counts match the approved plan.
2. Copy `<project-dir>/labels.jsonl` to `<project-dir>/data/hil/labels.before_hil.<n>.jsonl`, with `<n>` 1 for the first round and otherwise one more than the highest backup already there, so no earlier backup is overwritten.
3. Move `<project-dir>/data/hil/updated_dataset.jsonl` to `<project-dir>/labels.jsonl`.
4. Tell the user that `labels.jsonl` now holds the annotators' labels (the same rows as before, with the annotators' answers in the prediction field), and the backup's path.

### Hand back the export

For every auto-labeling input, hand back the export right after Step 7 when this skill merges nothing (with `Contract.corrections`, and for the cold-start sample; Step 8's billing reminder still follows in Label Studio mode), else after Replace `labels.jsonl`. Record it in the HIL log:

```bash
python scripts/hil_log.py write --project-dir <project-dir> --kind artifact --step <plan-step or human-in-the-loop-export> \
  --iteration <iteration or 0> --status completed --fields-json '{"artifact": "hil-export", "export_path": "<export>", "review_mode": "<local or external_tool>"}'
```

`export_path` is the absolute path of the last export Step 7 wrote, else Step 5's; the log stores it relative to `<project-dir>` when it is inside it. Tell the user both and the entry's `id` (`write` prints it), for auto-labeling's next step (`auto-labeling/references/full-loop.md`, Step 7b, names the export's columns for each review mode; for the cold-start sample, `auto-labeling/references/cold-start.md`, Step C).
