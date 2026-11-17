# Spec Creation Flow

Use this flow when the user wants data preparation operations (ingest, clean, filter, merge, split, dedup) but has not provided a Transformation Spec. The goal is to gather enough information to construct a valid spec, then return to `overview.md` for lane, delivery, and execution dispatch.

**Key principle:** Keep spec creation lightweight — gather just enough to build a valid spec, then let the workflow execution flow handle the details (run directory creation, script generation, dependency checks, etc.).

## Steps

**Ask steps 1–3 together.** First reuse any input, operation, or output values
already supplied in the conversation or a relevant project spec/config. Ask
only for missing values, grouped into one message, and wait once for the reply
— do not pause after each question. The proposed spec values are confirmed in
step 5 before the JSON is constructed or written.

1. **Identify input dataset(s)** — Ask the user for the dataset location. Supported input types: S3 URI, local file path, or SageMaker Hub dataset ARN (e.g., `arn:aws:sagemaker:<region>:<account>:hub-content/<hub>/<type>/<name>/<version>`). Store the original value as-is in the spec's `input` field. API built-in and direct-BYOC paths use a DataSet ARN directly; the local lane resolves its backing S3 location, and CodeGen resolves one exact backing S3 object for schema reconciliation. If the user mentions multiple datasets (e.g., for merging), collect all paths.

   > "Where is your dataset? (S3 URI, local path, or SageMaker Hub dataset ARN)"

2. **Identify desired operations** — Ask what operations the user wants to
   perform. Preserve the user's instruction verbatim. Use the Operation Type
   Inference table in `spec_execution_flow.md` for the local lane and
   `api-execution-flow.md` capability-choice precedence for the API lane.
   Populate `implementation` only when the API lane is already selected. Omit
   it for the local lane or a spec-authoring-only request; if the lane has not
   been selected yet, add it later only if the API lane is chosen.
   Populate `required_fields` from the fields named by the request, and
   `expected_output_fields` with every output field the request requires on
   each record, including an existing field transformed in place. Keep
   conditionally produced fields in the instruction instead.
   If the user describes a multi-step workflow (e.g., "clean and deduplicate my
   data, then split it"), capture each step as a separate operation instruction.

   > "What would you like to do with this dataset? For example: clean it, remove duplicates, filter by quality, split into train/test sets, etc."

3. **Identify output destination** — Ask where the final result should go. If
   the API lane is confirmed, require an `s3://` output prefix. A local path is
   valid only for the local lane. If the lane has not been selected for a
   spec-authoring-only request, record the requested destination and state this
   constraint in the saved-spec summary.

   > "Where should the final output be saved? (S3 URI or local path)"

   **Cross-primitive consistency:** When running after `synthetic-dataset-generation` or `dataset-quality`, default the output to the same S3 prefix the upstream primitive used (check conversation context or the upstream notebook's `OUTPUT_S3_URI`). This keeps all transformation outputs co-located under a single IAM-scopeable prefix. Confirm the default with the user rather than re-asking from scratch.

4. **Hub registration (local lane only, optional)** — For the local lane, if
   the user mentions registering in SageMaker Hub, or if the project context
   includes a Hub ARN, ask whether they want to register the output.

   > "Would you like to register the output dataset in SageMaker Hub? If so, provide the Hub ARN."

   If not relevant, skip this step. Do not add `hub_arn` to an API-lane spec:
   full API jobs publish their output DataSet automatically, while CodeGen Job
   1 publishes no output DataSet.

5. **Confirm the proposed spec** — Summarize the proposed `input`, `output`,
   local-lane `hub_arn` when present, and ordered operations with their
   instruction and known capability/field metadata. For the API lane, summarize
   the selected capability's automatic output-DataSet behavior instead. Ask the
   user to approve those values or request changes. Do not construct or write
   the Transformation Spec JSON before this approval.

   ⏸ Wait for user confirmation.

6. **Construct and write the approved spec** — Build the JSON according to
   `transformation_spec_schema.md` and save it to
   `<project-dir>/specs/transformation_spec_run_NNN.json` (where NNN is the next
   available run number, matching the run directory numbering). For a
   spec-authoring-only request, report the saved path and stop. Otherwise,
   return to the main workflow (overview.md Step 2) to revalidate the confirmed
   lane and execution eligibility, then continue to Step 3 to choose delivery.
