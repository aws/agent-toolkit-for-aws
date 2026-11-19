# Troubleshooting: MediaConvert

Per-service troubleshooting guidance for MediaConvert job issues.

---

## Symptom Router

```
IF job fails at submission (before processing):
  → See "Job Submission Failures" below
IF job fails during processing:
  → See "Job Processing Failures" below
IF job completes but output wrong/missing:
  → See "Output File Issues" below
IF quality issues (blocky, artifacts):
  → See "Quality Issues" below
IF jobs queuing too long:
  → See "Job Queue and Throughput" below
IF Lambda automation failing:
  → See "Lambda Automation Issues" below
```

---

## Job Submission Failures

| | |
|---|---|
| **Symptom** | Job fails immediately at submission |
| **Check first** | Endpoint URL, IAM role, input codec support |

**Decision tree:**

```
IF 404 or access denied:
  → Wrong endpoint URL. Use the direct regional endpoint: https://mediaconvert.<region>.amazonaws.com
IF "Unable to assume role":
  → Role MUST trust mediaconvert.amazonaws.com
  → Submitter needs iam:PassRole permission
IF "Unsupported input":
  → Check codec/container compatibility docs
  → Common unsupported: ProRes in MKV, VP9, AV1 input
IF accelerated transcoding fails:
  → Use PREFERRED (falls back to standard) instead of ENABLED
```

---

## Job Processing Failures

| | |
|---|---|
| **Symptom** | Job starts but status becomes FAILED |

**Decision tree:**

```
IF S3 access denied:
  → Role needs s3:GetObject (source) + s3:PutObject (destination)
  → If KMS-encrypted: role needs kms:Decrypt
IF codec incompatibility:
  → File extension may not match actual codec. Verify with mediainfo/ffprobe.
IF DRM/encryption error:
  → Verify SPEKE endpoint URL accessible from MediaConvert service
  → Verify IAM role has key provider permissions
```

---

## Output File Issues

| | |
|---|---|
| **Symptom** | Job COMPLETE but files not where expected |

MediaConvert appends output group name + name modifier to destination path. MUST check `OutputGroupDetails` in job result for actual paths.

```bash
aws mediaconvert get-job --endpoint-url <endpoint> --id <job-id> --query "Job.OutputGroupDetails"
```

---

## Quality Issues

| | |
|---|---|
| **Symptom** | Output blocky, artifacts, combing |

**Decision tree:**

```
IF blocky/low quality:
  → Bitrate too low for resolution. Use QVBR for best quality-per-bit.
  → Use High profile for H.264 on ALL rungs (not Baseline/Main)
IF combing artifacts:
  → Source is interlaced, deinterlacer not enabled
  → Enable deinterlacer: Adaptive (telecine), Interpolation (sports), FrameFormer (VOD)
IF segment switching issues:
  → All ABR rungs MUST use same segment duration
```

---

## Job Queue and Throughput

**Decision tree:**

```
IF jobs queuing too long:
  → Check account concurrency limits in Service Quotas
  → Use SQS to throttle submission rate for burst uploads
IF predictable high volume:
  → Reserved queue (lower per-minute cost in exchange for upfront commitment; guaranteed capacity)
  → Configure queue hopping: reserved first, fallback to on-demand
IF urgent processing needed:
  → Accelerated transcoding (premium per-minute rate; faster completion)
  → Use PREFERRED mode for automatic fallback
```

---

## Accelerated Transcoding Fallback

| | |
|---|---|
| **Symptom** | Job completes with `accelerationStatus: NOT_ACCELERATED` |

The API does NOT provide a structured reason for fallback. Agents MUST NOT guess the cause.

**Troubleshooting steps:**

```
1. Check job.messages.warning for service-provided hints
2. If no explanation in messages, present common causes to user:
   → Input too short (< ~1 min)
   → Input missing embedded timecodes
   → Unsupported input codec or container
   → Incompatible job settings (e.g., frame capture outputs)
   → Input resolution too low
3. Ask user to verify against their specific input/settings
```

---

## Lambda Automation Issues

| | |
|---|---|
| **Symptom** | S3 event-triggered Lambda fails to submit jobs |

**Decision tree:**

```
IF recursive trigger loop:
  → Source and destination are same bucket without prefix filters
  → Fix: separate buckets OR strict prefix/suffix filters
IF Lambda timeout:
  → Lambda should ONLY submit the job (not process the file)
IF duplicate jobs:
  → S3 events can deliver more than once
  → Use ClientRequestToken for idempotent submissions
```
