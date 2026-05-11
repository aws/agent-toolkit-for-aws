# S3 Security Audit Checklist

## Critical (fix immediately)

| Control | Check command | Pass condition |
|---|---|---|
| Block Public Access | `get-public-access-block` | All 4 flags true |
| No public bucket policy | `get-bucket-policy` | No `"Principal": "*"` or `"Principal": {"AWS": "*"}` with Allow |
| HTTPS enforced | `get-bucket-policy` | DenyInsecureTransport statement present |
| ACLs disabled | `get-bucket-ownership-controls` | `BucketOwnerEnforced` |

## High

| Control | Check command | Pass condition |
|---|---|---|
| Default encryption enabled | `get-bucket-encryption` | SSEAlgorithm set |
| S3 Bucket Keys enabled | `get-bucket-encryption` | `BucketKeyEnabled: true` |
| SSE-C blocked | `get-bucket-encryption` | `BlockedEncryptionTypes.EncryptionType` contains `SSE-C` |
| Not using AWS managed key | `get-bucket-encryption` | KMSMasterKeyID is NOT `aws/s3` |

## Medium

| Control | Check command | Pass condition |
|---|---|---|
| Versioning enabled | `get-bucket-versioning` | `Status: Enabled` |
| Logging enabled | `get-bucket-logging` + `cloudtrail get-event-selectors` | PASS if either S3 server access logging OR CloudTrail data events is configured; NOT CONFIGURED if neither |
| GuardDuty S3 Protection | `list-detectors` + `get-detector` | `S3_DATA_EVENTS` feature is `ENABLED` |

## Prerequisites

**IAM Access Analyzer**: The audit checklist requires an active analyzer. Before running `list-findings`, verify one exists:

```bash
aws accessanalyzer list-analyzers --region <region>
```

If the result is empty, report as a finding: "No IAM Access Analyzer configured in `<region>`". Creating the analyzer is a remediation action (Workflow C), not part of the audit.

## Low / Compliance

| Control | Check command | Pass condition |
|---|---|---|
| Object Lock (WORM) | `get-object-lock-configuration` | Enabled if compliance required |
| Cross-region replication | `get-bucket-replication` | Configured if DR required |
| Bucket in account namespace | bucket name | Ends with `-<account-id>-<region>-an` |

## AWS Config Rules

Core (always enable):

```
s3-bucket-public-read-prohibited
s3-bucket-ssl-requests-only
s3-bucket-versioning-enabled
s3-bucket-logging-enabled
```

Optional (enable if compliance requires):

```
s3-bucket-public-write-prohibited
s3-account-level-public-access-blocks
s3-bucket-replication-enabled
cloudtrail-s3-dataevents-enabled
```
