---
name: troubleshoot-spark-job
description: >-
  Diagnoses and fixes failed or slow Apache Spark workloads on AWS Glue, EMR on
  EC2, EMR Serverless, and EMR on EKS with the analyze_spark_workload MCP tool,
  which provides deeper analysis than the AWS job run APIs alone. Analyzes job
  failures, performance issues, and error stack traces, and generates code fix
  recommendations as a follow-up only when the diagnosis identifies a code-level
  fix. Applies to requests such as: spark job failed, glue job error, emr job
  failing, emr on eks job failed, spark out of memory, spark job slow, debug
  spark, spark exception, analyze spark failure, spark job stuck, spark job
  troubleshoot. Not intended for upgrading Spark versions, creating new Spark
  jobs, or general cluster management.
metadata:
  version: "1"
  argument-hint: "[platform] [job-name-or-cluster-id] [run-id-or-step-id]"
---

Diagnose failed or degraded Apache Spark workloads on AWS Glue, Amazon EMR on EC2, Amazon EMR Serverless, and Amazon EMR on EKS. Uses the SageMaker Unified Studio Spark Troubleshooting MCP server (`spark-troubleshooting`) to analyze job logs, error traces, and resource metrics. Optionally follows up with the Spark Code Recommendation MCP server (`spark-code-recommendation`) to generate targeted code fixes - but only when the diagnosis identifies a code-level fix.

## Reference Documentation

- [error-handling.md](references/error-handling.md) -- MCP connection issues and setup guidance

## Workflow

**Constraints:**

- You MUST call `analyze_spark_workload` (the `spark-troubleshooting` server) FIRST as the primary diagnostic tool for every troubleshooting request. It provides deeper analysis than AWS job run APIs alone.
- You MUST NOT call `spark_code_recommendation` (the `spark-code-recommendation` server) standalone or as a first step. It is a FOLLOW-UP ONLY: invoke it after `analyze_spark_workload` has produced a diagnosis AND that diagnosis identifies a code-level fix AND the user wants code changes. Calling it without a prior `analyze_spark_workload` diagnosis produces lower-quality root cause analysis.
- You MUST NOT call `spark_code_recommendation` when the diagnosed fix is configuration-only (e.g. memory, partition, or resource tuning with no code change). Present the configuration fix directly.
- Prefer `analyze_spark_workload`'s natural chaining into code recommendation over an explicit standalone `spark_code_recommendation` call.
- Do NOT call `aws emr describe-step`, `aws emr describe-cluster`, `aws glue get-job-run`, `aws emr-serverless get-job-run`, `aws emr-containers describe-job-run`, or any AWS CLI command as a diagnostic step. The MCP tool provides all the information needed.
- Do NOT call `aws emr list-clusters`, `aws emr-serverless list-applications`, `aws emr-containers list-virtual-clusters`, `aws glue list-jobs`, `aws glue get-job-runs`, or any discovery/list API. Ask the user for identifiers instead.

### Phase 0: Gather Job Identifiers

If the user has not provided the required identifiers, ask for them. Do NOT call AWS CLI, AWS APIs, list-jobs, get-job-runs, or any other discovery API to look them up. Do NOT attempt to list recent failures or guess which job failed. Ask the user directly and wait for a response.

A bare "EMR" (without EC2, cluster, or step; Serverless or application; or EKS or virtual cluster) is NOT platform-distinguishing. If the user says only "EMR" (for example, "my EMR job failed"), ask whether it is EMR on EC2, EMR Serverless, or EMR on EKS before requesting identifiers; the three platforms use different identifiers.

**AWS Glue:** job name and job run ID (hex string starting with `jr_`)

**EMR on EC2:** cluster ID (format: `j-<alphanumeric>`, typically 12-13 chars after the prefix) and step ID (alphanumeric string starting with `s-`)

**EMR Serverless:** application ID (16-char alphanumeric string starting with `00`) and job run ID (16-char alphanumeric string starting with `00`)

**EMR on EKS:** virtual cluster ID (lowercase alphanumeric string, e.g. `6aycqwm1iryxff42j7sf1qix0`) and job run ID (alphanumeric string, e.g. `00000003891im4vqfb6`)

**Optional for all platforms:** additional context (error message, user observations, what was tried)

### Phase 1: Analyze the Workload

Call `analyze_spark_workload` with the platform type and parameters. Valid `platform_type` values: `GLUE`, `EMR_EC2`, `EMR_SERVERLESS`, `EMR_EKS`. For `EMR_EKS`, pass `virtual_cluster_id` and `job_run_id`. The tool returns:

- Root cause classification (OOM, data skew, misconfiguration, code error, resource contention, etc.)
- Contributing factors with evidence from logs
- Severity assessment
- Recommended fixes with priority ordering

### Phase 2: Present Diagnosis

Present the analysis results clearly:

- **Root cause**: Primary failure reason with supporting evidence
- **Contributing factors**: Secondary issues that worsened the failure
- **Recommended fixes**: Ordered by impact. Give specific values for configuration fixes. For code-level fixes, do not hand-write the code change here; generate it in Phase 3.

If - and only if - the diagnosis includes code-level issues: when the user has already asked for code fixes, go directly to Phase 3 and call `spark_code_recommendation` for the code change rather than writing it by hand; ask first only if the user has not requested code changes. If the fix is configuration-only, do not offer code recommendations; present the config change directly.

### Phase 3: Generate Code Recommendations (Follow-up, conditional)

Enter this phase ONLY when Phase 1/2 diagnosed a code-level issue (inefficient transformations, missing optimizations, incorrect API usage) AND the user wants fixes. Call `spark_code_recommendation` with the analysis results and the user's Spark code. The tool generates specific code changes with before/after examples, configuration tuning recommendations, and explanations. Present the tool's code changes; do not substitute a hand-written fix for them.

Note: `analyze_spark_workload` may automatically invoke `spark_code_recommendation` when the error category is eligible - prefer this natural chaining over calling `spark_code_recommendation` independently, which produces lower-quality root cause analysis. If `analyze_spark_workload` did not return code recommendations, call `spark_code_recommendation` after the diagnosis. Never call `spark_code_recommendation` as the entry point to this skill.

### Phase 4: Summarize and Next Steps

Provide a concise summary: root cause confirmed, fixes applied or recommended, configuration changes needed, whether a re-run is expected to succeed, and any follow-up monitoring recommended.

## Argument Routing

- **No args**: Ask for platform and job identifiers interactively
- **Platform specified**: e.g. `glue my-etl-job jr_abc123` -- Skip platform prompts

## Supported Platforms

| Platform | Trigger Keywords |
|----------|-----------------|
| AWS Glue | glue job, glue etl, glue spark |
| EMR on EC2 | emr ec2, emr ec2 cluster, emr step |
| EMR Serverless | emr serverless, emr-s, serverless spark |
| EMR on EKS | emr on eks, emr eks, emr virtual cluster, emr-containers |

If the user's input matches a trigger keyword in the table above, use that platform directly. The fallback (asking which platform) applies only when no platform-distinguishing keyword is present. A bare "EMR" does not match any EMR row, so ask. If the input matches trigger keywords for more than one platform, ask the user which platform the failing job runs on before proceeding.

## Gotchas

- Connecting to the MCP server and listing its tools requires no `sagemaker-unified-studio-mcp` action permissions. Permissions are required only when tools make downstream API calls (e.g., accessing Glue, EMR, or CloudWatch logs). If a tool call fails with AccessDeniedException, see the [IAM setup docs](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/spark-troubleshooting-agent-iam-setup.html).
- EMR Serverless IDs are 16-character alphanumeric strings starting with `00` (e.g., `00g5gmlv894uvl09`), not the same format as EMR-EC2 step IDs.
- EMR on EKS jobs are identified by virtual cluster ID + job run ID (the `emr-containers` API), not by an EKS cluster name. Do NOT call `aws emr-containers list-job-runs` or `kubectl` to find them; ask the user.
- The `--read-timeout 180` is intentional -- log fetching and analysis for large jobs can take several minutes.
- Code recommendations require the original Spark source code to be accessible. If the code is not local, provide the relevant file paths or paste the problematic sections.
- Do not enable "trust" for all tool calls by default. Review each tool execution before approving.

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| MCP server failed to load | Configuration or credentials issue | Verify JSON syntax and AWS credentials |
| AccessDeniedException on log fetch | IAM role lacks required permissions | Add the missing permissions (see [IAM setup docs](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/spark-troubleshooting-agent-iam-setup.html)) |
| Job run not found | Incorrect job name, run ID, or wrong region | Verify identifiers with the user |
| Analysis returns no root cause | Logs unavailable or job succeeded | Confirm the job is in a failed state; check log retention settings |

**Detailed guidance:** [references/error-handling.md](references/error-handling.md)
