# Dataset Taxonomy

Discovers what is in a dataset by running the SageMaker Dataset Quality Evaluation `taxonomy` operator: for each
requested **framing** (`task`, `domain`, `quality`) it embeds every row, clusters the corpus,
labels a three-level category tree with a foundation model, and assigns every row to a leaf with a
confidence margin. The result is a per-framing tree with row counts, per-row category columns, and
a combined HTML report. Nothing is dropped and no row is rewritten.

This is a sub-reference of `dataset-quality`. The parent overview's Step 1 routes here when the
user asks what their data covers. When the user also wants a scorecard and the session is in
us-east-1, the parent adds the operator to its quality evaluation (`quality-job.md` Step 10.2) after
the cost confirmation this workflow requires, and reads the result with this workflow's presentation
steps and `references/result-interpretation.md`. The registration, format-validation, and job-submission
procedures this workflow points to are the parent's own.

Use it when the user wants to know what tasks, subject areas, or quality tiers their data covers,
whether coverage matches the use case, where the gaps and imbalances are, or how to slice the data
by category before filtering or generating more. It is not a labeling tool for a user-defined label
set (that is auto-labeling) and not a failure taxonomy for eval predictions (that is error-analysis).

## Principles

1. **One thing at a time.** Each response advances exactly one decision.
2. **Confirm before spending.** This job calls Bedrock for every row and framing. State the cost
   drivers and get approval before submitting.
3. **Don't read files until you need them.** Load a reference only at the step that requires it.
4. **No narration, no repetition.** Share outcomes and ask questions.
5. **Always end with a question** whenever you pause for user input.
6. **No internal labels.** Never expose step numbers, script names, or file names to the user. The
   job's output URIs are the user's and are shown at Step 7; they are not internal labels.
7. **The tree is discovered, not prescribed.** Category names come from the model and differ
   between runs; present them as observations about this dataset, not as a fixed schema.
8. **Never offer downstream capabilities while the job is running.** Wait for a terminal state.

## Prerequisites

- **Region us-east-1.** The operator embeds rows with a Nova embedding model that is served only
  in us-east-1. A job submitted in any other region fails. Check the session region first.
- A dataset registered in the SageMaker AI Registry (`DatasetArn`; an S3 or local file is registered by the
  generated code's Cells 3 and 4 after the Step 5 confirmation, Step 1) with at least 10 rows — in practice tell the user taxonomy is built for larger corpora (a job on a few dozen rows can fail at finalization; the row keyed on `l3_category has N null` in `../troubleshooting.md` says what to do); every value of the
  bound text field must be at most 49,000 characters.
- An S3 location for the job output.
- The SDK installed and verified as `../../../sdk-getting-started/references/sagemaker-python-sdk-setup.md`
  says. The job's execution role is settled before the plan (Step 4 item 5).

## Quick Reference

| Step | Action |
|------|--------|
| 0 | Check region and prior context |
| 1 | Locate the dataset and make sure it is registered |
| 2 | Pick the text column (or no binding for recognized nested formats) |
| 3 | Choose framings and confirm the cost drivers |
| 4 | Gather job name and output S3 URI; settle the execution role and the SDK state |
| 5 | Confirm, then generate the notebook or script from `code_templates/taxonomy.py` |
| 6 | Run and monitor the job |
| 7 | Present the taxonomy |
| 8 | Drill into categories and low-confidence rows on request |

## Workflow

### Step 0: Check region and prior context

Confirm the working region is us-east-1. If it is not, say so before anything else and offer to
switch the session region or to register the dataset there; do not proceed in another region.

Silently scan `<project-dir>/manifests/`, `use_case_spec.md`, and the conversation for a dataset
ARN, the text column, an `OUTPUT_S3_URI`, and the stated use case. The use case matters here: the
taxonomy is most useful when compared against what the user says the data should cover.

### Step 1: Locate the dataset and make sure it is registered

For this step, you need **the dataset to analyze**. Three entry points:

| Entry point | What to do |
|---|---|
| Dataset ARN already known | Confirm it with the user and continue |
| Dataset in S3 | Registered by the generated code (Cell 4) after the plan is confirmed |
| Local file | Uploaded to S3 (Cell 3) and registered (Cell 4) by the generated code after the plan is confirmed |

For the S3 and local entry points, follow the BYOD import procedure in `../dataset-import.md` (the
SDK's `DataSet.create`): the template's conditional Cells 3 and 4 (`code_templates/taxonomy.py`)
upload the file and register it, and set `DATASET_ARN` for the submit cell. They are included only on
these two entry points and run only after the Step 5 confirmation; nothing is registered before it.
Do not write an alternative import.

If the dataset is already known from the conversation or project files (Step 0's scan), confirm it
with the user and move on. If not, discover first, in the registry and in S3, and offer the candidates
you find. Registry: run `aws sagemaker list-hubs`, take the hub whose `HubDisplayName` begins
`AiRegistry-` (the account's SageMaker AI Registry, `../dataset-import.md` "Where it registers"), then
run `aws sagemaker list-hub-contents --hub-name <hub> --hub-content-type DataSet` and offer the dataset
names it returns; no hub means no registered datasets. S3: run `aws s3 ls` on a bucket the conversation named
(or the session's default bucket). To count the rows of an S3 object,
read its size with `aws s3api head-object` first and never copy it locally: under 50 MB stream it to
`wc -l`, and at 50 MB or over give an estimate from its first 1 MB, named as one
(`../training-volume-requirements.md` "How to count"). Ask the open question only when
nothing is found:

> "Which dataset should I map out? A dataset ARN, an S3 URI, or a local file path works."

⏸ Wait for user.

### Step 2: Pick the text column

The operator binds exactly one text operand, the same way the deduplication and text metrics do:

- **Columnar formats**: read the keys of the first record and ask which field carries the content
  to categorize. For instruction data suggest `prompt` (what the row asks); for pretraining data
  `text`. Bind that single column with an explicit View. When `prompt` holds a list of messages
  (a Verl or HF_Preference file in message form), it is nested: do not bind it; bind a flat column
  or flatten first.
- **Recognized nested formats** (Bedrock_Converse, OpenAI_Messages, Nova_PPO, Nova_CPT): do not
  bind a column. The service derives the prompt and completion from `messages` and runs the operator
  on each, which doubles the Bedrock spend. Say so, and offer
  dataset-transformation to flatten to a single field when the user only cares about one side.
- **Unrecognized nested formats** have no validated workflow here: route to dataset-transformation to
  flatten the data first, then return to Step 1 with the flattened file.

⏸ Wait for user.

### Step 3: Choose framings and confirm the cost drivers

Read `references/operator.md` for what each framing produces. Then ask the user which views of the
data they want, naming the three framings as the choices: task (what each row asks the model to do),
domain (the subject area of each row), and quality (the quality-related traits of each row). Say
what each answers: task answers whether the rows are balanced across what they ask; domain answers
what topics they cover; quality answers how the rows differ in traits such as clarity. Say that each
framing is a separate pass over the whole dataset and that one framing is usually enough to start.

The framings question is its own question, in its own message, with its own wait. It is asked and
answered before the plan of Step 5 is drawn, and the plan's Framings line carries the user's answer,
never a framing you chose for them. A request that names what the user wants to know ("what
topics", "balanced across tasks") tells you which framing answers it: say so, and still ask. Offer
the three choices as task only, task and domain, or all three including quality:

> "Which views should the job build: task only, task and domain, or all three including quality?
> Task says what each row asks the model to do, so whether the set is balanced across tasks. Domain
> adds the subject area of each row, so what topics it covers. Quality adds the quality-related
> traits of each row. Each view is a separate pass over the whole dataset; one is usually enough to
> start."

State the cost drivers plainly: one embedding call per row per framing, plus a bounded number of
labeling calls per framing, billed through Bedrock in the account running the job. N is the record
count, counted as `../training-volume-requirements.md` "How to count" says (an S3 object of 50 MB or
over gives an estimate, and the plan says so). For N rows and F framings expect about N × F
embedding calls: 10,000 rows with `task` and `domain` is about 20,000 embedding calls plus the
labeling calls. A recognized nested format runs the operator on the
normalized prompt and again on the completion, so count every row twice: N × F × 2, about 40,000
embedding calls for the same example. For a large dataset, offer to register a sample of a few
thousand rows and run on that first.

⏸ Wait for user.

### Step 4: Gather remaining parameters

Collect any missing values one at a time, confirming rather than re-asking anything already known:

1. **Job name** — alphanumeric and hyphens, starting with a letter or digit; the SDK appends a timestamp (shortening a long name to fit), and the code stops before submitting on any other character.
2. **Output S3 URI** — reuse the upstream `OUTPUT_S3_URI` when chaining from another run.
3. **VPC** — not a question. Running the job in the user's own VPC is not offered.
4. **MLflow** — not a question. Logging the job to SageMaker managed MLflow is not offered.
5. **Execution role** — settled before the plan, never left open. With none given, the SDK takes the
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
6. **SDK state** — not a question. Before the plan, check whether the SDK is installed as
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

The order of the gate is fixed, and no reply format moves a part of it ahead of another. First the
framings question of Step 3, asked on its own and answered by the user before anything below is
written; the Framings line of the plan carries that answer, never a framing you chose. Then the
confirmation, which is one message: first the Bedrock notice, its first line and its taxonomy line,
as `../quality-job-submit.md` "Confirm the plan" gives them (do not reword them); then the plan, the
exact request the generated code will send, every value as the template will carry it; then the
confirmation question, the only question in this message, as its last line, after the plan is on
screen and never above it or in a list of questions before it. When the Dataset line is the "to be
registered" form, add before the question: the run uploads the file to S3 (local files), registers a
Dataset entity in the SageMaker AI Registry under the name above (a name already registered there
gets a new major version) and creates the registry's hub when the account has none; both can be
removed afterwards (`aws sagemaker delete-hub-content`, then `aws sagemaker delete-hub`). The plan
names no other hub: a hub where an earlier entry of the same data was found is not where this
registration goes (`../dataset-import.md`, "Where it registers"). "One
question per message" means
each question gets its own message and its own wait; it never means folding the framings choice
into the plan so that the confirmation is the only question asked. Then the wait:

> "Here's the taxonomy setup:
>
> - Dataset: [ARN; for the user's own data, not yet registered: "to be registered as [hub content name] in the account's SageMaker AI Registry"] ([N] rows)
> - Field: [column, or 'normalized prompt and completion']
> - Framings: [list]
> - Region: us-east-1, output: [S3 URI]
> - Job name: [name from Step 4]; execution role: [the ARN settled in Step 4, or "the session's execution role, [role name]"]
> - Setup: [from Step 4: "installs the SDK into your Python environment", or "the SDK is installed, nothing to install"]
> - Cost: about [N × framings; twice that for a recognized nested format] embedding calls plus labeling calls, billed through Bedrock
> - Delivery: [the user's or the caller's own words when they said: notebook you run yourself / script I run; otherwise "a notebook you run yourself (say so here if you would rather I run it as a script)"]
>
> Nothing has been installed, registered or submitted yet. Anything to change before I run it?"

⏸ Wait for user. Do not install, register, generate or submit without this answer. A change to any
line after this point restates the changed lines and asks again.

**Delivery mode.** The plan's Delivery line settles it: the user's or the caller's stated preference,
otherwise the notebook default, which the user changes in the confirmation answer ("run it", "just
run it", "execute it" choose the script). Do not ask a separate delivery question after the
confirmation. Script mode combines the cells into `<project-dir>/scripts/taxonomy.py`
and offers the same three run options the parent offers (`quality-job-submit.md` Delivery Mode).

**Generation rules.**

- Use `code_templates/taxonomy.py` exactly. Include every cell; Cells 3 and 4 are only included on
  the S3 and local-file entry points of Step 1 (Cell 3, the upload, for a local file only). Copy
  `scripts/taxonomy_summary.py` into
  `<project-dir>/scripts/` before generating; Cell 6 imports it from there. Cell 6 reads the aggregate
  report only, the per-framing counts and the HTML report paths; the report this capability writes
  carries the aggregate's counts and the HTML report path, and the trees are built on request. The
  row-level file (the user's data, which can be gigabytes) is read only when the user asks for the
  trees or for rows, by the helper script in Step 8, streamed from S3 line by line and never
  downloaded; the rows never enter the conversation.
- Add the Bedrock notice from Cell 0 [markdown] as the first markdown cell.
- Substitute every placeholder from this table, then renumber cells sequentially.

| Placeholder | Value |
|---|---|
| `[DATASET_ARN]` | Hub content ARN from Step 1; on the S3 and local-file entry points no ARN exists yet, so it is left empty (`DATASET_ARN = ""`) and Cell 4's import sets it |
| `[INPUT_BUCKET]` | the S3 bucket a local file is uploaded to (local-file entry only) |
| `[LOCAL_DATASET_PATH]` | the local file path, written as given, without quotes; the template's line adds them; it sits in a Python string, so a single quote or a space stays as it is and a `\` or `"` is written as `\\` or `\"` (local-file entry only) |
| `[DATASET_FILENAME]` | the file's name in S3, written inside a Python string the same way (local-file entry only) |
| `[HUB_CONTENT_NAME]` | the dataset's Hub content name: alphanumeric and hyphens (S3 and local-file entries) |
| `[DATASET_S3_URI]` | the full S3 URI of the one data file the dataset is registered from (S3 and local-file entries): the user's file from Step 1, or `s3://<input bucket>/byod/<hub content name>/<filename>` on the local-file entry (Cell 3's upload path); a file, never a folder |
| `[DATASET_FORMAT]` | the format name the parent's format check returned (`../format-check.md`; S3 and local-file entries); the SDK records it as passed |
| `[TEXT_COLUMN]` | Column from Step 2 in quotes (e.g. `"prompt"`), or `None` unquoted for recognized nested formats; the slot itself is unquoted so both substitute correctly |
| `[FRAMINGS]` | Python list literal, e.g. `["task"]` or `["task", "domain"]` |
| `[OUTPUT_S3_URI]` | Output S3 URI from Step 4 |
| `[JOB_BASE_NAME]` | Job name from Step 4 (alphanumeric and hyphens) |
| `[ROLE_ARN]` | `None` unquoted only when Step 4 found the session identity is itself a SageMaker execution role, otherwise the ARN Step 4 settled in quotes; the slot itself is unquoted so both substitute correctly |
| `[PROJECT_SCRIPTS_DIR]` | Path to `<project-dir>/scripts/` where the helper script was copied |
| `[WAIT]` | `True` unquoted (notebook, and the script's run-and-wait option), or `False` unquoted for the script's start-but-don't-wait option; it is the only line the run option changes |

Notebook mode: append to an existing project notebook when one exists, otherwise create
`<project-dir>/notebooks/<project-name>_taxonomy.ipynb`. Use the directory-management capability if no
project directory exists yet.

### Step 6: Run and monitor

Expect at least several minutes even for a small input (job start-up, `../quality-job-submit.md` Step 12b),
and the run then grows with the Step 3 cost drivers (rows × framings), so large corpora take
proportionally longer. The generated code submits the job and prints its name and ARN as one JSON line.
With `WAIT` true it then waits on the job (`job.wait()`) and stops if the job ended in any state but
Completed; with `WAIT` false it ends there, and the user comes back for the results (`DataPreparer.attach`
takes the ARN, the status check takes the name). The summary cell reads the job's outputs from the S3 URIs its
`metadata.json` lists (DescribeJob's `JobConfigDocument.MetadataS3Uri`, printed when the job
completes); the DataSet handle the SDK returns describes the input dataset, not the output. For status
questions while it runs, follow `../progress-check.md` to re-attach to the job and see which results
are written. Its record-display step assumes judge-score columns and a `messages` array; for this
job show, for the last rows, the bound text column (or `dq_input__prompt` / `dq_input__completion` for
recognized nested formats) with `dq_taxonomy_<framing>_{l1,l2,l3,margin}__<column>`, where `<column>` is
that same suffix. An unknown framing is rejected at submit. Fewer than 10 rows, or a text over 49,000 characters,
fails the job before any model call (the specific message is in the job log); fix the input and
resubmit. A wrong region is caught before submission only by the
generated code's own region check, so keep that cell: a job that reaches the service outside
us-east-1 fails later, when the embedding call cannot find the model.

### Step 7: Present the taxonomy

Read `references/result-interpretation.md`, then present per framing:

> **Dataset Taxonomy — [framing]** *([classified] of [input] rows classified, [low_confidence]
> low-confidence)*
>
> [on request]: the tree lines below are filled only when the user asks for the trees:
> [L1 category] — [count] rows ([%])
> ├─ [L2] — [count]
> │  ├─ [L3] — [count]
> ...
>
> **Notable findings:** [flags from result-interpretation.md]
>
> **Report:** [taxonomy_report_path] (HTML; one per bound column, so nested formats have a prompt
> report and a completion report — name the column with each)
> **Output files:** [the `metadata.json` URI], and the `aggregate/quality_report.json` and
> `record_level/evaluated_data.jsonl` URIs it lists

The counts and the report path come from the aggregate (`quality_report.json` → `taxonomy`); that is
also what the written quality report carries. The aggregate has no category names. Of the notable
findings, only the Confidence flags (the low-confidence share) and the Integrity flags come from the
aggregate's counts; the Coverage and Balance findings of `references/result-interpretation.md` need the
category names and their row counts, which are in the trees alone. Without the trees, state the
confidence and integrity flags only, say that the coverage and balance checks need the trees, and never
name a category or its share from memory or from the use case.
A request that asked what the dataset covers (its topics, tasks or categories) is the ask for the trees:
check the size as Step 8 does; under 50 MB, run the helper without another question and give the L1
and L2 names with their row counts in the reply that reports the job's end; at 50 MB or over, ask
Step 8's second sentence. The tree lines are filled only when the
user asks for the trees: the helper script builds them on request (Step 8) by streaming the row-level
object from S3 line by line, never downloading it; the rows never enter the conversation. Then show them largest branches first, trimmed to what fits; the full tree is in the HTML
report. For recognized nested formats there is one tree per normalized column per framing; present both
and name the column each time. Then offer all six, in the reply that gives the result, never one alone: see rows in a category, see low-confidence rows,
compare coverage against the use case, filter or split by category (dataset-transformation),
generate more data for thin categories (synthetic-dataset-generation), or run a quality scorecard
on a category (the parent overview's quality evaluation).

### Step 8: Drill into categories and low-confidence rows

When the user asks to see the category trees, the rows in a category, or the low-confidence rows,
check the size first, as `../report-visualization.md` does before its row-level read: run
`aws s3api head-object --bucket <bucket> --key <key>` on the `Reports.RecordLevel` object named in
`metadata.json` and read `ContentLength`. Then say one of these two sentences, with the size filled in:

- Under 50 MB: "Your row-level file is {size} MB; since it's under 50 MB, I'd recommend a streamed
  read for the trees and the rows: the file stays on S3 and only the rows needed are read. Would you
  like to proceed with the streamed read?"
- 50 MB or over: "Your row-level file is {size} MB; since it's over 50 MB, I'd recommend staying
  with the per-framing counts and the HTML report, which has the full tree, instead of streaming the
  whole file. Would you like that, or would you prefer the streamed read anyway?"

Do not run the helper until the user approves. A request for the topics is that approval under
50 MB (Step 7). Under 50 MB, or when the user chooses the streamed
read, copy `scripts/taxonomy_summary.py` into the project's `scripts/` directory (Step 5 may have done so
already) and run it: `python scripts/taxonomy_summary.py --metadata <the job's MetadataS3Uri> [--column <bound column>]`,
or `--aggregate <quality_report.json URI> --record-level <evaluated_data.jsonl URI>` when those two
URIs are known. The script streams the objects from S3 line by line and never downloads them (the
user's data, which can be gigabytes); it prints the trees and the listings, and the rows never enter
the conversation. Present its output per `references/result-interpretation.md`. It is run only when
the user asks for the trees or for rows, never for the report, which carries the aggregate's taxonomy
counts and the HTML report path.

Use the helper script's row listings, which read the `dq_taxonomy_<framing>_l1/l2/l3/margin`
columns; for nested formats name the normalized column (the helper's `suffix` argument or `--bound`
flag). Show at most 20 rows per request, and for low-confidence rows sort by margin ascending. Never
load the whole scored file into the conversation.

## Resources

- `code_templates/taxonomy.py` — cell templates for the upload and the import (conditional), the job and the summary
- `scripts/taxonomy_summary.py`: on request only, it streams the job outputs from S3 (the row-level
  file included, never downloaded), builds the tree with counts from the scored rows, and lists rows by
  category and by low confidence; it runs only when the user asks for the trees or for rows, never for
  the report
- `references/operator.md` — `taxonomy` configuration, constraints, and output contract
- `references/result-interpretation.md` — what to flag and how to read margins
- `../dataset-service-api.md`: job submission details
- `../dataset-import.md`: BYOD import (the SDK's `DataSet.create`, in the generated notebook's Cell 4)
- `../progress-check.md` — mid-job status protocol
