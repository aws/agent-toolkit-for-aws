# Dataset Deduplication

Identifies exact and near-duplicate records in a registered dataset by running the SageMaker Dataset
Quality Evaluation `exact_dedup` and `fuzzy_dedup` operators in one dataset quality evaluation job. The job is
**identification-only**: every input row comes back annotated with a duplicate decision and nothing
is dropped on the service side. Neither operator calls a foundation model, so the job has no Bedrock cost.

This is a sub-reference of `dataset-quality`. The parent overview's Step 1 routes here when duplicates
are the question. When the user also wants a scorecard, the parent runs the two operators alongside its
other metrics in one job (`../quality-job.md` Step 10.2) and reads their results with Step 7 here and
`references/result-interpretation.md`. The registration, format-validation, and job-submission
procedures this workflow points to are the parent's own.

**When to use this and not `dataset-transformation`'s dedup operation:** the dataset is registered
in the SageMaker AI Registry or is too large to process on the user's machine, or the user wants an auditable
duplicate report before deleting anything. Use dataset-transformation's dedup operation for small
local files inside a transformation spec where rows should simply be removed.

## Principles

1. **One thing at a time.** Each response advances exactly one decision.
2. **Confirm before proceeding.** Wait for the user to agree before moving on.
3. **Don't read files until you need them.** Load a reference only at the step that requires it.
4. **No narration, no repetition.** Share outcomes and ask questions.
5. **Always end with a question** whenever you pause for user input.
6. **No internal labels.** Never expose step numbers, script names, or file names to the user. The
   job's output URIs are the user's and are shown at Step 7; they are not internal labels.
7. **Identification is not removal.** Never tell the user rows were removed; report counts of
   *flagged* rows. This capability writes no copy of the data with the flagged rows dropped; a user
   who asks for one is answered from "When to use this and not `dataset-transformation`'s dedup
   operation" above.
8. **Never offer downstream capabilities while the job is running.** Wait for a terminal state.

## Prerequisites

- A dataset registered in the SageMaker AI Registry (`DatasetArn`). Local files and S3 data are registered by
  the generated code's Cells 3 and 4, after the Step 5 confirmation (Step 1).
- An S3 location for the job output.
- The SDK installed and verified as `../../../sdk-getting-started/references/sagemaker-python-sdk-setup.md` says.
  The job's execution role is settled before the plan (Step 4 item 6).
- AWS Region us-east-1 or us-west-2.

## Quick Reference

| Step | Action |
|------|--------|
| 0 | Check prior context (manifests, upstream dataset-quality findings) |
| 1 | Locate the dataset and make sure it is registered |
| 2 | Pick the text column (or no binding for recognized nested formats) |
| 3 | Choose exact, fuzzy, or both, and the operator parameters |
| 4 | Gather job name and output S3 URI; confirm the session region; settle the execution role and the SDK state |
| 5 | Confirm, then generate the notebook or script from `code_templates/deduplication.py` |
| 6 | Run and monitor the job |
| 7 | Present the duplicate report |
| 8 | Drill into duplicate groups on request |

## Workflow

### Step 0: Check for prior context

Silently scan `<project-dir>/manifests/` and the conversation for upstream outputs: a
dataset-quality run that flagged low `uniqueness`, a synthetic-dataset-generation output ARN, or a
transformation manifest with the current dataset path. Reuse the dataset ARN, text column, and
`OUTPUT_S3_URI` from there instead of asking again. A first run with no manifests is normal; do not
mention it.

### Step 1: Locate the dataset and make sure it is registered

For this step, you need **the dataset to deduplicate**. There are three entry points:

| Entry point | What to do |
|---|---|
| Dataset ARN already known | Confirm it with the user and continue |
| Dataset in S3 | Registered by the generated code (Cell 4) after the plan is confirmed |
| Local file | Uploaded to S3 (Cell 3) and registered (Cell 4) by the generated code after the plan is confirmed |

The dataset quality evaluation job requires a `DatasetArn`. For the S3 and local entry points, follow the BYOD
import procedure in `../dataset-import.md` (the SDK's `DataSet.create`): the template's conditional
Cells 3 and 4 (`code_templates/deduplication.py`) upload the file and register it, and set
`DATASET_ARN` for the submit cell. They are included only on these two entry points and run only
after the Step 5 confirmation; nothing is registered before it. Do not write an alternative import.

If the dataset is already known from the conversation or project files (Step 0's manifests, an
upstream run's ARN), confirm it with the user and move on. If not, discover first, in the registry and
in S3, and offer the candidates you find. Registry: run `aws sagemaker list-hubs`, take the hub whose
`HubDisplayName` begins `AiRegistry-` (the account's SageMaker AI Registry, `../dataset-import.md`
"Where it registers"), then run `aws sagemaker list-hub-contents --hub-name <hub> --hub-content-type DataSet`
and offer the dataset names it returns; no hub means no registered datasets. S3: run `aws s3 ls` on
a bucket the conversation named (or the session's default bucket).
Ask the open question only when nothing is found:

> "Which dataset should I deduplicate? You can give me a dataset ARN, an S3 URI, or a local file
> path."

⏸ Wait for user.

### Step 2: Pick the text column

Both operators bind exactly one text operand. The binding depends on the dataset shape:

- **Columnar formats** (HF_Prompt_Completion, HF_Preference, SageMaker_Eval, Verl, or an
  unrecognized flat schema): read the keys of the first record and ask which column defines a
  duplicate. (`Nova_RLVR`: `messages` / `reference_answer` are nested and not bindable — bind an additional flat column if the records carry one, else flatten first.) Suggest `prompt` for instruction data, `text` for pretraining data, and the input
  field for classification data. Bind that single column with an explicit View. When `prompt` holds
  a list of messages (a Verl or HF_Preference file in message form), it is nested: do not bind it;
  bind a flat column or flatten first. Never offer a
  column whose values are all numbers: `exact_dedup` on it fails the whole job before any metric
  runs (`../format-check.md`, "When the output has a `service_note`").
- **Recognized nested formats** (Bedrock_Converse, OpenAI_Messages, Nova_PPO, Nova_CPT): do not
  bind a column. The service derives the prompt and completion from `messages` and runs the operators
  on them, one run each. Row columns then carry the `dq_input__prompt` and
  `dq_input__completion` suffixes described in `../output-schema.md`.
  If the user wants a single-field definition of duplicate, offer dataset-transformation to
  flatten the data first.
- **Unrecognized nested formats** have no validated workflow here: route to dataset-transformation to
  flatten the data first, then return to Step 1 with the flattened file.

If the format is not already known from context, determine it with the parent's format check
(`../format-check.md`) rather than guessing from field names.

The first record gives you its keys and what that one record holds, nothing about the other rows.
Do not describe every row from it ("each `prompt` holds the question after a fixed lead-in"); the
rule for such a claim is in Step 5.

> "Which field should define a duplicate? Two rows count as duplicates when this field matches
> (exactly, or nearly for fuzzy matching)."

⏸ Wait for user.

### Step 3: Choose the operators and parameters

Read `references/operators.md` for the semantics before advising. Then ask the user how strict the
match should be, naming the three choices as values: exact (byte-identical values of the field,
optionally after trimming whitespace and lowercasing), near-duplicate (MinHash similarity on word
5-grams, so minor rephrasing still matches), or both (one job, two independent reports). Recommend
both and ask the user to confirm it or to choose exact or near-duplicate instead.

Defaults, which you should state and only change if the user asks: `Normalize` false for exact;
`JaccardThreshold` 0.7 and `Lowercase` true for fuzzy. A higher threshold flags fewer, closer
matches; a lower one clusters more aggressively.

⏸ Wait for user.

### Step 4: Gather remaining parameters

Collect any missing values one at a time, confirming rather than re-asking anything already known:

1. **Job name** — alphanumeric and hyphens, starting with a letter or digit; the SDK appends a timestamp (shortening a long name to fit), and the code stops before submitting on any other character. Suggest one from context.
2. **Output S3 URI** — when chaining from an upstream synthetic-dataset-generation,
   dataset-quality, or dataset-transformation run, reuse the same `OUTPUT_S3_URI` so all
   artifacts share one prefix and one IAM policy.
3. **Region** — the job runs in the session's region, which must be us-east-1 or us-west-2; the
   generated code checks this and stops otherwise. There is no region placeholder: to run in the
   other supported region the user switches the session region (profile or `AWS_DEFAULT_REGION`)
   before running.
4. **VPC** — not a question. Running the job in the user's own VPC is not offered.
5. **MLflow** — not a question. Logging the job to SageMaker managed MLflow is not offered.
6. **Execution role** — settled before the plan, never left open. With none given, the SDK takes the
   session identity as the job's role (or the SageMaker config `RoleArn` default, when set), so read
   that role (`aws sts get-caller-identity`; in an assumed-role session it is the segment after
   `assumed-role/`) and check it the way `../../../sdk-getting-started/references/execution-role-setup.md`
   "Validate" does: `aws iam get-role`, and the trust policy must name `sagemaker.amazonaws.com`.
   - It does: the identity is itself a SageMaker execution role. Leave `[ROLE_ARN]` unset; the plan
     names it, "the session's execution role, [role name]".
   - It does not (an Admin role, a federated or assumed-role session, any other role): the job would
     fail about a minute after submit ("Unable to register credentials"). List the roles whose trust
     policy names `sagemaker.amazonaws.com` (`aws iam list-roles` returns each with its
     `AssumeRolePolicyDocument`); one qualifies, its ARN goes in the plan; several, the user picks and
     never you; none, ask for an ARN as that page's "Resolve" does. A named role is checked the same way.
7. **SDK state** — not a question. Before the plan, check whether the SDK is installed as
   `../../../sdk-getting-started/references/sagemaker-python-sdk-setup.md` says, with the Python the
   SDK was installed into (on a venv setup, `./.venv/bin/python`): installed means nothing to
   install; otherwise setup installs. The check installs nothing;
   the install itself waits for the Step 5 answer. The plan's Setup line states the result, so the plan
   the user approves is complete and nothing is discovered after "Go".

⏸ Wait for each answer.

### Step 5: Confirm and generate code

This step gates the spend. Nothing is installed, registered, created or submitted before the user
answers the question below: no SDK install, no hub import, no script or notebook, no job. A request
that asked for everything up front ("run it and wait", "just do it") chose the delivery mode only; it
did not answer this question. An unattended or autonomous run is not an exception: when nobody can
answer, leave the plan and the question in chat and stop here without launching.

The confirmation is one message in a fixed order, and no reply format moves a part of it ahead of
another. First the cost line: this job calls no foundation model, so the Bedrock notice of
`../quality-job-submit.md` "Confirm the plan" does not apply; say instead that the job runs on
SageMaker compute billed to the account and writes to the output prefix. When the Dataset line is
the "to be registered" form, add: the run uploads the file to S3 (local files), registers a Dataset
entity in the SageMaker AI Registry under the name above (a name already registered there gets a new
major version) and creates the registry's hub when the account has none; both can be removed
afterwards (`aws sagemaker delete-hub-content`, then `aws sagemaker delete-hub`). Then the plan: the exact
request the generated code will send, every value as the template will carry it. Then the one
question, as the last line of the message, after the plan is on screen and never above it or in a
list of questions before it. Then the wait:

The plan, and anything you say around it, describes the rows only as far as you counted them. A
claim about every row (what each `prompt` holds, what lead-in the rows share, why a check will or
will not match) is made only from a count run over all the rows, and it states the count ("all 40
prompts open with one of five lead-ins"; "31 of 40 open with the same sentence"). From one record
you may say what that record holds; without the count, name the field and stop. The same rule
applies to the report in Step 7.

> "Here's the deduplication setup:
>
> - Dataset: [ARN; for the user's own data, not yet registered: "to be registered as [hub content name] in the account's SageMaker AI Registry"]
> - Field: [column, or 'normalized prompt and completion']
> - Match: [exact / near-duplicate / both] with [parameters]
> - Output: [S3 URI], region [session region]
> - Job name: [name from Step 4]; execution role: [the ARN settled in Step 4, or "the session's execution role, [role name]"]
> - Setup: [from Step 4: "installs the SDK into your Python environment", or "the SDK is installed, nothing to install"]
> - Delivery: [the user's or the caller's own words when they said: notebook you run yourself / script I run; otherwise "a notebook you run yourself (say so here if you would rather I run it as a script)"]
>
> Nothing has been installed, registered or submitted yet. Anything to change before I run it?"

⏸ Wait for user. Do not install, register, generate or submit without this answer. A change to any
line after this point restates the changed lines and asks again.

**Delivery mode.** The plan's Delivery line settles it: the user's or the caller's stated preference,
otherwise the notebook default, which the user changes in the confirmation answer ("run it", "just
run it", "execute it" choose the script). Do not ask a separate delivery question after the
confirmation. Script mode combines the cells into `<project-dir>/scripts/deduplication.py`
and offers the same three run options the parent offers (`../quality-job-submit.md` Delivery Mode:
leave it, run and wait, start and check later).

**Generation rules.**

- Use `code_templates/deduplication.py` exactly. Include every cell; Cells 3 and 4 are only included
  on the S3 and local-file entry points of Step 1 (Cell 3, the upload, for a local file only).
- Cell 0 [markdown] is used as written: in a notebook it is the first markdown cell, and in a script
  its lines are the file's opening comment, the sentence that the job flags rows and drops nothing
  included.
- Copy `scripts/dedup_decisions.py` into `<project-dir>/scripts/` before generating. Cell 6
  imports it from there. Never regenerate or inline its logic.
- Substitute every placeholder from this table, then renumber cells sequentially.

| Placeholder | Value |
|---|---|
| `[DATASET_ARN]` | Hub content ARN from Step 1; on the S3 and local-file entry points no ARN exists yet, so it is left empty (`DATASET_ARN = ""`) and Cell 4's import sets it |
| `[INPUT_BUCKET]` | the S3 bucket a local file is uploaded to (local-file entry only) |
| `[LOCAL_DATASET_PATH]` | the local file path, written as given, without quotes; the template's line adds them; it sits in a Python string, so a single quote or a space stays as it is and a `\` or `"` is written as `\\` or `\"` (local-file entry only) |
| `[DATASET_FILENAME]` | the file's name in S3, written inside a Python string the same way (local-file entry only) |
| `[HUB_CONTENT_NAME]` | the dataset's Hub content name: alphanumeric and hyphens (S3 and local-file entries) |
| `[DATASET_S3_URI]` | the full S3 URI of the one data file the dataset is registered from (S3 and local-file entries): the user's file from Step 1, or `s3://<input bucket>/byod/<hub content name>/<filename>` on the local-file entry (Cell 3's upload path); a file, never a folder |
| `[DATASET_FORMAT]` | the format name the parent's format check returned (Step 2, `../format-check.md`; S3 and local-file entries); the SDK records it as passed |
| `[TEXT_COLUMN]` | Column from Step 2 in quotes (e.g. `"prompt"`), or `None` unquoted for recognized nested formats; the slot itself is unquoted so both substitute correctly |
| `[DEDUP_MODE]` | `exact`, `fuzzy`, or `both` |
| `[NORMALIZE]` | `True` or `False` (exact_dedup) |
| `[JACCARD_THRESHOLD]` | Number in (0, 1], default `0.7` (fuzzy_dedup) |
| `[LOWERCASE]` | `True` or `False` (fuzzy_dedup) |
| `[OUTPUT_S3_URI]` | Output S3 URI from Step 4 |
| `[JOB_BASE_NAME]` | Job name from Step 4 (alphanumeric and hyphens) |
| `[ROLE_ARN]` | `None` unquoted only when Step 4 found the session identity is itself a SageMaker execution role, otherwise the ARN Step 4 settled in quotes; the slot itself is unquoted so both substitute correctly |
| `[PROJECT_SCRIPTS_DIR]` | Path to `<project-dir>/scripts/` where the helper script was copied |
| `[LOCAL_WORK_DIR]` | Local directory for the job's `metadata.json` and aggregate report, e.g. `<project-dir>/manifests/dedup`; the row-level file (the user's data, which can be gigabytes) is never saved there: the helper streams it from S3 line by line, only when the user asks for the groups |
| `[WAIT]` | `True` unquoted (notebook, and the script's run-and-wait option), or `False` unquoted for the script's start-but-don't-wait option; it is the only line the run option changes |

Notebook mode: append to an existing project notebook when one exists, otherwise create
`<project-dir>/notebooks/<project-name>_deduplication.ipynb`. Use the directory-management capability if
no project directory exists yet.

### Step 6: Run and monitor

Run time depends on the row count: job start-up takes a few minutes even for a handful of rows
(`../quality-job-submit.md` Step 12b), and the fuzzy pass adds time in proportion to the row count. Do not promise a duration; the status panel shows progress.
The generated code submits the job and prints its name and ARN as one JSON line. With `WAIT` true it
then waits on the job (`job.wait()`) and stops if the job ended in any state but Completed; with `WAIT`
false it ends there, and the user comes back for the results (`DataPreparer.attach` takes the ARN, the
status check takes the name). The summary cell reads the job's outputs from the S3 URIs its `metadata.json` lists
(DescribeJob's `JobConfigDocument.MetadataS3Uri`, printed when the job completes); the DataSet handle
the SDK returns describes the input dataset, not the output. For status questions while it runs,
follow `../progress-check.md` to re-attach to the job and see which results are written. Its record-display step assumes judge-score columns and a `messages` array; for this job
show, for the last rows, the bound text column (or `dq_input__prompt` / `dq_input__completion` for
recognized nested formats) with `dq_<operator>_flagged__<column>` and `dq_<operator>_reason__<column>`,
where `<column>` is that same suffix. Do not suggest next steps until the job is terminal.

### Step 7: Present the duplicate report

Before you write or explain any result, read `references/result-interpretation.md`: it gives the
duplicate-rate table with the wording each band is reported in, the near-duplicate caveats to state
once, and the offer to rerun at a different threshold. Then present the aggregate results per operator:

> **Duplicate Report** *(identification only — nothing has been removed)*
>
> **Exact duplicates on [field]:** [duplicate_count] of [input_count] rows
> ([duplicate_rate as %]) in [duplicate_groups] groups; [distinct_count] rows would remain.
> **Near-duplicates on [field] (Jaccard target [threshold]):** [duplicate_count] of [input_count]
> rows ([rate]) in [duplicate_groups] clusters; [distinct_count] would remain.
>
> **Notable findings:** [flags from result-interpretation.md]
>
> **Output files:** [the `metadata.json` URI], and the `aggregate/quality_report.json` and
> `record_level/evaluated_data.jsonl` URIs it lists

For recognized nested formats each operator reports twice, once per normalized column; present both
and name the column each time. In the notable findings, a claim about the whole dataset (what every
row shares, why a check found nothing) is made only from a count you ran over the rows and states
that count, as in Step 5; without the count it is not made, and the explanation stays with the rows
you saw. A claim about a flagged pair
or group (what its rows share, where they differ, why the exact check missed it) is made only from a
comparison of the full field values of those rows, quoting or counting the differing parts, as
`references/result-interpretation.md` "Explaining a flagged pair" gives it; the first few hundred
characters of each row, the `reason` label, or the group's shape is not that comparison.

Then the next step. In the same message, name the routes as available and not as questions:
drilling into the groups (Step 8), a full quality scorecard on the result (the parent's quality
evaluation), or fine-tuning if nothing is notable. The rerun at a different threshold belongs in the
notable findings as prose (the offer `references/result-interpretation.md` gives). When no row was
flagged, the question is whether to continue to fine-tuning.

Name the routes once. A later turn about the same result (the report asked for again, a group shown
in Step 8, a question about a row) ends with its answer, not with the list of routes again. Name them
again only when the user asks what to do next, or the result changes (a rerun at another threshold).

### Step 8: Drill into duplicate groups

When the user asks to see duplicates, check the size first, as `../drill-down.md` and the taxonomy
page do before their row-level read: run `aws s3api head-object --bucket <bucket> --key <key>` on the
`Reports.RecordLevel` object named in `metadata.json` and read `ContentLength`. Then say one of these
two sentences, with the size filled in:

- Under 50 MB: "Your row-level file is {size} MB; since it's under 50 MB, I'd recommend streaming it
  from S3 to list the duplicate groups. Would you like to proceed?"
- 50 MB or over: "Your row-level file is {size} MB; since it's over 50 MB, I'd recommend not streaming
  the whole file. The aggregate report has the duplicate counts per operator; I can give those, or list
  groups from a sample of the file."

Do not run the listing until the user agrees. At 50 MB or over, give the aggregate report's counts (the
summary the script prints from the aggregate, as Step 7 showed them) and do not run `--groups` on the
whole file; the script itself refuses to stream a row-level file of that size. Once the user agrees
under 50 MB, use the helper script's group listing (`--groups N` with
`--metadata <the job's MetadataS3Uri>` or `--record-level <the evaluated_data.jsonl URI>`), which
streams the scored rows from S3 and joins each flagged row to its representative via the `row_id` and
`representative_row_id` columns; the summary cell did not read the rows, so this is their first read. For nested
formats list per normalized column (the helper's `suffix` argument or `--bound` flag). Show at most
20 groups, largest first, with the representative text and the member texts, at most 20 members per
group (the script's `--members N`, default 20) followed by one "and K more" line when the group is
larger, so a group of a hundred thousand duplicates never fills the conversation; a text the job's
`pii_detection` flagged on a row prints as `[REDACTED: PII]`, as the parent's drill-down script
prints it, and a `dq_input__` column (`dq_input__prompt`, `dq_input__completion`: text the service derived from a source column such as `messages`) prints as `[REDACTED: PII]` when any column of that row is flagged, and you do not look the value up another way. Never load the whole
scored file into the conversation. End with what the groups show; the routes of Step 7 were named
with the report and are not named again here.

## Resources

- `code_templates/deduplication.py` — cell templates for the upload and the import (conditional), the job, and the summary
- `scripts/dedup_decisions.py` — saves the job's `metadata.json` and aggregate report, summarizes the
  decisions, and, on request, lists duplicate groups by streaming the row-level file from S3 (never
  downloaded)
- `references/operators.md` — `exact_dedup` and `fuzzy_dedup` configuration, semantics, and output
  contract
- `references/result-interpretation.md` — thresholds, flags, and the drill-down procedure
- `../dataset-import.md` — the BYOD import procedure
- `../dataset-service-api.md` — job submission and verifying the import
- `../progress-check.md` — mid-job status protocol
