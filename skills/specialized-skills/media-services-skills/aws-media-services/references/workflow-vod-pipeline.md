# VOD Pipeline Workflow

File-based VOD workflows: transcode → package → deliver.

---

## Architecture Selection

```
IF simple VOD delivery (pre-rendered formats):
  → Basic: S3 → MediaConvert → S3 → CloudFront → Viewers
IF need multiple manifest formats (HLS+DASH) from single encode, or multi-DRM:
  → JIT packaging: S3 → MediaConvert → S3 → MediaPackage v2 VOD → CloudFront
IF content uploaded continuously (UGC, content library):
  → Automated: S3 event → Lambda → MediaConvert → S3 → CloudFront
```

---

## Resource Creation Sequence

```
DEPENDENCY GRAPH:
  Step 1 [CloudFront] ← create first so content is immediately servable
  Step 2 [S3 Buckets] (source + destination)
  Step 3 [IAM Role] (trusts mediaconvert.amazonaws.com)
  Step 4 [Job Template] (optional but recommended)
  Step 5 [MediaConvert Job or Lambda automation]
```

### Step 1: CloudFront Distribution

| | |
|---|---|
| **Preconditions** | S3 destination bucket (or create together) |
| **Outputs** | `distribution_domain_name` |
| **Needed by** | Viewers (immediate delivery once jobs complete) |

#### Decision: Origin type

```
IF basic VOD (no JIT packaging):
  → Origin = S3 destination bucket with OAC
IF using MediaPackage v2 VOD:
  → Origin = MediaPackage v2 endpoint URL
```

**Cache behavior:** Segments cached indefinitely (immutable). Manifests cached minutes to hours. Set `ViewerProtocolPolicy: redirect-to-https` on all cache behaviors. For custom domains, attach an ACM certificate (provisioned in us-east-1) with minimum protocol version `TLSv1.2_2021`.

### Step 2: S3 Buckets

| | |
|---|---|
| **Outputs** | `source_bucket`, `destination_bucket` |
| **Needed by** | Step 3 (IAM permissions), Step 5 (job source/destination) |

May be same bucket with different prefixes, or separate buckets. Enable versioning on source if overwriting is possible. Enable SSE-KMS encryption at rest on both buckets (SSE-S3 minimum if KMS is not available); SSE-KMS is RECOMMENDED for media content as it provides an audit trail via CloudTrail. Enable S3 Block Public Access on both buckets.

### Step 3: IAM Role

| | |
|---|---|
| **Preconditions** | S3 buckets exist |
| **Outputs** | `mediaconvert_role_arn` |

- Trust: `mediaconvert.amazonaws.com`
- Permissions: `s3:GetObject` (source), `s3:PutObject` (destination)
- If DRM/SPEKE: add key provider access

### Step 4: Job Template

| | |
|---|---|
| **Preconditions** | None (defines encoding settings) |
| **Outputs** | `job_template_name` |
| **Skip if** | One-off jobs with inline settings |

#### Decision: Output group type

```
IF delivering HLS only:
  → HLS_GROUP_SETTINGS
IF delivering DASH only:
  → DASH_ISO_GROUP_SETTINGS
IF delivering both HLS and DASH from single encode:
  → CMAF_GROUP_SETTINGS (produces both manifests)
IF producing downloadable files:
  → FILE_GROUP_SETTINGS (MP4, MXF, MOV)
```

### Step 5: Submit Job

| | |
|---|---|
| **Preconditions** | IAM role (Step 3), source file in S3, endpoint URL discovered |
| **Outputs** | `job_id`, output files in S3 |

**Actions:**

1. Use the direct regional MediaConvert endpoint: `https://mediaconvert.<region>.amazonaws.com`
2. Submit job with source path, destination path, IAM role, template/settings
3. For long-form or time-sensitive content, set `AccelerationSettings.Mode: PREFERRED` to enable accelerated transcoding (falls back to standard if content is ineligible)
4. Poll job status until COMPLETE

**Validation:** `get-job` shows `Status: COMPLETE`. Check `OutputGroupDetails` for actual output paths.

---

## Lambda Automation Pattern

| | |
|---|---|
| **Preconditions** | S3 buckets, IAM role, job template |
| **Trigger** | S3 ObjectCreated event on source bucket |

```
S3 source bucket (ObjectCreated)
  → Lambda function
    → MediaConvert CreateJob API
      → Output to S3 destination bucket
```

**Lambda IAM needs:** `mediaconvert:CreateJob`, `iam:PassRole`, `s3:GetObject`

### Decision: Avoiding recursive triggers

```
IF source and destination are same bucket:
  → Use prefix filters (e.g., input/ vs output/)
  → Or use suffix filters (.mp4, .mxf, .mov on source only)
IF source and destination are different buckets:
  → No recursion risk
```

**Idempotency:** Use `ClientRequestToken` in CreateJob (S3 events can deliver more than once).

---

## ABR Ladder for VOD

| Rung | Resolution | Codec | Bitrate | Notes |
|------|-----------|-------|---------|-------|
| 2160p | 3840×2160 | H.265 | 12-15 Mbps | Premium, HEVC devices |
| 1080p | 1920×1080 | H.264 | 5-8 Mbps | Broad compatibility |
| 720p | 1280×720 | H.264 | 2.5-4 Mbps | Mobile |
| 480p | 854×480 | H.264 | 1-2 Mbps | Low bandwidth |
| 360p | 640×360 | H.264 | 600-1000 Kbps | Minimum |

Use QVBR for best quality-per-bit. VOD bitrates can be lower than live (multi-pass encoding).

---

## Common Mistakes

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| Hardcoding MediaConvert endpoint URL | 404 or access denied in other accounts | Discover endpoint or use regional URL |
| Missing S3 permissions on role | Job fails immediately | Add s3:GetObject + s3:PutObject |
| Assuming output file paths | Files not found | Check OutputGroupDetails in job result |
| Same bucket without prefix filters | Lambda recursive trigger loop | Separate buckets or strict filters |
| No CloudFront for delivery | High latency, S3 throttling | Always use CloudFront for viewers |
| Segment duration mismatch across rungs | Player switching issues | Identical segment duration on all rungs |
