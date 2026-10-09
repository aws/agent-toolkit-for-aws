# Training Job Troubleshooting

## Collect evidence

1. Run `aws sagemaker describe-training-job --training-job-name <name> --region <region>`. If submission itself failed and no job exists, preserve the `CreateTrainingJob` exception, request ID, timestamp, region, and redacted request parameters; do not start with log lookup.
2. For an existing job, record `TrainingJobStatus`, `SecondaryStatus`, `FailureReason`, `SecondaryStatusTransitions`, `ResourceConfig`, `AlgorithmSpecification`, `InputDataConfig`, and `RoleArn`.
3. Find the job's streams with `aws logs describe-log-streams --log-group-name /aws/sagemaker/TrainingJobs --log-stream-name-prefix <name> --region <region>`.
4. Read only matching streams with `aws logs filter-log-events --log-group-name /aws/sagemaker/TrainingJobs --log-stream-names <stream...> --region <region>`.
5. For performance/OOM analysis, query the `/aws/sagemaker/TrainingJobs` namespace for the exact job start/end window and `Host=<job-name>/algo-<index>` dimension. Run the following read-only command for each relevant host and metric (`CPUUtilization`, `MemoryUtilization`, `DiskUtilization`, and, on GPU instances, `GPUUtilization` and `GPUMemoryUtilization`):

   ```bash
   aws cloudwatch get-metric-statistics \
     --namespace /aws/sagemaker/TrainingJobs \
     --metric-name CPUUtilization \
     --dimensions Name=Host,Value=<job-name>/algo-1 \
     --start-time <job-start-utc> --end-time <job-end-utc> \
     --period 60 --statistics Average Maximum \
     --region <region>
   ```

   Replace the metric name and `algo-<index>` for each container. Correlate peaks with status transitions and decisive log timestamps; do not infer utilization from logs alone.

Do not relaunch, stop, change quota, or modify IAM without explicit approval.

## Classification

| Signature/evidence | Category | Likely fix |
|---|---|---|
| `CreateTrainingJob` `ValidationException` or local SDK validation before an ARN exists | Submission/config | Correct the rejected field, image/algorithm, channel, or name; preserve request ID and do not search nonexistent job logs |
| `ResourceLimitExceeded`, quota value below requested count | Quota | Request quota or choose approved compute; do not silently downsize |
| `AccessDenied`, `iam:PassRole`, S3/ECR/KMS denial | IAM | Add the missing least-privilege action/resource or correct the execution role trust |
| Missing object, wrong channel/path, malformed records | Data | Correct S3 URI/channel/schema; keep data and job in the same region |
| `CUDA out of memory`, exit 137, memory metric saturation | OOM | Reduce batch/model footprint or use verified larger/distributed compute |
| `AlgorithmError`, image entrypoint/module/dependency failure, or nonzero user-code exit | Container/algorithm | Use `FailureReason` plus the first decisive container traceback; fix code/image/dependencies before resubmission |
| NaN/Inf loss or divergence without infrastructure errors | Training config | Validate data, learning rate, precision, and recipe overrides |
| Long `Pending`/capacity message with quota available | Capacity | Use an approved training plan/reservation or another verified instance type/region |
| Internal service error with healthy user code | Service | Capture request/job ARN and timestamps; retry only when documented as transient |

## Escalation

If no customer-actionable cause is found—or an internal service error remains after user configuration, IAM, quota, data, and container evidence are ruled out—draft, but do not submit, an AWS Support case containing:

- account and Region
- job name/ARN, or failed `CreateTrainingJob` request ID
- UTC failure window and status transitions
- sanitized `FailureReason`, `AlgorithmError`, and decisive log/metric evidence
- SageMaker Python SDK version and image URI/digest
- every read-only check performed plus an explicit **Not checked** list
- requested help: identify the internal failure and confirm whether retry is safe

Ask the user to review the draft before submission.

## Response format

Return:

- job name/ARN (or create-request ID when no job exists), status, and relevant timeline
- failure signature and root-cause category
- evidence from `FailureReason`, one or two decisive log lines, and metrics if checked
- concrete repair steps ordered by lowest risk
- an explicit **Not checked** section
- a support-case draft only when the escalation condition above is met

If evidence is insufficient, say so and identify the next read-only check rather than guessing.
