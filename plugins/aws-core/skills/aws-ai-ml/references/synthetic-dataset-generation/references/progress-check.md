When the user asks about job progress, status, or how many records have been generated (e.g., "how many samples generated?", "how many records have been created?", "what's the status?", "how many samples do we have so far?"), follow this logic:

1. **Re-attach to the job** to get current status. **This is an agent-side step — the agent calls `.attach()` itself to answer the user's progress question. Do NOT write this as a notebook cell.** Use the job ARN saved from submission:

   ```python
   from sagemaker.ai_registry import DataPreparer
   from sagemaker.core import Attribution, set_attribution
   set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
   job = DataPreparer.attach(job_arn, wait=False)
   # job.job_status, job.secondary_status, job.failure_reason, job.created_at
   ```

   This calls `DescribeJob` internally and populates the Job handle. Use the `OutputS3Uri` from `json.loads(job.job_config_document)` for S3 lookups — do NOT rely on earlier conversation context for the output path, as it may be stale or incorrect.
2. **If `job.secondary_status` is `Executing`**, locate the output file in S3:
   - Build a timestamp with minute precision from `job.created_at` (may be `datetime` or ISO string per the SDK): format as `%Y-%m-%dT%H%M`. Example output: `2026-05-12T0652`.
   - S3 prefix: `{OutputS3Uri}synthetic-data-generation/{jobName}/{truncated}` (no extra `/` after `OutputS3Uri` — it already ends with one). Example full URI: `s3://bucket/output/synthetic-data-generation/tech-doc-generator-1778568771/2026-05-12T0652`.
   - Run `aws s3api list-objects-v2 --bucket <bucket> --prefix <key-prefix>` with bucket and bare-key prefix separately — e.g. `--bucket bucket --prefix output/synthetic-data-generation/tech-doc-generator-1778568771/2026-05-12T0652`. Look for a key ending in `/job_metadata/verified_samples.jsonl`.
   - If that prefix holds no such key, list the earlier layout's prefix the same way: `{OutputS3Uri}{jobName}-{truncated}` (e.g. `--prefix output/tech-doc-generator-1778568771-2026-05-12T0652`). Jobs that started before the service moved SDG output under `synthetic-data-generation/` write there.
   - If multiple matches are returned (unlikely — would require two jobs with the same name in the same minute), pick the most recent one by comparing timestamps in the key.
3. **If the file is found:**
   - Count the number of lines (each line = one record).
   - Report to the user: "**{count} records generated so far.** The job is still running."
   - Show the S3 URI of the file.
   - Show the **last 5 records** from the file. If fewer than 5 records exist, show all of them. Say "Here are the last {min(5, count)} records:" (use the actual number available).
   - **Parsing records from `verified_samples.jsonl`:** Each line is a JSON object with a `content` field that is itself a JSON string. You must parse the inner JSON to extract the actual data. Example structure:

     ```json
     {"content": "{\"query\": \"...\", \"response\": \"...\", \"category\": \"...\"}", "verification_results": [...], "timestamp": "..."}
     ```

     Parse it as: `record = json.loads(line)` then `inner = json.loads(record["content"])` — display `inner["query"]`, `inner["response"]`, and `inner["category"]` (or whatever fields the inner JSON contains).
   - **Parsing records from `output_samples.jsonl`:** Each line is a clean JSON object (already unwrapped). It may use a `messages` format with `role`/`content` fields, or a flat format with `query`/`response` fields. Display whichever fields are present.
4. **If neither file exists yet:**
   - If this is the sample run (submitted from the spec), report: "The job is in progress (status: Executing) but no output samples have been written yet. The job is still building the generator: the service is testing the code and fixing what fails, which usually takes several minutes. Records appear once it starts generating them."
   - For a refinement or full run, which reuses the generator, report: "The job is in progress (status: Executing) but no output samples have been written yet. The generation is still in its early phase."
5. **If the job is in a terminal state** (Completed, Failed, Stopped):
   - Report the final status and follow `reading-synthetic-dataset-generation-job-logs.md`.

> **Note:** The `verified_samples.jsonl` file is streamed incrementally during generation — it grows as new records are produced and verified. The `output_samples.jsonl` is generated at the end from the verified samples (with verification metadata stripped). So during an in-progress job, only `verified_samples.jsonl` may be available.
