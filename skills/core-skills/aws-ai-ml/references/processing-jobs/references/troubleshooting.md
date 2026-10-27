# Processing Job Troubleshooting

## Collect evidence

1. Run `aws sagemaker describe-processing-job --processing-job-name <name> --region <region>`.
2. Record `ProcessingJobStatus`, `ExitMessage`, `FailureReason`, `AppSpecification`, `ProcessingResources`, `ProcessingInputs`, `ProcessingOutputConfig`, and `RoleArn`.
3. Find streams with `aws logs describe-log-streams --log-group-name /aws/sagemaker/ProcessingJobs --log-stream-name-prefix <name> --region <region>`.
4. Read only matching streams with `aws logs filter-log-events --log-group-name /aws/sagemaker/ProcessingJobs --log-stream-names <stream...> --region <region>`.
5. For a stuck job, compare creation/start/end timestamps and inspect compute metrics for the exact window.

Do not stop/relaunch the job, edit IAM, or change query/container configuration without explicit approval.

## Classification

| Signature/evidence | Category | Likely fix |
|---|---|---|
| `ResourceLimitExceeded` or quota below requested count | Quota | Request quota or choose approved compute |
| `AccessDenied`, `iam:PassRole`, S3/ECR/KMS/Athena/Redshift denial | IAM | Correct role trust and add only missing resource-scoped permissions |
| Missing S3 object, invalid `/opt/ml/processing/` path, schema/format error | Data | Correct input/output mapping and script expectations |
| exit 137, OOM, disk-full, memory/disk saturation | Resources | Increase verified memory/volume or reduce working set/partitions |
| Image pull, entrypoint, module, dependency, nonzero exit | Container/user code | Verify image, command, script, source directory, and requirements |
| Athena/Redshift query syntax, workgroup, cluster, or result-location failure | Dataset definition | Validate SQL, metadata, result S3 URI, and warehouse permissions |
| Spark executor lost, serialization, shuffle/disk failure | Spark | Validate dependency packaging, partitions, executor memory, and instance count |
| Long `InProgress` with no logs/metrics movement | Stuck | Check process liveness and data volume; stop only after user approval |

## Response format

Return:

- job name/ARN, status, and timeline
- failure signature and root-cause category
- evidence from `ExitMessage`/`FailureReason`, decisive logs, and metrics if checked
- concrete repair steps ordered by lowest risk
- an explicit **Not checked** section

If evidence is insufficient, state the next read-only check instead of guessing.
