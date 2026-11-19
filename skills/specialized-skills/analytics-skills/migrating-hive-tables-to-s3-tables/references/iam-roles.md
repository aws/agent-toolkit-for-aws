# IAM roles

Two roles are involved: the **caller** (the identity that runs the CLI) and the **migration
service role** (the customer-provided role S3 Tables assumes to read the source and write the
destination). Sections 1, 3, and 4 are the migration service role's trust and permission policies.
Section 2 notes that Lake Formation
registered sources are not supported (confirm current support in the [migration guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-migrate.html)).

**Placeholders** (shared by the policies below): `${Partition}` (e.g. `aws`), `${Region}`,
`${AccountId}`, `${GlueDatabaseName}`, `${GlueTableName}`, `${SourceBucketName}`,
`${NormalizedSourcePrefix}`, `${TableBucketName}`, `${NamespaceName}`, `${TableName}`,
`${DestinationTableArn}`, `${ReportBucketName}`, `${NormalizedReportPrefix}`, `${SourceKmsKeyArn}`,
`${DestinationKmsKeyArn}`, `${ReportKmsKeyArn}`. The three KMS placeholders apply only when that
resource uses a customer managed key; with SSE-S3 end to end, omit the KMS statements.

## Discover before asking

Do not interrogate the customer about IAM plumbing. Take the account id and caller identity from
`sts get-caller-identity`, and search for an existing migration service role before proposing to
create one. A name substring like `igration`/`S3Tables` is only a coarse first pass, it also
matches DMS, MigrationHub, and partner roles, so confirm a candidate by its **trust policy**
(which must name `migration.s3tables.amazonaws.com` with the `aws:SourceAccount`/`aws:SourceArn`
conditions), not by its name. **If you find a role that appears suitable, do NOT use it silently: present it to the user (its ARN, trust principal, and how
it matches the requirements below) and ask them to confirm before using it**, because that role
lets S3 Tables read the source and write the destination on their behalf. If discovery finds no
suitable role, offer to create one. If a role exists but is missing a required principal or permission, report exactly what is missing and let the user fix it, rather than modifying their role. For non-role resources (report bucket, namespace),
resolve and state what you resolved so the user can correct you. See `references/preflight.md` §0.5.

## Caller policy (the identity running the CLI)

Scope `Resource` to the specific destination table-bucket ARN(s) the caller migrates into rather
than `*` (least privilege). Broaden only if the caller genuinely drives migrations across many
buckets.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3tables:StartTableMigration",
      "s3tables:SyncTableMigration",
      "s3tables:UpdateTableMigration",
      "s3tables:CompleteTableMigration",
      "s3tables:GetTableMigration",
      "s3tables:ListTableMigrations"
    ],
    "Resource": [
      "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}",
      "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}/*"
    ]
  }]
}
```

The preflight and plan-review steps also run regular `s3tables` reads the six migration actions do
not cover: `list-table-buckets` / `list-namespaces` / `create-namespace` (preflight §4) and
`get-table` (the Complete confirmation reads `managedByService`). Grant the caller these too, or
state that the caller is assumed to already hold them:

```json
{
  "Effect": "Allow",
  "Action": [
    "s3tables:ListNamespaces",
    "s3tables:GetNamespace",
    "s3tables:CreateNamespace",
    "s3tables:GetTable"
  ],
  "Resource": [
    "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}",
    "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}/*"
  ]
}
```

`s3tables:ListTableBuckets` is account-scoped (it takes `Resource: "*"`); grant it separately only
if the caller must discover table buckets rather than being handed the destination ARN.

Also add a second statement for `iam:PassRole` on the migration service role's ARN, conditioned on `iam:PassedToService` so the caller can only hand that role to the migration service:

```json
{
  "Effect": "Allow",
  "Action": "iam:PassRole",
  "Resource": "arn:${Partition}:iam::${AccountId}:role/<MIGRATION_ROLE>",
  "Condition": {
    "StringEquals": {
      "iam:PassedToService": "migration.s3tables.amazonaws.com"
    }
  }
}
```

During plan review your coding agent reads the compatibility report from the report bucket (`lifecycle.md`:
`aws s3 cp` the report object), so the caller also needs read access to it:

```json
{
  "Effect": "Allow",
  "Action": "s3:GetObject",
  "Resource": "arn:${Partition}:s3:::${ReportBucketName}/${NormalizedReportPrefix}*",
  "Condition": {
    "StringEquals": {
      "aws:ResourceAccount": "${AccountId}"
    }
  }
}
```

If the report bucket is SSE-KMS, the caller also needs `kms:Decrypt` on that bucket's key.

### Caller KMS for an SSE-KMS destination

When the destination table bucket uses SSE-KMS, the caller needs `kms:DescribeKey` and
`kms:GenerateDataKey` on the destination key, in addition to the role's KMS permissions in section 3. Pin the caller's grant
to the destination key ARN (`Resource` = the key ARN) with no `Condition` block; the key ARN is the
scoping. With SSE-S3 end to end, neither the caller nor the role needs any KMS permissions.

**Destination key policy (SSE-KMS).** Identity policies are not enough. When the destination table
bucket uses SSE-KMS, the customer-managed key's **key policy** (the resource policy on the key
itself) must also grant the S3 Tables maintenance service principal access, or every encrypted
`CreateTable` fails and planning never completes (the migration is what creates the destination
table). Add to the key policy:

```json
{
  "Sid": "AllowS3TablesMaintenance",
  "Effect": "Allow",
  "Principal": { "Service": "maintenance.s3tables.amazonaws.com" },
  "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
  "Resource": "*",
  "Condition": {
    "StringLike": {
      "kms:EncryptionContext:aws:s3:arn": "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}/*"
    }
  }
}
```

No `kms:*` grant on the role or caller substitutes for this; it is a resource-policy requirement on
the key. Read the current policy with `aws kms get-key-policy`, add this one statement, and show the
result to the user for approval. Never replace the whole key policy.

## 1. Trust policy

The trust policy is a single statement: the `migration.s3tables.amazonaws.com` service principal,
gated by `aws:SourceAccount` and `aws:SourceArn` conditions. It covers both planning and the
data-copy (`migrating`) phase.

- **Use `migration.s3tables.amazonaws.com`**, not `s3tables.amazonaws.com`.
- **Both condition keys go in ONE `StringEquals` block.** A second `StringEquals` block silently
  overwrites the first.
- **`aws:SourceArn` must match the destination table-bucket ARN exactly** (region, account, bucket
  name). These conditions are confused-deputy protection and the secure default.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowS3TablesMigrationService",
      "Effect": "Allow",
      "Principal": {
        "Service": "migration.s3tables.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "${AccountId}",
          "aws:SourceArn": "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}"
        }
      }
    }
  ]
}
```

## 2. Lake Formation (not supported)

Glue tables registered with Lake Formation are not supported (confirm current support in the [migration guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-migrate.html)); planning fails with
`metadata.glueLakeFormation`. The check and the stop rule are in `references/preflight.md` §6.

- Do NOT grant Lake Formation permissions, register or deregister locations, or change data lake
  settings to work around this. Those are governance decisions for the customer's data lake
  administrators.
- No Lake Formation grant is part of the migration role setup.

## 3. StartTableMigration policy

The migration service role's permission policy for `StartTableMigration`. Attach it to the migration service role (the role named in `roleARN`), scoped
to the exact source, destination, and report resources via the placeholders above. Notes:

- **`s3:GetObjectVersion` is required**: without it, planning fails on the source
  read with a plan-artifact read error even though `s3:GetObject` is present.
- Destination access is split into `CreateDestinationTable` (create-side actions, `s3tables:namespace`
  condition) and `MigrateDestinationTable` (copy-side actions, `s3tables:namespace` +
  `s3tables:tableName` conditions). Prefer these condition keys over a simpler ARN-only statement. With
  `StringEquals`, the `tableName` value must equal the per-run destination table exactly or
  planning/copy is denied (a common self-inflicted failure); to cover many runs without editing the
  policy each time, use `StringLike` with a scoped pattern (e.g. `s3tables:tableName` = `myprefix_*`).
- Report writes: the migration writes all three reports (table compatibility, object compatibility, object migration) under the single `migrationOutput.bucket` and the prefixes you set, under `<prefix>/<migration-id>/<report-type>/v1/...` (the folder layout can change, so read each object key from `migrationOutput.<report>.key` in `get-table-migration`; see `references/lifecycle.md`). Grant one `s3:PutObject` on the report prefix (`${NormalizedReportPrefix}*`), with an `aws:ResourceAccount` condition. This assumes all three reports share one prefix (as the Start and Sync examples do); if you configure distinct prefixes, grant one `Resource` per prefix. Omitting a prefix is legal and writes that report to the bucket root, which `${NormalizedReportPrefix}*` would not cover.
- `CreateDestinationTable` lists both the bucket ARN and `bucket/<name>/table/*`, scoped by the
  namespace condition.
- KMS: `kms:DescribeKey` validates the destination key; `kms:Decrypt`/`kms:GenerateDataKey` are
  scoped by `kms:ViaService` and `kms:EncryptionContext`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadSourceGlueTable",
      "Effect": "Allow",
      "Action": [
        "glue:GetTable",
        "glue:GetPartitions",
        "glue:GetColumnStatisticsForPartition"
      ],
      "Resource": [
        "arn:${Partition}:glue:${Region}:${AccountId}:catalog",
        "arn:${Partition}:glue:${Region}:${AccountId}:database/${GlueDatabaseName}",
        "arn:${Partition}:glue:${Region}:${AccountId}:table/${GlueDatabaseName}/${GlueTableName}"
      ]
    },
    {
      "Sid": "ReadSourceObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion"
      ],
      "Resource": "arn:${Partition}:s3:::${SourceBucketName}/${NormalizedSourcePrefix}*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceAccount": "${AccountId}"
        }
      }
    },
    {
      "Sid": "ListSourceBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:${Partition}:s3:::${SourceBucketName}",
      "Condition": {
        "StringEquals": {
          "aws:ResourceAccount": "${AccountId}"
        }
      }
    },
    {
      "Sid": "DecryptSourceObjects",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "${SourceKmsKeyArn}",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": ["s3.${Region}.amazonaws.com"]
        },
        "StringLike": {
          "kms:EncryptionContext:aws:s3:arn": [
            "arn:${Partition}:s3:::${SourceBucketName}",
            "arn:${Partition}:s3:::${SourceBucketName}/*"
          ]
        }
      }
    },
    {
      "Sid": "CreateDestinationTable",
      "Effect": "Allow",
      "Action": [
        "s3tables:CreateTable",
        "s3tables:TagResource",
        "s3tables:PutTableEncryption",
        "s3tables:PutTableStorageClass"
      ],
      "Resource": [
        "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}",
        "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}/table/*"
      ],
      "Condition": {
        "StringEquals": {
          "s3tables:namespace": "${NamespaceName}"
        }
      }
    },
    {
      "Sid": "MigrateDestinationTable",
      "Effect": "Allow",
      "Action": [
        "s3tables:GetTable",
        "s3tables:GetTableMetadataLocation",
        "s3tables:UpdateTableMetadataLocation",
        "s3tables:PutTableMaintenanceConfiguration",
        "s3tables:GetTableData",
        "s3tables:PutTableData"
      ],
      "Resource": "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}/table/*",
      "Condition": {
        "StringEquals": {
          "s3tables:namespace": "${NamespaceName}",
          "s3tables:tableName": "${TableName}"
        }
      }
    },
    {
      "Sid": "ValidateDestinationKmsKey",
      "Effect": "Allow",
      "Action": "kms:DescribeKey",
      "Resource": "${DestinationKmsKeyArn}",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": ["s3tables.${Region}.amazonaws.com"]
        }
      }
    },
    {
      "Sid": "UseDestinationKmsKey",
      "Effect": "Allow",
      "Action": [
        "kms:GenerateDataKey",
        "kms:Decrypt"
      ],
      "Resource": "${DestinationKmsKeyArn}",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": ["s3.${Region}.amazonaws.com"]
        },
        "StringLike": {
          "kms:EncryptionContext:aws:s3:arn": [
            "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}/table/*"
          ]
        }
      }
    },
    {
      "Sid": "WriteReports",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:${Partition}:s3:::${ReportBucketName}/${NormalizedReportPrefix}*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceAccount": "${AccountId}"
        }
      }
    },
    {
      "Sid": "EncryptReportObjects",
      "Effect": "Allow",
      "Action": "kms:GenerateDataKey",
      "Resource": "${ReportKmsKeyArn}",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": ["s3.${Region}.amazonaws.com"]
        },
        "StringLike": {
          "kms:EncryptionContext:aws:s3:arn": [
            "arn:${Partition}:s3:::${ReportBucketName}",
            "arn:${Partition}:s3:::${ReportBucketName}/*"
          ]
        }
      }
    }
  ]
}
```

## 4. SyncTableMigration policy

The permission policy for `SyncTableMigration` (applying source deltas to the already-migrated
table before cutover). It differs from the Start policy: it drops the create and table-config
actions (`CreateTable`, `PutTableEncryption`, `PutTableStorageClass`,
`PutTableMaintenanceConfiguration`) and scopes the destination to the table ARN
(`${DestinationTableArn}`) rather than the bucket. Both policies carry
`s3tables:GetTableMetadataLocation` and `glue:GetColumnStatisticsForPartition`; Amazon S3 Tables
needs both on the Start and the Sync paths. The Sync destination statement needs **no**
`s3tables:namespace` / `s3tables:tableName` condition: its `Resource` is already the exact
destination table ARN, which identifies the one table on its own. (The Start policy keeps the
conditions because its destination `Resource` is a `bucket/table/*` wildcard that the conditions
scope down. The Start `CreateDestinationTable` statement conditions on `s3tables:namespace` only,
not `s3tables:tableName`, because the table name is not yet in context at create time.) A role
used for the full lifecycle (Start then Sync) should carry both documents as two separate inline
policies; IAM evaluates the union automatically. Do not merge them into one document: they share
several `Sid`s (`ReadSourceGlueTable`, `ReadSourceObjects`, and others), which must be unique within
a single policy.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadSourceGlueTable",
      "Effect": "Allow",
      "Action": [
        "glue:GetTable",
        "glue:GetPartitions",
        "glue:GetColumnStatisticsForPartition"
      ],
      "Resource": [
        "arn:${Partition}:glue:${Region}:${AccountId}:catalog",
        "arn:${Partition}:glue:${Region}:${AccountId}:database/${GlueDatabaseName}",
        "arn:${Partition}:glue:${Region}:${AccountId}:table/${GlueDatabaseName}/${GlueTableName}"
      ]
    },
    {
      "Sid": "ReadSourceObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion"
      ],
      "Resource": "arn:${Partition}:s3:::${SourceBucketName}/${NormalizedSourcePrefix}*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceAccount": "${AccountId}"
        }
      }
    },
    {
      "Sid": "ListSourceBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:${Partition}:s3:::${SourceBucketName}",
      "Condition": {
        "StringEquals": {
          "aws:ResourceAccount": "${AccountId}"
        }
      }
    },
    {
      "Sid": "DecryptSourceObjects",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "${SourceKmsKeyArn}",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": ["s3.${Region}.amazonaws.com"]
        },
        "StringLike": {
          "kms:EncryptionContext:aws:s3:arn": [
            "arn:${Partition}:s3:::${SourceBucketName}",
            "arn:${Partition}:s3:::${SourceBucketName}/*"
          ]
        }
      }
    },
    {
      "Sid": "SyncDestinationTable",
      "Effect": "Allow",
      "Action": [
        "s3tables:GetTable",
        "s3tables:GetTableMetadataLocation",
        "s3tables:UpdateTableMetadataLocation",
        "s3tables:GetTableData",
        "s3tables:PutTableData"
      ],
      "Resource": "${DestinationTableArn}"
    },
    {
      "Sid": "UseDestinationKmsKey",
      "Effect": "Allow",
      "Action": [
        "kms:GenerateDataKey",
        "kms:Decrypt"
      ],
      "Resource": "${DestinationKmsKeyArn}",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": ["s3.${Region}.amazonaws.com"]
        },
        "StringLike": {
          "kms:EncryptionContext:aws:s3:arn": [
            "arn:${Partition}:s3tables:${Region}:${AccountId}:bucket/${TableBucketName}/table/*"
          ]
        }
      }
    },
    {
      "Sid": "WriteReports",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:${Partition}:s3:::${ReportBucketName}/${NormalizedReportPrefix}*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceAccount": "${AccountId}"
        }
      }
    },
    {
      "Sid": "EncryptReportObjects",
      "Effect": "Allow",
      "Action": "kms:GenerateDataKey",
      "Resource": "${ReportKmsKeyArn}",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": ["s3.${Region}.amazonaws.com"]
        },
        "StringLike": {
          "kms:EncryptionContext:aws:s3:arn": [
            "arn:${Partition}:s3:::${ReportBucketName}",
            "arn:${Partition}:s3:::${ReportBucketName}/*"
          ]
        }
      }
    }
  ]
}
```
