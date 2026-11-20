# API Execution Flow

> **PRECONDITION — size check. Read this before anything else on this page.**
> `API_CEILING` in `routing-and-guardrails.md` is the largest whole-file input
> covered by this reference's validation evidence, not a universal service
> limit. Above it, recommend sharding or sampling below the ceiling. A
> whole-file managed API transformation may proceed only as clearly labeled
> best-effort guidance after the validation-gap disclosure and explicit user
> confirmation.

Reference for the API lane via the `DataPreparer` pySDK
(`sagemaker.ai_registry`). This file covers what the API lane does once routing has
selected it: input resolution, config assembly, telemetry, and execution
(via `DataPreparer.transform(...)`, with capability-specific wait handling below).

## Template entry requirements

Use `../code_templates/api_transformation.py` only after
`routing-and-guardrails.md` has selected and the user has confirmed the API
lane. It is for one built-in operation per job (Merge accepts two inputs);
CodeGen and direct BYOC use their separate templates. Resolve every placeholder
from the user's intent and `api-operator-configs.md` before running any logic.

For script delivery, write one selected, placeholder-resolved capability
template per service job to
`<project-dir>/scripts/api_<capability>_job_J_run_NNN.py`, using `built_in`,
`codegen_generate`, `codegen_execute`, or `direct_byoc` as the capability slug
and the one-based service-job ordinal as `J`. Increment `J` for every distinct
job artifact in the run, including a regenerated CodeGen Job 1, so no artifact
overwrites an earlier job. For direct BYOC, omit the notebook-only cells and
write the reviewed transformer separately as required below. Run a script
normally with `python3 <script-path>`; do not use `runpy`, `exec`, or another
dynamic execution mechanism. The service job ARN and capability artifacts
remain the authoritative run record. For later status and result inspection,
derive the job name from the saved ARN and run:

```bash
aws sagemaker describe-job --job-name <job-name> \
  --job-category DataTransformation \
  --query '{JobArn:JobArn,JobStatus:JobStatus,SecondaryStatus:SecondaryStatus,FailureReason:FailureReason,JobConfigDocument:JobConfigDocument}'
```

In a notebook, direct BYOC and CodeGen Job 2 use the final `reattach_result`
expression; built-in jobs and CodeGen Job 1 use their capability-specific
status and result outputs below.

## Encryption boundary

S3 applies SSE-S3 encryption at rest by default, and the AWS SDK and CLI use
TLS in transit. Include the exact staging, specification, transformer, review,
and output S3 locations in the applicable Step 4 and API
pre-submission/pre-handoff summary. If the user's compliance requirements call
for a customer-managed KMS key, do not invent a key, change a bucket policy, or
disable encryption. Require the user-approved bucket default encryption, KMS
key and key policy, and execution-role permissions to be in place before any
upload or service submission. See the official Amazon S3 guidance for
[default encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-bucket-encryption.html)
and [encryption in transit](https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingEncryptionInTransit.html).

## Telemetry (REQUIRED on the API lane)

Every API-lane invocation MUST emit BOTH telemetry signals (do not pick one):

1. **`set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)`**.
   Import from `sagemaker.core`. Call before the FIRST pySDK call on the API lane —
   including `DataSet.create(...)` (input registration), which runs before
   `DataPreparer` is constructed; otherwise the registration call runs
   un-attributed. (Enum value: `awslabs/agent-plugins/sagemaker-ai`.)

   ```python
   from sagemaker.core import set_attribution, Attribution
   set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
   ```

2. **`SAGEMAKER_PYSDK_CREATED_BY` env var** — set in the notebook/session
   environment so the SDK stamps provenance on the created job.

## SDK requirement

The API lane needs the SageMaker SDK that ships `DataPreparer`
(`sagemaker.ai_registry`) and `set_attribution`
(`sagemaker.core.telemetry.attribution`). Complete the shared
`sdk-getting-started` workflow and verify those imports before using this lane.
Dataset transformation does not install the SDK or copy its artifacts.
Parquet CodeGen schema inspection also requires `pyarrow`; verify that import
for a Parquet input because the pySDK has no Parquet schema-reader surface.
The schema preflight uses the session's S3 client only for a bounded `Range`
read because `S3Downloader.read_file` has no byte-range operation. Pass the
spec's `expected_bucket_owner`, or the caller's account when omitted, as
`ExpectedBucketOwner`. The Parquet metadata reader uses
`pyarrow.fs.S3FileSystem` with the session region and frozen temporary
credentials so its read uses the same identity as the owner-pinned
`head_object`. The credentials remain in memory and are not printed or
persisted.

## Input resolution to DatasetArn

The API takes registered **DataSet** inputs, not raw S3 paths. Each
`InputDataConfig` entry is a `DatasetArn` (a hub-content ARN, e.g.
`arn:aws:sagemaker:us-west-2:<acct>:hub-content/<Hub>/DataSet/<Name>/<Version>`).
Registration is only needed for the **API lane** — local execution reads S3/local
files directly and needs no DataSet.

> **Submit the transform against the endpoint where the input DataSet is
> registered** — the transform must use the same AWS Region and SageMaker
> endpoint the DataSet is registered in. Verify the DataSet resolves with
> `aws sagemaker describe-hub-content --hub-name <hub-name> --hub-content-type DataSet --hub-content-name <dataset-name> --hub-content-version <version>`,
> then submit against the same endpoint. See
> `../../sdk-getting-started/references/sagemaker-python-sdk-setup.md` Step 4 (Configure
> Endpoint) for how the endpoint is resolved.
>
> Rationale: submitting against the wrong endpoint fails with a misleading
> `"Hub content with name <name> does not exist"` — the content is invisible from the
> wrong endpoint, not actually missing.

### Input format precheck — do BEFORE registration

DataTransformation accepts **JSONL (the canonical format), CSV, TSV, and Parquet**
inputs. It does **not** accept **Arrow/Feather or single JSON-array** files, which
must be converted to JSONL before they can be registered and transformed.

So BEFORE registration below, detect the source format (file extension +
a content sniff of the first bytes/lines):

- **JSONL / CSV / TSV / Parquet** → accepted as-is; register without conversion.
- **Arrow / Feather / single JSON-array** → **convert to JSONL first** via
  the ingest operation (see `op_ingest.md`), then register the converted JSONL.
  `DataSet.create(source=<s3_uri>)` reads the source from S3, so upload the converted
  file first — derive the bucket from the exact destination URI, run
  `aws s3api head-bucket --bucket <bucket> --expected-bucket-owner <account-id> --region <region>`,
  then run `aws s3 cp '<local>.jsonl' '<s3_uri>' --region <region>`.
  The owner-pinned preflight requires `s3:ListBucket`; high-level `s3 cp`
  supports multipart uploads but cannot carry `ExpectedBucketOwner`.
  The `<account-id>` is the caller's account (`aws sts get-caller-identity --query Account --output text --region <region>`)
  or the account the user named for that bucket — then register that URI.

When a local source has selected the API lane, accepted formats still require
staging because `DataSet.create` cannot register a local path. Use the exact S3
object URI confirmed under input resolution below, upload the unchanged file
after approval, and register that object.

**Prefer JSONL even when CSV/TSV would be accepted.** Only JSONL maps to the
recognized record schemas in `sagemaker_dataset_formats.md` (OpenAI / HF-Prompt-
Completion / SageMaker-Eval / Verl / Nova). CSV/TSV are accepted and the job still
runs, but they are treated as an unrecognized (`Custom`) schema — so the job proceeds
without schema-aware grounding, and schema-aware operations (e.g. `SchemaConversion`)
have no field mapping to work from. Convert CSV/TSV to a recognized JSONL schema only
when a downstream operation needs one; otherwise CSV/TSV is fine as-is.

**Respect the local-processing cap when converting.** This conversion is a
format-normalization preprocessing step, not a workflow `operation`, and it does not
change the local-lane/API-lane routing _decision_ (`routing-and-guardrails.md`). At or
under `LOCAL_CAP`, use the local ingest operation and upload its JSONL result. Above
`LOCAL_CAP`, this reference has no validated whole-file conversion path for an
unregistrable Arrow/Feather or JSON-array input. Use the managed script path in
`../../processing-jobs/overview.md`, with an image that has the required format
reader, to write one JSONL object to S3; then return here and register that object.
Do not submit the Arrow/Feather or JSON-array source directly to
DataTransformation or CodeGen.
State the proposed conversion, staging object, and DataSet registration in the
Step 4 artifact summary. After artifact generation, include those side effects
in the applicable pre-submission or pre-handoff approval under input resolution
below; do not add another upload-only approval.

**Scope of this precheck.** It covers the common path where a raw `s3://` input is
registered here via `DataSet.create`. On built-in and direct-BYOC paths, an input
supplied as an **already-registered** `DatasetArn` (case 1 below) is not
re-inspected — if that DataSet is backed by a non-JSONL / non-Parquet file the
transform can still fail downstream; re-register it from a converted JSONL source
in that case. CodeGen Job 1 is the exception: resolve and inspect its exact backing
S3 object to set `INPUT_FORMAT` and reconcile the requested fields before
registration.

Because a user typically arrives with raw S3 data, resolution to a `DatasetArn`
happens **at runtime**, as part of taking the API lane:

1. **Already a DataSet ARN** → use it directly.
2. **Local file with the API lane confirmed** → resolve and confirm an exact
   staging `s3://` object URI and include the proposed object in the Step 4
   artifact summary. After artifact generation, use the delivery-specific
   approval gate: for script delivery, obtain the separate API pre-submission
   approval; for notebook delivery, obtain the separate API pre-handoff
   approval before the agent uploads the object. The approval must cover the
   new S3 object, DataSet registration, possible charges, and reversibility;
   Step 4 artifact approval and lane confirmation are not sufficient. After
   approval, upload an accepted source unchanged, or upload the JSONL produced
   by the format conversion above, then continue with case 3. For notebook
   delivery, complete that upload before handoff and do not add an input-upload
   cell—the service cells consume the object but do not create it. The local
   source remains unchanged.
3. **Raw `s3://` input** → **register it at runtime** via the pySDK
   `DataSet.create(name=<name>, source=<s3_uri>, wait=True)`
   (`sagemaker.ai_registry.dataset.DataSet`), which returns a `DataSet` whose
   `.arn` is the `DatasetArn` to transform. `DataSet.create` wraps
   `AIRHub.import_hub_content` internally — you do NOT call `import_hub_content`
   directly (that keeps the whole API lane on the pySDK surface, consistent with the
   pySDK-only execution rule). Do NOT pass a bare `s3://` URI as a transformation
   input, and do NOT treat registration as an out-of-band user prerequisite — it is a
   runtime step of the API lane.
4. **Input count cap: 2.** `InputDataConfig` accepts at most **2** entries.
   A single-input op uses 1; `Merge`
   uses 2.
5. **More than 2 inputs** → **chained pairwise merges**: merge two at a time across
   sequential jobs, feeding each merge's output DataSet into the next.

For the built-in template, populate ordered `API_INPUTS` with one entry, or two
for `Merge`; each entry sets either `DatasetArn` or `S3Uri` plus `DataSetName`
for that raw S3 input.
For direct BYOC, set exactly one of `INPUT_DATASET_ARN` or `INPUT_SOURCE`.
CodeGen Job 1 remains different: it requires and registers the exact backing S3
object used for schema reconciliation and review.

## Config assembly per operation

For each operation, assemble the `Config` object **from `api-operator-configs.md`**
(which is generated from the runtime operator schema). Rules:

- **Never invent fields.** Only emit keys that appear in the operator's schema;
  unknown keys are rejected (`additionalProperties:false`). If the user asks for a
  parameter the operator doesn't have, say so — don't silently drop or rename it.
- **One operation per job.** Each job runs a single operator. A multi-step
  workflow (e.g. dedup → split) is executed as **chained jobs**: the output
  DataSet of one job is the input of the next.
- **Split is normally terminal.** If the request places an operation after
  Split, surface the configured output names and ask whether to continue from
  one named output or fan out separate downstream jobs for every output.
  Preserve that decision in the Step 4 chain summary and downstream job
  inputs; never silently select `outputs[0]`.
- Resolve the intent to an operator via `operator-name-mapping.md` first, then fill
  its Config from `api-operator-configs.md`.

## Execution role preflight (do BEFORE submitting the transform)

The transform runs under a caller-supplied **execution role**, and the DataTransformation service
assumes it to read the input, write the output, and publish the result DataSet. A
role that is missing trust or permissions produces a **server-side execution-time
failure minutes into the job**, not a fast client-side error — so verify it up front
rather than discovering it in a post-mortem. Before the first `transform` call, confirm:

1. **Trust** — the role trusts the DataTransformation service (`sagemaker.amazonaws.com` in its
   `AssumeRolePolicyDocument`). A role that does NOT trust the service (e.g. a plain
   `Admin` role) fails at execution with "Unable to register credentials for customer
   role …". (See `../../sdk-getting-started/references/execution-role-setup.md` for the
   trust check.)
2. **S3 read + write** on BOTH the input source bucket and the `OutputDataConfig`
   output bucket (`s3:GetObject`, `s3:PutObject`, `s3:ListBucket`).
3. **`sagemaker:ImportHubContent`** on the target hub + `hub-content/<Hub>/DataSet/*`
   — required to publish the output DataSet version. Missing this is the classic
   "job Completed but no OutputDatasetArns / publish failed silently" footgun.

Surface any gap to the user and stop before submitting; do not let the job run and
fail server-side.

## Execution via pySDK

All execution is through the `DataPreparer` pySDK (`sagemaker.ai_registry.data_preparer`).

**Choose the API capability path by the operation type:**

- The user explicitly selects service **CodeGen** for a natural-language
  transform → **CodeGen two-job path** below, even when a built-in operator
  could perform the transform. Briefly identify the built-in default when
  relevant, but honor the user's capability choice; do not refuse or repeatedly
  redirect them to the built-in.
- The user supplies transformer source without separately selecting CodeGen,
  explicitly asks the agent to author direct-BYOC code instead of using
  CodeGen, or a validated workflow reference explicitly owns a direct-BYOC
  implementation → **direct BYOC path** below. Direct BYOC is not CodeGen and
  never submits a CodeGen job.
- The user explicitly requests custom or bespoke row-filter logic and provides
  complete predicates sufficient to author the transformer without designing
  or inferring missing behavior → **direct BYOC path** below.
- Otherwise, the operation's complete requirements are exactly expressible by
  the documented Config of one of the **built-in operations** (FuzzyDedup,
  ExactDedup, Split, Merge, SchemaConversion, SchemaFilter, TextQualityFilter,
  LanguageFilter, PiiRedaction) → **Built-in operations** below (a single
  `transform` call, no preview step). A broad local intent label alone does not
  satisfy that condition.
- Otherwise, the operation is expressed as a plain-language transform and has **no
  deterministic built-in operator** → **CodeGen two-job path** below. Route to
  CodeGen even when the instruction is precise enough for a programmer to
  implement directly because CodeGen produces a reviewable sample before any
  full-dataset execution.

**Capability-choice precedence:** detailed prose alone is not BYOC except for
the complete custom or bespoke row-filter predicate case above; never invent an
operator name for a custom transform or refuse it solely because no built-in
matches.

### CodeGen schema and specification preflight

Complete this preflight after the user confirms the API lane and before
submitting CodeGen Job 1:

1. Fill `REQUIRED_INPUT_FIELDS` from the fields named by the request; do not
   guess or add fields. The template derives the actual top-level schema from a
   bounded JSONL/CSV/TSV sample or Parquet metadata. A field proven absent by a
   complete bounded sample or metadata stops before Job 1; a truncated JSONL
   sample warns because a sparse field may appear later or the first record may
   be larger than the bounded sample.
   Fill `INPUT_FORMAT` from the format precheck above rather than inferring it
   from the object suffix. `INPUT_SOURCE` must be the exact backing S3 object,
   not a bucket, prefix, or DataSet ARN. If the request starts from an
   already-registered DataSet, resolve its backing source through the pySDK
   before assembling Job 1; stop and ask for the exact object if it cannot be
   resolved unambiguously. Job 1 registers that object as its review input.
   Resolve `[EXPECTED_BUCKET_OWNER]` to the spec's confirmed account ID, or the
   caller account from
   `aws sts get-caller-identity --query Account --output text --region <region>`
   when the field is omitted.
2. Preserve the user's transformation instruction verbatim in the spec. Record
   `implementation: codegen`, the referenced `required_fields`, and any
   `expected_output_fields`. List only fields required on every output record;
   describe conditionally produced fields in the instruction and validate them
   against matching sample records during review. Include the request's field
   contract, fields that must remain unchanged, exact replacement values, and
   required edge cases in the CodeGen specification.
   When resolving `[TRANSFORMATION_SPEC_TEXT]` in the Python artifact, replace
   the entire placeholder expression with `repr(spec_text)` or an equivalent
   safely escaped Python string literal. Never interpolate the instruction
   between prewritten quote delimiters.
3. Reconcile every referenced field against the actual input schema. **Stop
   before Job 1** when a complete bounded sample or metadata proves a required
   field is absent. Show the requested fields and available fields, then ask the
   user to correct the field mapping or revise the transformation. For a
   truncated JSONL sample, warn and allow Job 1 because a sparse field may
   appear later. Never submit a known-mismatched spec and never describe a
   100%-error or zero-output result as successfully completed.

For regex-style or literal-replacement requests, make the specification
unambiguous and include exact edge cases visible in the reviewed input. If the
generated code or sample misses a required edge case, report it, propose
strengthened specification text, and ask the user to approve rerunning Job 1.
The rerun is a new billed CodeGen job, registers another input DataSet version,
and discards the earlier candidate. Wait for explicit approval. Do not approve
or locally patch around the failed candidate.

Select exactly one capability path per operation/job and use only its
template:

| Capability path            | Template(s)                                                               |
| -------------------------- | ------------------------------------------------------------------------- |
| Built-in operator          | `../code_templates/api_transformation.py`                                 |
| CodeGen generate/sample    | `../code_templates/api_codegen_generate.py`                               |
| CodeGen approved execution | `../code_templates/api_codegen_execute.py`                                |
| Direct BYOC                | `../code_templates/byoc_transformer.py` + `../code_templates/api_byoc.py` |

Do not concatenate alternative implementations of the same operation into a
notebook that can run top to bottom. A multi-step workflow may chain different
capability paths across separate jobs—for example, CodeGen materializes a flat
chat-text field, then a built-in `LanguageFilter` job reads that field. Emit
one ordered capability-template group per job, and use each completed group's
output DataSet ARN as the next group's input. For Split, follow the terminal or
explicit named-output/fan-out decision above rather than assuming a singular
handoff. Each job keeps its own template and approval boundary; a background
job must complete before its dependent group is emitted or run. In particular,
a direct BYOC request must not generate code with CodeGen first, and CodeGen
Job 2 is emitted only after its later review approval.

### Built-in operations

For the 9 built-in operations (FuzzyDedup, ExactDedup, Split, Merge,
SchemaConversion, SchemaFilter, TextQualityFilter, LanguageFilter, and PiiRedaction), run a single
`DataPreparer.transform(...)` call:

- `transform(wait=True)` is the default. It blocks, streams status
  transitions, and returns `List[DataSet]` (always a list, even for one output).
  The cases that use `wait=False` instead, including every `PiiRedaction` job, are
  under "wait handling" below.
- Give each job a unique `job_name`. It must be **≤ 63 characters** and match
  `[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}` — `transform`/`DescribeJob` reject anything
  longer or otherwise non-conforming. A `{dataset}-{operator}-{timestamp}` name can
  exceed 63 chars for a long dataset name, so truncate the dataset-name prefix (keep
  the operator + timestamp suffix whole for uniqueness), as the code template does.
- **No preview / no sample step** for built-in operations — they are
  correctness-provable and run straight to full execution once the user approves the
  exact API submission summary at the Step 5 submission gate in `../overview.md`.
  "No sample step" means built-in
  operations skip the generate-and-stop-for-review pause that CodeGen uses; it does
  **not** skip the pre-execution approval — the agent must still get the user's
  approval before submitting the job. (The sample/review pause is CodeGen-only; see
  the CodeGen two-job path below.) For `LanguageFilter`, the Data Quality
  `language_detection` metric is the preview (see `api-operator-configs.md`); for
  `PiiRedaction`, the `pii_detection` metric is.

### wait handling

- **Default to `wait=True`** (blocking). Only use `wait=False` for the two cases
  below.
- Flip to **`wait=False`** only on (a) an explicit user "run in background" request,
  or (b) a size/duration estimate crossing a large-dataset threshold. Every `PiiRedaction`
  job meets (b): it makes a model call per row, so it is long-running at any size.
  Every full-dataset direct BYOC and approved CodeGen Job 2 run also meets (b);
  their templates default `WAIT = False`.
  `wait=False` returns a **job handle** exposing `job.job_arn`.
- **No settable timeout.** There is no timeout parameter. If a `wait=True` call
  raises `DataPreparerJobTimeoutError` (a sagemaker-core waiter timeout, carrying
  `job_arn` + `elapsed_seconds`), **catch it, detach, and surface the `job_arn`** so
  the user can reattach later — do not hang.
- **`logs` require `wait=True`.** Streamed logs are only available in blocking
  mode; a `wait=False` handle does not stream logs.
- **`attach(job_arn)` is cross-session** — a job started in one session (or as a
  `wait=False` handle) can be reattached later to get its result/status.
- **No local analog.** Local runs are synchronous `python3` subprocesses with no
  `job_arn`/`attach`/`wait`; this whole section is API-lane only.

### CodeGen two-job path

CodeGen uses **`AutoExecute=False`** (two jobs), NOT one-job AutoExecute:

1. **Job 1 — generate + sample + STOP.** `AutoExecute=False` generates
   `transformer.py` and a sample output, then halts. Generate this artifact from
   `api_codegen_generate.py`; fill its visible `TRANSFORMATION_SPEC` with the
   complete agreed request. Fill its required input fields from fields named in
   that request and its expected output fields from outputs required on every
   record. The artifact derives the actual top-level fields with a bounded
   JSONL/CSV/TSV sample or Parquet schema metadata, rejects proven field
   mismatches, and warns when a truncated JSONL sample cannot prove a sparse
   field absent. It uploads the exact text to
   `SpecificationS3Uri` and contains no full-dataset execution cell. This
   review-only job does not publish an output DataSet. Wait on its Job handle
   and read
   `TransformationCodeS3Uri` and `TransformationReportS3Uri` from the completed
   `DescribeJob.JobConfigDocument`; do not try to rehydrate `OutputDatasetArns`.
   The sample is `sample_output.jsonl` beside the report, and the template
   verifies both S3 objects and output fields required on every record before
   presenting their URIs.
   The template defaults `WAIT = True`. If the user chooses background
   submission, set `WAIT = False`; Cell 4 submits, prints the job ARN, and
   returns without reading review artifacts. Retain the printed input DataSet
   ARN with the job ARN. To resume, put the job ARN in `JOB_ARN`, set
   `WAIT = True`, and rerun the artifact's cells. Cell 3 skips spec upload and
   input registration when `JOB_ARN` is present, and Cell 4 attaches to the
   existing job, recovers the input DataSet ARN from
   `JobConfigDocument.InputDataConfig`, then retrieves the review artifacts.
2. **Review + approve — HARD STOP.**
   - **Retrieve:** Set `AWS_SDK_UA_APP_ID=AWSSkill-SageMaker`, create a
     permission-restricted `<project-dir>/review/<codegen-job-name>/`
     directory, then download the printed source and sample S3 objects to
     `transformer.py` and `sample_output.jsonl`. The template prints their
     exact URIs but does not print their contents.

   ```bash
   export AWS_SDK_UA_APP_ID=AWSSkill-SageMaker
   install -d -m 700 <project-dir>/review/<codegen-job-name>
   aws s3api get-object --bucket <code-bucket> --key <code-key> --expected-bucket-owner <account-id> --region <region> <project-dir>/review/<codegen-job-name>/transformer.py
   aws s3api get-object --bucket <sample-bucket> --key <sample-key> --expected-bucket-owner <account-id> --region <region> <project-dir>/review/<codegen-job-name>/sample_output.jsonl
   ```

   Derive each bucket and key from its printed `s3://` object URI. Read both
   local files after restricting each to the current user with `chmod 600`.
   - **Review:** Surface the actual generated `transformer.py` source, the
     sample's local path and S3 URI, and its record count in the current secure
     user session. Check schema access, field preservation, expected output
     fields, exact replacement tokens, and exact edge cases. Offer to show the
     actual transformed sample contents; show them only if the user asks,
     following `../overview.md` → "Showing records". Do not copy sample data
     into tickets or unrelated logs.
   - **Disclose:** Explain that Job 2 is a billed full-dataset
     DataTransformation job that publishes a new output DataSet version while
     leaving the source unchanged; rerunning does not undo or replace that
     output. For an explicit PII-to-CodeGen override, warn that the sample may
     still contain unredacted PII. If the user asks to see sample records,
     display only the fields the transform changed. Before approval, also state
     that the published output DataSet may still contain PII the generated code
     did not match and that `PiiRedaction` remains the validated path for PII.
   - **Stop:** End the turn and wait for explicit user approval. Earlier
     approval of the transformation spec or artifact generation is not
     approval of generated code.
   - **Clean up:** After the user approves or rejects the candidate, remove
     `<project-dir>/review/<codegen-job-name>/` and its transient source and
     sample copies. Job 2 uses the approved S3 source URI; the local review
     directory is not a run artifact and must not be retained.
3. **Job 2 — full run with generated code.** Job 2 must be created and
   submitted only in a later turn after the user approves the reviewed code
   and sample. Run the generated code over the full dataset using
   `api_codegen_execute.py`. Pass Job 1's retained or recovered
   `input_dataset_arn` as `INPUT_DATASET_ARN` and its approved URI as
   `APPROVED_GENERATED_CODE_S3_URI`; do not reuse the direct-BYOC
   `USER_TRANSFORMATION_CODE_S3_URI` variable. The execute template has an
   explicit `USER_APPROVED` guard, refuses to submit when it is false, submits
   with `WAIT = False`, and prints the UTC submission time and job ARN for
   later re-attachment.

   `APPROVED_GENERATED_CODE_S3_URI` must be the reviewed Job 1 `s3://` object
   URI. The execution template does not accept an HTTPS URL for
   `TransformationCodeS3Uri`.

(`AutoExecute=True` self-executes the full dataset in one job and IS implemented, but
the skill deliberately uses the two-job path so the user can review and approve the generated code before full execution.)

### Direct BYOC path

- **Direct BYOC means separately supplied or explicitly requested
  user/agent-authored code, not service-generated code.** When the user
  supplies the transformer source, preserve it as the reviewed
  `transformer.py` and submit it through `api_byoc.py`; this path does not run
  CodeGen. Only start from `byoc_transformer.py` and implement its edit region
  when the user explicitly requests agent-authored direct-BYOC code, explicitly
  requests custom or bespoke row-filter logic with complete predicates, or a
  validated workflow reference requires that implementation. In notebook mode,
  write the reviewed source to `[PROJECT_DIR]/scripts/transformer.py` during
  artifact generation and emit the separate `%%writefile` cell with identical
  source; copy user-supplied source to that canonical path if needed. Before
  writing or copying, compare an existing canonical file with the reviewed
  source. Reuse it when identical. If it differs, include the potential
  overwrite at the Step 5 artifact-generation approval point and ask whether
  to replace it or use a different project/path. State that replacement
  overwrites the existing contents and is not automatically reversible; do not
  write until the user decides. After that
  conflict is resolved, keep the required notebook `%%writefile` cell. In
  script mode, create the directory and write the file directly before running
  the submitter. The submitter reads the reviewed file from disk and uploads it to
  `USER_TRANSFORMATION_CODE_S3_URI`, then uses that URI as
  `TransformationCodeS3Uri`. It contains no `CodeGen` operator and no
  `SpecificationS3Uri`. The full-dataset submit uses `WAIT = False` and prints
  the UTC submission time and job ARN for later re-attachment.
- The code must expose `transform_dataset(inputs: dict[str, str], output_dir: str) -> dict`, reading each input from the `inputs` name→path mapping, writing output file(s) into `output_dir`, and returning a stats dict (`{"outputs": [...], "total_records": int, "transformed_records": int, "errors": int}`).
- `BYOCConfig` must NOT accept `AutoExecute` (CodeGen-only key).
- Do not point direct BYOC at a CodeGen output URI. Conversely, do not describe
  CodeGen Job 2 as the user's direct BYOC artifact; both use the BYOC wire
  operator, but their provenance and approval gates are different.

### Progress + actionable failure

- On `wait=True`, surface the streamed status transitions as progress.
- **For a successful full-dataset job, report the output DataSet ARN,
  `ds.source`, and the report's size — do NOT read or parse `report.json`.**
  CodeGen Job 1 is the exception described above: it reports its job,
  generated-source, and sample URIs and has no output DataSet. Every completed
  full-dataset job writes `report.json` in its output folder,
  `{S3OutputPath}/data-transformation/{job_name}/{createdAt}/`,
  where `{createdAt}` is the job's creation time without colons (shaped like
  `YYYY-MM-DDTHHMMSS.sssZ`). Do not build `{createdAt}` by hand: list
  `{S3OutputPath}/data-transformation/{job_name}/` and use its one folder. Jobs that
  ran before this layout wrote to `{S3OutputPath}/{job_name}/` instead. Check the
  report's SIZE via S3 object metadata: run
  `aws s3api head-object --bucket <report-bucket> --key <report-key> --expected-bucket-owner <account-id> --region <region>` and read
  `ContentLength` — not the object's contents. Tell the user whether the report
  is large or small, along with the `report.json` S3 URI so they can open the
  raw file themselves if they want the per-operation detail. Do not download
  the object, do not `json.loads` it, and do not iterate `operations[]` in code.
  The size signal plus the URI is the deliverable. (The schema block below is
  NOT needed for this success path — it exists only for the
  rehydration-fallback bullet, the one case that does read `report.json`.)
- **A `transform()` that raises `OutputDatasetArns`-missing on a job that actually
  reached `Completed` is NOT a failure — treat it as a success and fall back.**
  `transform(wait=True)` result rehydration (`_rehydrate_datasets`)
  can throw when a Completed job's `DescribeJob.JobConfigDocument` carries no
  `OutputDatasetArns`, even though the transform ran and wrote output. Do not report
  failure. Instead, run
  `aws sagemaker describe-job --job-name <job-name> --job-category DataTransformation`
  to confirm `JobStatus=Completed`, then read
  the output from the job's output folder (above) — `report.json` has the structure
  below, and `dataset.jsonl` is the transformed data (an `_response.json` sidecar also
  lists the output datasets). This fallback is the ONE case that reads `report.json`:
  parse it to confirm the recovered job's `operations[]` produced output (non-zero
  output records, `failure_info` is null), then report the DataSet ARNs from the
  `_response.json` sidecar. Only a genuinely non-terminal / `Failed` / `Stopped`
  DescribeJob status is a real failure.

  `report.json` contains `report_version`, `job_name`, an `operations` array,
  and nullable `failure_info`. Each operation reports its operator, duration,
  input and output record metadata, error count, operator details, and optional
  row outcomes. Merge and Split entries may add names to input/output objects.
- On failure, map the DataPreparer exception taxonomy (the exception types the
  pySDK raises) and enrich job-lifecycle
  failures via **DescribeJob only** (do not invent internal error detail). The full
  hierarchy:

  - `DataPreparerConfigurationError` covers incomplete or invalid pre-submit
    configuration.
  - `DataPreparerSchemaNotFoundError` and
    `DataPreparerSchemaValidationError` derive from `DataPreparerSchemaError`.
  - `DataPreparerJobFailedError`, `DataPreparerJobStoppedError`, and
    `DataPreparerJobTimeoutError` derive from `DataPreparerJobError`.

  - The **job-lifecycle** family (`DataPreparerJobError` subtree) is what maps to
    DescribeJob: `DataPreparerJobFailedError.failure_reason` / `.secondary_status`
    are the DescribeJob-derived detail to surface; `DataPreparerJobTimeoutError`
    carries `job_arn` + `elapsed_seconds` → catch, detach, surface `job_arn`.
  - The **schema/config** family (`DataPreparerConfigurationError`,
    `DataPreparerSchemaError` subtree) is client-side / pre-submit — see the
    Config-typo failure surfacing section below.
- **API runs do NOT write the local manifest or local-lane per-run scripts**
  (`ManifestWriter` / `scripts/run_NNN/` are local-only). API script delivery
  does write the standalone
  `scripts/api_<capability>_job_J_run_NNN.py` submission artifact defined
  above. The Step-1
  Transformation Spec may already exist on disk — that is the plan, not the run
  record. Reference the `job_arn` plus capability-specific service artifacts:
  CodeGen Job 1 uses the generated-source and sample URIs, while a full run also
  uses its output DataSet ARN(s). This is the API-lane form of overview.md
  Principle 6; the service record replaces local run files.

### Config-typo failure surfacing

The SDK **does** validate the operator `Config` client-side, via a dynamic Pydantic
model built from the Hub `JobConfigSchema` — so a typo is caught pre-submit, not only
server-side (except `LanguageFilter` and `PiiRedaction`, whose `Config` is checked only
when the job runs; see `api-operator-configs.md`). Three distinct exceptions carry the actionable detail:

- **`DataPreparerSchemaValidationError`** — the payload failed Pydantic validation
  (wrong/missing/misspelled Config key or bad value). It carries the pydantic error
  list on **`.errors`** plus `category` + `schema_version`; surface the offending
  field(s) from `.errors` and the accepted set from `api-operator-configs.md`.
- **`DataPreparerSchemaNotFoundError`** — no schema exists for the requested
  `(category, version)`. It carries `available_versions`; surface those.
- **`DataPreparerConfigurationError`** — pre-submit config is incomplete/invalid in a
  non-schema way (e.g. missing required inputs).

Point the user at the pySDK's `DatasetJobConfig.print_schema(JobCategory.DATA_TRANSFORMATION)` for the live contract in all three cases.

### Immutability / output as a new hub version

Treat source DataSets as **immutable** — never overwrite the input. Publish each
transform's output as a **new hub content version** (a new DataSet / version), so the
input is preserved and the lineage is a forward chain. This is behavior to implement
and assert, not just document.
