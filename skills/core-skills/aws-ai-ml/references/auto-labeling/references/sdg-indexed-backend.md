# The labeling job

Labeling runs through the **synthetic data generation service** (the SageMaker `DataPreparer` job
service, SDK `sagemaker.ai_registry.DataPreparer`) in **labeling mode**: one `CreateJob` whose
`DatasetOptions.Type` is `labeling.<task>`. The service supplies the labeling program; the skill
sends the spec, the input, the gold and the options, and reads the job's artifacts back. Each input
row produces exactly one output row with its id, so predictions score against gold and join back
to the corpus.

The labeling round (`code_templates/labeling_round.py`, over the SDK operator `operators.job.round`)
is the entrypoint. It talks only to the service and to S3 and never labels a row itself: it reads
the first row of `INPUT_DATA` (nothing else of the corpus), stages the spec, demos and a local
split's gold under `<S3_PREFIX>run-<run id>/<stage>/`, builds and checks the request, submits one
`CreateJob` under a unique job name, and reads the result back through the SDK. An `s3://` or
DataSet-ARN input is named in the request as it is; a local corpus is uploaded byte for byte,
never parsed.

**The request, the rules it is checked against, what the job writes and the summary's keys are the
SDK's**: `sagemaker.ai_registry.data_preparer.auto_labeling.operators.job.request`
(`build_labeling_request`, `request_summary`, the constants) and `operators.job.round`
(`read_round`, `CORPUS_ARTIFACTS`). A request outside the rules fails there with the field named
(`LabelingRequestError`) before anything is uploaded. What the skill writes beside `OUT` is in
`references/input-output-contract.md`; the certificate, cutoff, routing and spot-check rules are in
`references/apply-and-confidence.md`.

## Limits the job enforces

- Task: `classification`, `ner`, `qa`, `ordinal`, `llm_judge`, `summarization`.
- `DATASET_NAME` and `REVIEW_DATASET_NAME`: 1 to 63 letters, digits and hyphens, starting and
  ending with a letter or digit; the two differ.
- Models: 1 to 5 distinct ids. A refine round runs one; a corpus run on a vote task
  (`classification`, `ner`, `qa`) votes 2 to 5 (exactly 1 with a verbalized, judge or panel
  confidence); `ordinal`, `llm_judge` and `summarization` run exactly 1. `summarization` needs 1 to
  3 graders (`GRADERS`), none the labeling model, and takes no gold.
- `TARGET`: 0.85 to 0.99, corpus run only, never on `ordinal`, `llm_judge` or `summarization`
  (no accuracy promise).
- Sizes: the spec at most 64 KiB; at most 100 demo rows (64 KiB); at most 50,000 input rows;
  nothing is certified on fewer than 50 gold rows, and fewer than 100 at a target of 0.95 warns
  of a wide bound.
- Model ids are matched **exactly**, not by family. An unlisted id is refused at `CreateJob`
  before any row is labeled ("ModelId contains unsupported model ... Allowed values: [...]"); the
  round relays that list, which is the live source. Confirm every model and juror id in the HARD
  RULE #2 summary (`references/full-loop.md`).

## Scratch DataSets and re-attach

A reused `DATASET_NAME` appends a version to the existing entry, so every working job (`STAGE =
dev` / `val` / another word) registers under the run-unique **scratch name**
`<dataset name>-<stage>-<run id>`; `RUN_ID` is at most 40 letters, digits and hyphens, and the
name is trimmed to the 63-character Hub limit with the stage and run id kept whole. Each scratch
job's `artifact` run-log entry has `status: scratch` with the DataSet version as `arn` and the job
as `job_arn`; the `hub_ops` `scratch` action (`DELETE = True`) lists and, after the user's yes,
deletes them (the S3 files stay).

Re-running with the same `RUN_ID` and `STAGE` **re-attaches**: a Completed job is read back with
no new job, a running one is reported (with `WAIT = False`) or waited on, and only a Failed,
Stopped or never-created job is submitted again. A re-run under that id with a different request
is refused; use another `RUN_ID`. Without `RUN_ID` the run id is generated and never re-attaches.

## When the job cannot run

- **The service does not carry labeling mode** (its schema has no `DatasetOptions`): the round
  raises `LabelingBackendUnavailable` and **HALTs**:
  tell the user labeling jobs are not available to this account or region, and stop.
- **The SDK is missing**: the cell exits with the SDK-missing message: an install step, not a
  limitation; activate `sdk-getting-started` and run its install to completion.
- **The account cannot run labeling jobs** ("Account is not authorized for this service"), or the
  role does not trust `sagemaker.amazonaws.com` ("Unable to register credentials for customer
  role"): check in the order `references/troubleshooting.md` gives; when
  `AWS_ENDPOINT_URL_SAGEMAKER` is set, ask the user whether to unset it.
- **The job ended Failed or Stopped**: the run exits with the job's `FailureReason`; read the
  job's CloudWatch log, fix the input, and re-run with the same `RUN_ID` and `STAGE`.
- **The job is Partial**: `RowsMissing` rows have no labeled output and were routed to review; the
  certificate scored only the rows present. The run warns and continues.

In every case the skill tells the user and stops; it never labels rows another way.

## Configuration

The round needs, in addition to the model ids:

- `S3_PREFIX`: a writable S3 base for the job's spec, demos, gold, input and output
  (e.g. `s3://<bucket>/autolabel/<project>/`).
- `ROLE_ARN`: an IAM role that trusts `sagemaker.amazonaws.com`, with read and write on
  `S3_PREFIX` and `sagemaker:ImportHubContent` on the hub. Scope it to that prefix and that hub,
  not `s3:*` or `sagemaker:*` (<https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-roles.html>).
- `REGION`.
- `RUN_ID`: one per refinement iteration (Scratch DataSets above).

## Single-invoke LLM calls

Spec induction (`code_templates/induce_spec.py`, the SDK operator
`sagemaker.ai_registry.data_preparer.auto_labeling.operators.spec.induce`) is a one-shot Converse
call over the client-readable seed, not a labeling job; it reads seed rows only, never the corpus,
and reports each read as `client-read:`. Summaries are graded in the job (`GRADERS`); the skill has
no local judge.
