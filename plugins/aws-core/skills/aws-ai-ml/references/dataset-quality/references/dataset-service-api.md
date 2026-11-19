# Dataset Service API — Dataset Quality Evaluation

## Client setup

Both the dataset quality evaluation and the BYOD Hub import run through the
`sagemaker` boto3 client the V3 SDK constructs on `Session()`.

```python
from sagemaker.core.helper.session_helper import Session

session = Session()
```

**Available regions:** us-west-2, us-east-1. This list may change. A submit in another region fails with an error
that names the regions the service accepts.

---

## Dataset Quality Evaluation

`DataPreparer.evaluate()` assembles the CreateJob request, polls DescribeJob and streams the
CloudWatch log (`logs=True`).

```python
dq_config = DatasetJobConfig(input_data_config=[{"DatasetArn": DATASET_ARN}],
                             output_data_config={"S3OutputPath": "s3://my-bucket/dq-output/"},
                             schema_version="3.0.0")
dq_config.evaluation_config = {"Operations": [{"Operator": "default_metrics"}]}
job = DataPreparer(base_job_name="dq-my-eval").evaluate(dq_config, wait=False)
```

`job` is the Job handle (`job_name`, `job_arn`, `job_status`, `wait()`). `job.wait()` polls
DescribeJob and renders progress but does NOT raise: check `job.job_status` yourself and raise
with `job.failure_reason` when it is not `Completed`. On `Completed`,
`json.loads(job.job_config_document)["MetadataS3Uri"]` is the S3 URI of the job's `metadata.json`,
which lists every output file (`references/output-schema.md`).

The blocking form `dq_dataset = preparer.evaluate(dq_config)` also works — it polls (pass
`logs=True` to stream logs) and raises `DataPreparerJobFailedError` on failure — but it returns the
**input** DataSet: `dq_dataset.source` is the input location, not the output folder;
`dq_dataset.job_arn` is the job's ARN, whose last segment is the job name.

**Important:**

- Pin `schema_version="3.0.0"`. Unpinned, the SDK validates against 2.0.0, which requires
  `EvaluationName`, so the request fails client-side (`version=2.0.0 ... EvaluationName: Field
  required`).
- There is no `evaluation_name`. The SDK names the job from `base_job_name` (on
  `DataPreparer(...)` or `evaluate(...)`) plus a 26-character timestamp suffix, cutting the base
  so the name fits 63 characters (about 37 kept); `job_name=` sets an exact name.
- Do not include `EvaluationConfigSchemaVersion`; the service rejects it.
- The role goes on `DataPreparer(role=...)`, NOT on `DatasetJobConfig`.

The skill template in `code_templates/notebook_cells.py` (Cell 8) emits exactly this
shape. For the full set of fields accepted inside `DatasetJobConfig` for dataset quality evaluation,
use live discovery:

```python
DatasetJobConfig.print_schema(JobCategory.DATA_QUALITY_EVALUATION, schema_version="3.0.0")
```

### The request: `EvaluationConfig.Operations`

`evaluation_config` holds one key, `Operations`: a list of `{"Operator": ..., "Config": {...}}`
entries, `Config` optional. Each `Operator` is a metric from `supported-metrics.md` or `on-request-metrics.md`, or one of
three keywords:

| Operator | Runs | Config |
|---|---|---|
| `default_metrics` | The format's default metric set (`format-metric-mapping.md`) on the derived prompt/completion text | none |
| `spec_eval` | Spec-driven evaluation against a requirements document ([below](#spec-driven-evaluation-spec_eval)) | `SpecS3Uri` or `CodeArtifactS3Uri`, plus optional `ContextDocumentsS3Uri`, `DownSampleRecordCount`, `ModelConfig` |
| `exploratory_analysis` | A free-form analysis of the dataset by the service's agent ([below](#exploratory-analysis-exploratory_analysis)) | none |
| a metric (`word_count`, `fuzzy_dedup`, ...) | That metric | Its settings (`supported-metrics.md` or `on-request-metrics.md`), plus an optional `View` |

Entries compose freely: `default_metrics`, extra metrics, `spec_eval`, and `exploratory_analysis`
can all sit in one job. Only the listed operations run.

**Rules checked at submit (400):**

- `Operations` holds 1 to 50 entries, and each entry has only `Operator` and `Config`.
- Each keyword appears at most once. `default_metrics` and `exploratory_analysis` take no `Config`.
- A metric's settings sit beside `View` inside `Config`, spelled as `supported-metrics.md` or
  `on-request-metrics.md` lists them, and are checked against the metric's schema.
- The same metric with an identically written `Config` twice is rejected.
- There are no built-in judged metrics (relevance, accuracy, …); judged quality goes in the spec
  (`quality-job.md` Step 10).

**Repeats caught only at run time (job failure).** The service compares runs again after filling
in each setting's default, so these pass submit and then fail the job:

- The same run written two ways: a setting at its default next to one that omits it (`N: 1` and
  no `N` on `ngram_diversity`), or no `Config` next to `"Config": {}`.
- A default-set metric listed again without a View, with its default settings, next to
  `default_metrics` — that set already makes the run.
- Two runs of a metric that writes per-row columns on the same column, even with different
  settings: their row columns would collide. These are the row-level metrics: of
  `supported-metrics.md`, word_count, character_count, compression_ratio, toxicity,
  content_structures and mif_score; of `on-request-metrics.md`, the filters, exact_dedup,
  fuzzy_dedup, language_detection, pii_detection and taxonomy. Different settings on one
  column work only for aggregate-only metrics
  (`ngram_diversity` with `N: 1` and `N: 4`, `uniqueness`, …).

**What a run-time failure shows:** an error the evaluation finds while it runs gives a
`FailureReason` that starts with `ClientError: The job failed due to invalid input or
configuration.` and ends with the CloudWatch log group and stream that hold the specific message
(the ones quoted in this capability). Checks made before the evaluation starts (the spec or code
artifact exists, the dataset's location and size, the output bucket) and an IAM denial put their
own message in the `FailureReason`.

### View: binding columns to roles

A metric reads the dataset columns its `View` binds. A View is a list of
`{"Role": ..., "Column": ...}` entries; the Role for each metric is in `supported-metrics.md` or
`on-request-metrics.md`.

```python
{"Operator": "word_count", "Config": {"View": [{"Role": "Text", "Column": "answer"}]}}
{"Operator": "mean", "Config": {"View": [{"Role": "Column", "Column": "score"}, {"Role": "Column", "Column": "rating"}]}}
```

**Binding rules:**

- One column, any format with flat columns: `{"Config": {"View": [{"Role": "Text", "Column": "col_name"}]}}`.
- Several columns on one run (`Column` and `Label` roles): one entry per column, `{"Config": {"View": [{"Role": "Label", "Column": "col1"}, {"Role": "Label", "Column": "col2"}]}}`.
- Fan-out (the same metric on several columns, columnar only): separate metric entries, each with its own View; duplicate detection on a columnar prompt+completion format is emitted this way.
- `language_detection` binds exactly one column, `{"View": [{"Role": "Text", "Column": "<col>"}]}`, and takes its parameters by their lowercase catalog names, `languages` and `min_score`, never `Languages` / `MinScore`, which are the dataset-transformation `LanguageFilter` keys. Fan out to a second column with a second entry.
- `pii_detection` binds exactly one of `{"View": [{"Role": "Messages", "Column": "<chat column>"}]}` or `{"View": [{"Role": "Text", "Column": "<text column>"}]}` and takes no parameters: its `Config` holds only the `View`. Fan out to a second column with a second entry.

**Checked at submit (400):** an entry without a `Role`; a Role the metric does not declare (names
are case-sensitive); a missing required Role; more than one column on a one-column Role; a View on
`effectiveness`; a column starting with `dq_input__` (reserved, below); and any other View form —
a bare column string, a column list, or a `{Role: column}` map. The error names the Roles to use.

**Checked at run time (job failure):** a column that does not exist in the records, and a
nested value bound where a metric reads flat text.

**Omitting the View** works only for `Text` metrics on recognized formats: the metric runs on
text the service derives from the format, once on `prompt` and once on `completion` (prompt only
for Nova_CPT and Verl). The output shows that text as `dq_input__prompt` / `dq_input__completion`
(`output-schema.md`). `Column` and `Label` metrics, `language_detection`, and `pii_detection`
always need a View; without one the job fails at run time. An explicit View names only the
dataset's own columns: on a chat format, `completion` is not a column, so binding it fails the job.

### The request shape for a spec

Which document the job evaluates against (a curated spec, an SDG dataset's generation spec, or no
spec) is decided in `quality-job.md` Step 10 before this page is opened. The recommended shape when
a spec is used is the deterministic defaults plus the spec:

```python
dq_config.evaluation_config = {"Operations": [
    {"Operator": "default_metrics"},
    {"Operator": "spec_eval", "Config": {"SpecS3Uri": "s3://.../requirements.md"}},
]}
```

To reuse an SDG dataset's generation spec, run `aws sagemaker describe-hub-content --hub-name <hub>
--hub-content-type DataSet --hub-content-name <name>` and read `SpecS3Uri` from
`HubContentDocument`, then pass it as the `spec_eval` operation's `SpecS3Uri`. With no spec, send
`{"Operations": [{"Operator": "default_metrics"}]}` on a recognized format only: on Custom or
Nova_RLVR data, `default_metrics` and any metric without a View fail the job (`No column mapping
(View) was given, and no default could be inferred ...`); list metrics with explicit Views instead.

### Full surface

Every kind of operation in one request:

```python
dq_config.evaluation_config = {"Operations": [
    {"Operator": "uniqueness", "Config": {"View": [{"Role": "Text", "Column": "answer"}], "CaseSensitive": False}},
    {"Operator": "spec_eval", "Config": {"SpecS3Uri": "s3://my-bucket/specs/requirements.md", "DownSampleRecordCount": 100}},
    {"Operator": "exploratory_analysis"},
]}
```

### Spec-driven evaluation (`spec_eval`)

The user supplies a plain-prose requirements document
(the "spec"); the service derives metrics (measure, report values) and rules
(assert, report per-rule pass/fail verdicts) from it and evaluates the
dataset against them. Spec evaluation runs **only** when a `spec_eval`
operation is listed — it is never included implicitly.

**Config fields:**

| Field | Type | Notes |
|---|---|---|
| `SpecS3Uri` | S3 file URI | The requirements document. A single `.md` or `.txt` file (not a folder). |
| `CodeArtifactS3Uri` | S3 directory URI | The `spec_eval/` directory from an earlier spec run, to re-run its derived criteria without re-deriving them. |
| `ContextDocumentsS3Uri` | S3 folder URI | Optional. The folder of reference documents that `context: documents` criteria are judged against; the URI ends in `/`. What the folder may hold is fixed and checked before compute — see **The documents folder** below. A structured spec with a `context: documents` criterion needs it — see the documents failures below. |
| `DownSampleRecordCount` | integer ≥ 1 | Evaluate the spec on a seeded random subset of this many records (the same rows again for the same dataset). For iterating on a spec before a full run. |
| `ModelConfig.JudgeModelConfig.ModelId` | Bedrock model ID | Optional override of the model used for deriving metrics/rules **and** judging — a single model serves both roles. Omit for the service default (see **Model** below). |

**Exactly one of `SpecS3Uri` and `CodeArtifactS3Uri`** — neither or both is rejected at submit.
There is no fallback to a spec recorded on the dataset. No other key is accepted at any level of
the `Config`: a misspelled or extra key is rejected at submit (`... contains unsupported field:
<key>. Allowed fields: ...`), and so is a `SpecS3Uri` without a `.md` or `.txt` extension.

**The documents folder — what it may hold, checked before compute:**

Every object under the prefix is checked, hidden files (`.DS_Store`,
`.gitkeep`) included; only folder markers (keys ending in `/`) are skipped.
The folder passes when all of these hold:

- Every file carries one of these extensions (any letter case): `.txt`, `.md`,
  `.html`, `.htm`, `.json`, `.jsonl`, `.ndjson`, `.csv`, `.tsv`, `.pdf`,
  `.docx`. Word means `.docx` only; `.doc` is rejected, as is a file with no
  extension.
- No single file is over 10 MB.
- At most 1000 files.
- At most 200 MB in total.

The failure message names the limit in force.

A folder that misses one fails the job in seconds, before compute is
provisioned, like the spec: the `FailureReason` carries the service's own
message, not a `CONTEXT_*` code, naming the field as
`EvaluationConfig.Operations[i].Config.ContextDocumentsS3Uri` (`i` is the
position of the `spec_eval` entry in `Operations`) and the file or folder —
"file '…' has an unsupported file type. Allowed types: csv, docx, htm, html,
json, jsonl, md, ndjson, pdf, tsv, txt", "file '…' (… MB) exceeds the
maximum allowed size of 10.0 MB", "folder '…' contains N files, which exceeds
the maximum allowed count of 1000", "folder '…' contains N bytes of files,
which exceeds the maximum allowed total size of …". The same check fails a
folder whose bucket is in another region, or that is empty. Remove, convert or
rename the named file (or move it out of the folder), or trim the folder, and
resubmit. One rule is applied later, when the job loads the folder: no two
files may differ only in their extension — see `CONTEXT_DOCUMENT_UNREADABLE`
below.

**Documents failures — each stops the job before any row is judged:**

- `CONTEXT_REQUIRED_NO_DOCUMENTS` — a structured spec has a
  `context: documents` criterion and the job names no
  `ContextDocumentsS3Uri`. Supply the folder, or remove the `context:` line.
- `CONTEXT_DOCUMENT_UNREADABLE` — a file in the folder could not be read: a
  PDF or `.docx` file that does not open, a link that leaves the folder, or
  two files whose paths differ only in their extension (`guide.md` and
  `guide.pdf` share the passage-id stem `guide`). The message names the file
  (both, for a shared stem); remove, convert or rename it.
- `CONTEXT_DOCUMENTS_TOO_LARGE` — the documents alone do not fit the judge
  model's window (decided once, before any row). Remove or shorten documents
  until they fit.
- `CONTEXT_TOO_MANY_CRITERIA`: the spec exceeds the documents-criteria cap.
  See `structured-spec.md` for the cap and the merge-or-drop remedy.
  Raised after the criteria are derived and the code is generated, before any
  row is judged.

**Model — spec evaluation has its own default and allowlist:**

The service-owned default and permitted models are:

- `us.anthropic.claude-haiku-4-5-20251001-v1:0`
- `us.anthropic.claude-sonnet-4-6`
- `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
- `us.anthropic.claude-sonnet-5` *(default; Claude Sonnet 5)*
- `openai.gpt-oss-120b-1:0`
- `us.anthropic.claude-sonnet-4-20250514-v1:0`
- `us.anthropic.claude-opus-4-6-v1`

The ID is checked at submit: one outside this list is rejected with a 400 that names the allowed
values, and so is any key in the `spec_eval` `Config` (or in its `ModelConfig`) that the table
above does not list. The job checks the model again when spec evaluation starts, so the job log
also names the set in force. Spec evaluation
resolves to a single ID, so the account needs Bedrock access to that specific model.
`CodeGenerationModelConfig` is rejected at submit (400): one ID drives both roles. The rejection
reads `... ModelId contains unsupported model: <id>. Allowed values: [...]`; that message names the
set the service accepts.

**Which document applies:** the `SpecS3Uri` the operation names. For SDG-generated datasets
where the user wants to reuse the generation spec, read `SpecS3Uri` from the dataset hub
entity and pass it explicitly ("The request shape for a spec" above).

The spec object must exist and be readable by the job's execution role — this
is checked before compute is provisioned; a missing/unreadable spec fails the
job in seconds with the URI named in the `FailureReason`.

**Sample run vs full run (`DownSampleRecordCount`):** offer the user the
choice — both are acceptable:

- **Sample first:** run with `DownSampleRecordCount` (e.g. 100) to evaluate a
  random subset. The job derives the metrics/rules from the spec, writes the
  generated evaluation code to the output alongside the reports, and produces
  per-rule results for the sample, so the user can review how the spec
  was interpreted (derived rules, generated code, sample verdicts) before
  committing to a full run, or edit the spec and re-run the sample if the
  interpretation is off. Run the full dataset from the sample's `spec_eval/` folder
  (`CodeArtifactS3Uri`, no `DownSampleRecordCount`), so it uses the reviewed criteria; re-running
  with `SpecS3Uri` derives the criteria again, and prose criterion ids can change. When the
  criteria use `context: documents`, the re-run must pass the same `ContextDocumentsS3Uri`
  beside `CodeArtifactS3Uri`: the folder is not saved in `spec_eval/`, and a re-run without it
  fails with `CONTEXT_REQUIRED_NO_DOCUMENTS`.
- **One shot:** omit `DownSampleRecordCount` and run the full dataset
  directly.

### Exploratory analysis (`exploratory_analysis`)

The service runs an agent that downloads the dataset into a sandbox and explores it for issues
metric-based checks cannot catch — target leakage, cross-field inconsistencies, label noise,
evaluation-design problems, composition gaps — and returns about 10 to 15 evidence-backed
findings, ranked most consequential first. It takes no `Config`.

It runs alongside the job's other operations, or alone: a job whose only operation is
`exploratory_analysis` runs no metrics, so its `quality_report.json` holds only the findings and
it writes no `evaluated_data.jsonl`. Its output is described in `references/output-schema.md`, "Exploratory Analysis Output".

### Worked examples

**All defaults (deterministic)** — `{"Operations": [{"Operator": "default_metrics"}]}`; spec
evaluation never runs implicitly.

**Curated evaluation spec + deterministic defaults** — the recommended shape when a spec is
used ("The request shape for a spec" above).

**Spec only** — skip deterministic too:

```python
dq_config.evaluation_config = {"Operations": [
    {"Operator": "spec_eval", "Config": {"SpecS3Uri": "s3://my-bucket/specs/requirements.md"}},
]}
```

**Spec sample run with a model override** — review the derived rules and sample verdicts before
the full run:

```python
{"Operator": "spec_eval", "Config": {"SpecS3Uri": "s3://my-bucket/specs/requirements.md", "DownSampleRecordCount": 100,
                                     "ModelConfig": {"JudgeModelConfig": {"ModelId": "us.anthropic.claude-sonnet-4-6"}}}}
```

**Defaults plus duplicate detection** — extra metrics sit next to `default_metrics`:

```python
dq_config.evaluation_config = {"Operations": [
    {"Operator": "default_metrics"},
    {"Operator": "fuzzy_dedup", "Config": {"View": [{"Role": "Text", "Column": "answer"}], "JaccardThreshold": 0.8}},
]}
```

**One metric on a custom-schema dataset** — no format support needed:

```python
{"Operator": "word_count", "Config": {"View": [{"Role": "Text", "Column": "model_response"}]}}
```

**Both unigram and 4-gram diversity** — same metric, different settings, two runs:

```python
{"Operator": "ngram_diversity", "Config": {"View": [{"Role": "Text", "Column": "answer"}], "N": 1}},
{"Operator": "ngram_diversity", "Config": {"View": [{"Role": "Text", "Column": "answer"}], "N": 4}},
```

**One metric across two columns** — two runs, two aggregate entries:

```python
{"Operator": "toxicity", "Config": {"View": [{"Role": "Text", "Column": "question"}]}},
{"Operator": "toxicity", "Config": {"View": [{"Role": "Text", "Column": "answer"}]}},
```

---

## Verify the import

The import itself (the SDK's `DataSet.create`, which writes the 5.0.0 document and picks the hub) is
`references/dataset-import.md`; it applies to bring-your-own-data only. To verify a registered
dataset, run `aws sagemaker describe-hub-content --hub-name <hub> --hub-content-type DataSet
--hub-content-name <name> --hub-content-version <version>` (the version is the last segment of the
Dataset ARN; without it the call returns the latest version) and read `HubContentDocument`
(`DatasetFileFormat`, and `SpecS3Uri` on an SDG dataset).

**Entry points.** SDG result: `input_data_config=[{"DatasetArn": sdg.arn}]`, the `.arn` of the
`DataPreparer.generate(...)` result, with a `spec_eval` operation naming the curated spec or the
generation spec's `SpecS3Uri` (`quality-job.md` Step 10 decides which). BYOD: the imported
`HubContentArn` is the `DatasetArn` (`code_templates/notebook_cells.py` Cell 6 uploads a local
file, Cell 7 imports it); send at least `{"Operations": [{"Operator": "default_metrics"}]}` on a
recognized format; on Custom columnar data send metrics with explicit Views on the discovered
columns; on Nova_RLVR data an explicit View may bind only an additional flat scalar column of the
record, never `messages` or `reference_answer` (the rule of `quality-job-submit.md`'s View
construction rules). Known ARN: skip Cells 6 and 7 of the template and evaluate with the known
`arn:aws:sagemaker:<region>:<account>:hub-content/.../DataSet/<name>/<version>`.

---

## Output

The output contract (the folder under `S3OutputPath` the service names, `metadata.json` at
`JobConfigDocument.MetadataS3Uri` with its `Reports` block of `Aggregate`, `RecordLevel` and
`SpecEval` URIs, `aggregate/quality_report.json`, `record_level/evaluated_data.jsonl`,
`spec_eval/judge_code.py`, the `row_level_criteria` and `aggregate_criteria` sections of a spec
run, and the exploratory findings) is `references/output-schema.md`; a dataset quality evaluation job registers
no new hub content, so `DataPreparer.evaluate()` returns the input DataSet and the output location
is read from `MetadataS3Uri`, never built.
