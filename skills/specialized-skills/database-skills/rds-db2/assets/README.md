# Assets

Static data files and policy templates that the `rds-db2` skill references.

| File | Used by | Purpose |
|---|---|---|
| `rds-db2-minimal-iam-policy.json` | `references/minimum-iam.md` | Least-privilege IAM permissions policy for provisioning and managing RDS for Db2 |
| `rds-db2-trust-policy.json` | `references/minimum-iam.md` | Role trust policy with `ExternalId` + confused-deputy (`aws:SourceArn`/`aws:SourceAccount`) conditions |
| `selection-knowledge-input.json` | `aws-database-selection` parent skill | Machine-readable RDS-for-Db2 selection facts |
| `selection-knowledge-input.md` | `aws-database-selection` parent skill | Human-readable companion to the selection-knowledge JSON |

> Run-time outputs (per-application migration plans, upgrade plans, validation reports) are written
> to a local `artifacts/<app-name>/` directory in the working directory at run time. That is a
> run-time location, not part of this shipped skill package.
