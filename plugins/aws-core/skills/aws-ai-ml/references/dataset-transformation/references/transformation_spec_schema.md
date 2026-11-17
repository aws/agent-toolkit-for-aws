# Transformation Spec Schema

Every run is driven by a Transformation Spec supplied by the caller or built
with the user. This compact example represents an explicitly selected
local-lane run whose result is registered in the named Hub:
`{"input":"s3://bucket/raw.csv","output":"s3://bucket/result/","hub_arn":"arn:aws:sagemaker:us-west-2:123456789012:hub/my-hub","operations":[{"instruction":"Ingest CSV"},{"instruction":"Clean and deduplicate"},{"instruction":"Transform to SFT"},{"instruction":"Split 80/10/10"}]}`.

- `input` — S3 URI, local path, SageMaker Hub dataset ARN, or an array for
  merge. Preserve a Hub/DataSet ARN in the spec. API built-in and direct-BYOC
  paths use it directly; the local lane resolves its backing S3 location, and
  CodeGen resolves one exact backing S3 object for schema reconciliation.
- `output` — final S3 URI or local path for the local lane; the API lane
  requires an S3 prefix. For a local-lane run whose final operation is `split`,
  this must be a directory/prefix ending in `/`; the run writes
  `split_train.jsonl`, `split_val.jsonl`, and, for a three-way split,
  `split_test.jsonl` beneath it.
- `hub_arn` — optional local-lane Hub ARN for registration after
  transformation. Do not set it for the API lane: full API jobs publish their
  output DataSet automatically, while CodeGen Job 1 publishes none.
- `expected_bucket_owner` — optional 12-digit AWS account ID that must own
  every `s3://` bucket in `input` and `output`. Omit it to use the caller's own
  account. Set it only when the user confirms the data is in a bucket owned by
  another account; S3 rejects a call to a bucket that a different account
  owns. Pass it to the scripts as `--expected-bucket-owner` and to the helpers
  and notebook cells as `expected_bucket_owner`.
- `operations` — ordered natural-language instructions. Types are inferred,
  and one instruction may dispatch multiple sequential operations.
  - `instruction` — preserve the user's instruction verbatim.
  - `implementation` — optional API capability classification: `codegen`,
    `built-in`, or `byoc`. Add it after the API lane is selected, using the
    capability-choice precedence in `api-execution-flow.md`.
  - `required_fields` — optional list of existing input fields the operation
    reads. Reconcile these against the actual dataset schema before CodeGen Job
    1.
  - `expected_output_fields` — optional list of fields the generated sample
    must contain on every output record. Do not list fields produced only
    conditionally; describe those conditions in `instruction` and verify them
    against matching sample records during review.

Never put an invented operator name in the spec. Resolve built-in wire names
through `operator-name-mapping.md` and API capability classification through
`api-execution-flow.md`.

For the local lane, see `spec_execution_flow.md` for inference, fusion,
ordering, and combined instructions that include dedup. For the API lane, use
`api-execution-flow.md` for capability selection and job chaining.
