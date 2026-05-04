# BigQuery Connection Setup

AWS Glue native BigQuery connection (type `BIGQUERY`). Authentication is via a GCP service account; credentials flow through AWS Secrets Manager.

## Contents

- [Prerequisites](#prerequisites)
- [Service Account Setup](#service-account-setup)
- [Secrets Manager Storage](#secrets-manager-storage)
- [Connection JSON Template](#connection-json-template)
- [Further Reading](#further-reading)

## Prerequisites

- GCP project with BigQuery enabled
- Service account in that project with BigQuery access (typically `roles/bigquery.dataViewer` plus `roles/bigquery.jobUser` for running jobs)
- Service account JSON key file from GCP
- AWS Secrets Manager secret in the same region as the Glue job

## Service Account Setup

Service account and key generation happen in GCP, not AWS. For current steps see [GCP service account docs](https://cloud.google.com/iam/docs/service-accounts-create) and [BigQuery access control](https://cloud.google.com/bigquery/docs/access-control).

Minimum GCP IAM roles for read-only ingestion:

- `roles/bigquery.dataViewer` on the target dataset
- `roles/bigquery.jobUser` on the project (to run queries)

For cross-project reads, grant both roles in each source project.

## Secrets Manager Storage

Base64-encode the service account JSON and store in Secrets Manager. The Glue BigQuery connection expects the secret value to be the base64 string directly, not a JSON wrapper.

```bash
base64 -i <service-account>.json | tr -d '\n' > sa.b64
aws secretsmanager create-secret \
  --name glue/bigquery/<project-id>/credentials \
  --secret-string file://sa.b64 \
  --region <region>
rm sa.b64
```

Rotate by creating a new key in GCP and updating the secret value. Glue picks up the new value on next job run.

## Connection JSON Template

```json
{
  "Name": "bigquery-<project-id>",
  "ConnectionType": "BIGQUERY",
  "ConnectionProperties": {
    "SECRET_ID": "glue/bigquery/<project-id>/credentials"
  }
}
```

Glue's BigQuery connection talks to Google APIs over the internet. No `PhysicalConnectionRequirements` needed unless the Glue job itself must run in a specific VPC for other reasons (e.g., also reading from a private RDS). In that case, ensure the subnet has NAT gateway egress so Glue can reach `bigquery.googleapis.com`.

## Further Reading

- [AWS Glue: Creating a BigQuery connection](https://docs.aws.amazon.com/glue/latest/dg/creating-bigquery-connection.html)
- [AWS Glue: Creating a BigQuery source node](https://docs.aws.amazon.com/glue/latest/dg/creating-bigquery-source-node.html)
- [GCP service account keys](https://cloud.google.com/iam/docs/keys-create-delete)
