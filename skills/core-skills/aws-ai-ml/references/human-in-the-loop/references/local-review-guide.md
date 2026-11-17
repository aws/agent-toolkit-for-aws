# Local Review Guide

Used by Step 0 (sample preview + mode choice) and Step 3b (in-chat review loop) of `overview.md`. Defines the sample-printing rules, the per-record display format, the captured field schema, and the pause/resume behavior.

## When local review is the right choice

Local review is the right call when:

- **Records are short.** Prompts and completions fit comfortably in chat — typically each under ~1500 characters.
- **Volume is small.** Under ~30 records total. Anything larger gets tedious quickly.
- **The user wants a quick check.** Spot-check the worst records, sanity-check the judge, decide whether human-in-the-loop review is worth doing at scale.
- **No annotators available.** Solo review by the user, not a team annotation project.

Label Studio (set up in Step 3a) is the right call when:

- **Records are long.** Code samples, multi-turn conversations, long-form completions.
- **Volume is large.** Tens to hundreds of records.
- **Multi-annotator workflows** with inter-annotator agreement.
- **The platform's UI features are needed.** Highlighting, span annotations, structured forms.

The skill never auto-selects. It prints 5 samples (Step 0a), asks the user (the Step 0b question, at the Step 2 checkpoint), and only suggests a recommendation if the user explicitly asks (Step 0c).

## Step 0a: Sample selection

This skill samples directly from the pre-split files it receives as input. It does not re-derive bucket membership.

Target sampling (when the file is present and has ≥ 5 records):

| Bucket | Count | Selection |
|---|---|---|
| Low-confidence (from `low_confidence.jsonl`) | 4 | First 4 in file order |
| Variety check | 1 | Any record not already picked, drawn at random from the file |

Fallbacks:

- If the file contains fewer than 5 records, show all of them.

Use deterministic selection for the targeted picks (file order, not random) so the preview is reproducible across reruns. Only the variety-check pick is random.

## Step 0a: Per-sample display format

Show each sample as a record with these fields:

- its position and id (the record id, or its 1-based row number)
- its quality scores: each `dq_*` column present in the row (e.g. `dq_spec_eval_pass`, `dq_spec_eval_failed_criteria`)
- the prompt, truncated to 400 chars with `…` if longer, with its total length in chars
- the completion, truncated the same way, with its total length in chars

**Always show the full character length** of prompt and completion alongside the truncated preview — this is what the user uses to judge whether records are short enough for local review. For auto-labeling input, show the id field and each input field in place of the scores, prompt and completion, by the Step 3b rule, and give the lengths of the input fields.

## Step 0b: Length summary

After the 5 samples, give a one-line summary of lengths so the user does not have to eyeball it: the average and maximum length in chars of the prompts, and of the completions, across the 5 samples.

For auto-labeling input, give the same two numbers for each input field instead. Use these numbers in the mode-choice prompt (`overview.md` Step 0b).

## Step 0c: Recommendation if the user asks

Apply only if the user explicitly asks for a recommendation. Do not auto-route.

Recommend by the criteria in *When local review is the right choice* above, using the Step 0b length summary and the record count: local review when the records are short, the batch is small and the user reviews alone; Label Studio when the records are long, the batch is large, several annotators review, or the task needs Label Studio's UI. When the signals point both ways, recommend Label Studio and say which signal decided it.

The user always makes the call.

## Step 3b: Per-record display in the review loop

Unlike the Step 0 preview, the Step 3b loop displays the **full** record — no truncation. This is the actual review.

Never display a `_`-prefixed field (`_model_output`, `_review_reason`, `_failed`, `_failed_reason`). For auto-labeling's `review.jsonl`, show the input fields only (`Contract.text_fields`, when the hand-off spec gives them) and never a `Contract.hidden_fields` field such as `split`, so a spot-check row looks like every other row (the record header names no split). Never show, propose or pre-fill a label: a reviewer who sees the model's label tends to copy it, which breaks the accuracy check the spot-check rows exist for. Its rows carry no model answer: `route_to_review.py` keeps the model's label and its other outputs in the side file next to it (`review.model_output.jsonl`). Do not show that file to reviewers or upload it; only auto-labeling's fold reads it. The same holds for auto-labeling's cold-start sample (`auto-labeling/references/cold-start.md`, Step B), whose rows carry no label at all: show the id field and the input fields, ask for the label from the spec's label set and definitions, and never show, propose or pre-fill one. Walk the sample in a shuffled order, not file order: it keeps the corpus order, and a corpus sorted by class would show long runs of one class. The same holds for the records uploaded to Label Studio (Step 3a.7 of the setup): for auto-labeling's `review.jsonl` and cold-start sample, upload the id field and the input fields only (the labeling run's `--text-fields`, passed as `--data-fields` to `ls_space_client.py setup`, which drops every other field except `id`, the `--id-field` value and `unique_id`), the sample's records in a shuffled order, and keep the full file, and a review file's side file, for the fold.

Show each record with:

- its position in the review and the total (record i of N), and its id
- its quality scores: each `dq_*` column present in the row (e.g. `dq_spec_eval_pass`, `dq_spec_eval_failed_criteria`)
- the full prompt and the full completion, each as its own block, so line breaks and code survive

Then ask the approved annotation questions for this split.

For auto-labeling input, the header gives the record number and its id field value only, followed by each input field under its name, and then the approved question (`references/auto-labeling-input.md` → What annotators see and answer).

## Step 3b: Question presentation

Use the questions the user approved in Step 2. Ask them together for each record so the user can answer in one message. For each question, give its answer type and allowed values: the choices for a choice question (for example correct, incorrect or partial), what a free-text answer should hold (for example a corrected completion, asked only when the answer calls for one), a flag list with "none" allowed, and which questions are optional.

Parse the user's answer into the JSONL row schema below. If the user's response is ambiguous, ask one clarifying follow-up — do not guess.

## Step 3b: Captured row schema

Append one JSON line per record to `<project-dir>/data/hil/local_review_feedback.jsonl`. Step 6 (`references/annotation-summary-guide.md`) reads the same fields from either mode's file (Reading the feedback file).

| Field | Value |
|---|---|
| `record_id` | The record's id, from Step 1's `id_field` (`record_id`, else `id`), or, when no row has an id (Step 1's `id_field` is null), its 1-based row number in the reviewed file (`references/annotation-summary-guide.md` → Joining annotations to source records) |
| `split` | The split file the record came from, e.g. `low_confidence` |
| `status` | `completed` or `skipped` |
| `corrected_completion` | The corrected text, or empty; for auto-labeling input, the answer in its task's shape (Auto-labeling rows, below) |
| `issues` | List of issue tags; `unfixable` marks a row Step 8 removes |
| `meaningful_translation_rating`, `completeness_rating`, `has_security_vulnerability`, `corrected_code` | Only when a question asked for them, else `null` |
| `reviewer_notes` | Free text, or empty |

Only populate fields the approved questions actually asked about. Leave the rest `null`. The Step 6 summary already handles missing/null fields.

### Auto-labeling rows

For auto-labeling's `review.jsonl` and cold-start sample, write `record_id` as the row's id field value (`references/auto-labeling-input.md` → Record ids) exactly as the file has it, and the annotator's answer in `corrected_completion`, in the shape its task takes (`references/auto-labeling-input.md` → What annotators see and answer). Write no `split`: auto-labeling reads it from its own review row.

```json
{
  "record_id": "<id>",
  "status": "completed | skipped",
  "corrected_completion": "<the answer>",
  "reviewer_notes": "<text or empty>",
  "consensus_score": null
}
```

For `ner`, the shape is in `references/auto-labeling-input.md` → What annotators see and answer. `consensus_score` holds the annotator score when the approved questions ask for one; otherwise leave it `null`.

## Step 3b: Pause and resume

The user can pause anytime. Triggers: "stop", "pause", "I'll come back to this later", "save what I have", "let's stop here".

On pause:

1. Flush the in-memory buffer to `local_review_feedback.jsonl` (append mode).
2. Update `manifests/human-in-the-loop.json:human_in_the_loop.local_review_progress` with `last_record_index`, `completed_count`, `skipped_count`.
3. Tell the user where they left off: how many records were saved to `local_review_feedback.jsonl`, how far through the review they are (completed of total), and that saying "continue local review" or "pick up where I left off" resumes it.
4. Ask whether to resume now, finalize what's captured, or end the session.

On resume: run the check in Step 3b: Earlier review in the project directory first. When the user chose to resume there, read `local_review_feedback.jsonl` to get already-reviewed `record_id`s, skip those, and continue from the next unreviewed record.

## Step 3b: Earlier review in the project directory

Local review writes to fixed paths (`data/hil/local_review_feedback.jsonl`, appended to, and `manifests/human-in-the-loop.json`), so a second review in the same project directory would mix with the first. Each project directory holds one review; a new review goes into a new project directory. When the user picks local review at the Step 2 checkpoint, before the mode is saved, and on every resume, run:

```bash
python scripts/review_cycle.py begin --project-dir <project-dir> --data-file <the data file>
```

`<the data file>` is the local path, S3 URI or DataSet ARN the user gave, never `data/hil/review_records.jsonl` (a copy Step 1 may write, the same path for every input). Exit 0 (`state: new`): nothing earlier is in the project directory; `begin` recorded the data file in the manifest, so continue. Exit 2: report the file its error names, and don't start. Exit 3: the project directory already holds review files (`existing`), and `begin` wrote nothing (except with `--adopt`, below). By `state`:

- `resume`: an unfinished local review of the same, unchanged file. When the user asked to continue it ("continue local review"), that request is their choice: resume. Otherwise, ask as below, with resume as one more choice.
- `unrecorded`: review files whose data file was never recorded (a Label Studio review, or a local review started before this check). Ask as below, naming the files in `existing` in place of a data file; when `local_review_feedback.jsonl` is one of them, no Label Studio file (`ls_setup*.json`, `label_studio_export.jsonl`) is, and `finished` is false, offer resume as one more choice, and resume only after the user confirms it is the same file; then run `begin` again with `--adopt`, which records the file so later resumes report `resume`.
- `earlier_cycle`: a review of another file (`earlier_data_file`), a finished one (`finished: true`), one a Label Studio cycle followed (Label Studio files in `existing`), or one of this file before its contents changed or when they couldn't be checked (`changed: true`). Never resume it or add to its answers.

The question: say what the project directory holds (`earlier_data_file` or the `existing` files, `feedback_rows` answers, whether the review was finished (`finished`: Step 8 ran, or the export was handed back to auto-labeling), whether the file changed (`changed`)), that a new review here would mix with it, and ask for a new project directory with a new name. Never start the new review in this folder; its earlier answers and manifest stay as they are.

⏸ Wait for user (only on exit 3, unless the user asked to resume and the state is `resume`).

For the new project directory, use the name the user gives (or create one with the `directory-management` reference), save the review mode there as Step 0b says, record any Step 1 bucket-owner approval there again and, for an S3 or DataSet input, write Step 1's copy of the rows (`data/hil/review_records.jsonl`) there again (`overview.md` Step 1), then run `begin` with that folder; it exits 0.

## Step 3b: Skip semantics

If the user says "skip this one", "next", or "I don't know", write a row with `status: "skipped"` and no annotation fields, then move on. Skipped rows show up in coverage (Step 6a) as `skipped`, as a Label Studio task whose annotations are all cancelled does (`references/annotation-summary-guide.md` → Reading the feedback file).

## Step 3b: Disk write cadence

Write the partial JSONL to disk every 5 records. This keeps the user's progress safe without thrashing the filesystem. The final write happens when the loop exits (completion, pause, or mode switch).

## Step 3b: Mode switch mid-loop

If the user decides records are too long or too numerous and asks to switch to Label Studio:

1. Flush whatever is captured so far to `local_review_feedback.jsonl`.
2. Set `manifests/human-in-the-loop.json:human_in_the_loop.review_mode` to `"external_tool"` and `human_in_the_loop.annotation_tool` to `"labelstudio"` (the only annotation tool).
3. Note in `manifests/human-in-the-loop.json:human_in_the_loop.notes` that there is partial local feedback at `local_review_feedback.jsonl` — this is informational only; the Label Studio export becomes the canonical source.
4. Jump to Step 3a.

When the Label Studio export comes back in Step 5, **ignore the partial local feedback**. Two sources of truth would only confuse the summary.

## Edge cases

- **User answers in a different language than the dataset.** Capture verbatim. Do not translate or normalize — the Step 6 summary works on counts and lengths, not language.
- **User provides a correction longer than the original prompt.** Allowed. No length limit on `corrected_completion`.
- **No record has an id** (Step 1's `id_field` is null). Write each row's 1-based row number in the reviewed file as its `record_id`, so Step 8 joins it by position (`references/annotation-summary-guide.md` → Joining annotations to source records, which also says when that holds). Auto-labeling input is the exception: a missing id stops the review at Step 1 (`references/auto-labeling-input.md` → Record ids).
- **Two records share an id.** The review does not start (`overview.md` Step 1): Step 8 joins answers to rows by id, so it couldn't tell which row an answer belongs to.
- **`evaluated_data.jsonl` has fewer rows than the user's local-review subset request.** Cap the subset at the actual row count and tell the user.
