# DMS Schema Conversion: Troubleshooting

## Table of Contents

- [Sync Exceptions](#sync-exceptions)
- [Async Exceptions](#async-exceptions)
- [Outdated AWS CLI Version](#outdated-aws-cli-version)
- [Verify Connectivity](#verify-connectivity)
- [DDL Processing Statistics (Offline Source)](#ddl-processing-statistics-offline-source)

---

## Sync Exceptions

These errors are returned immediately by the API call itself (`start-*`, `create-*`, `describe-*`). Surface the error to the customer and apply the fix before retrying.

| Error | Returned by | Likely cause | Fix |
|---|---|---|---|
| `AccessDeniedFault` | Any call | Caller lacks IAM permissions | Check the IAM role or user has the required DMS, S3, or Secrets Manager permissions |
| `ResourceNotFoundFault` | Any call | Referenced resource does not exist | Verify the migration project, instance profile, or data provider ARN/name is correct |
| `ResourceAlreadyExistsFault` | `create-*` calls | Resource with this name already exists | Retrieve the existing resource ARN with the appropriate `describe-*` call and reuse it |
| `ResourceQuotaExceededFault` | `create-*` / `start-*` calls | Account quota exceeded | Check Service Quotas console and request an increase for the relevant DMS resource |
| `KMSKeyNotAccessibleFault` | `start-*` calls | DMS cannot access the KMS key | Check the KMS key policy allows the DMS service principal for the region |
| `S3AccessDeniedFault` | `start-*` calls | DMS cannot access the S3 bucket | Verify the S3 role trust policy includes `dms.<region>.amazonaws.com` and the bucket policy does not block DMS |
| `S3ResourceNotFoundFault` | `start-*` calls | S3 bucket does not exist | Validate: `aws s3api head-bucket --bucket <bucket_name>` — offer to create if missing |
| `InvalidSubnet` | `create-replication-subnet-group` | Subnets not in at least 2 AZs or wrong VPC | Re-run Phase 4b of the setup wizard with corrected subnet IDs |
| `EntityAlreadyExists` | IAM `create-role` / `create-policy` | IAM resource already exists | Retrieve existing ARN: `aws iam get-role --role-name <name>` or `aws iam get-policy --policy-arn <arn>` |
| `ResourceExistsException` | `secretsmanager create-secret` | Secret already exists | Retrieve existing ARN: `aws secretsmanager describe-secret --secret-id <name>` |

---

## Async Exceptions

These errors do not fail the initial API call. The operation starts successfully but later transitions to a `failed` status, visible when checking the corresponding `describe-*` command (see [schema-conversion-operations.md](schema-conversion-operations.md) for the full list).

### Step 1 — Retrieve the error message

Use the corresponding `describe-*` command for the operation that failed (e.g., `describe-metadata-model-imports`, `describe-metadata-model-conversions`, `describe-metadata-model-assessments`, `describe-metadata-model-creations`, `describe-metadata-model-exports-as-script`). Extract `ErrorDetails.defaultErrorDetails.message` and match it to a group below.

---

### Group 1 — Database Credentials

**Messages:**

- `The credentials in the secret SOURCE are not valid. Check your username and password and try again.`
- `The credentials in the secret TARGET are not valid. Check your username and password and try again.`
- `The credentials in the secret are not valid. Check your username and password and try again.`

**Fix:**

1. Inform the customer:
   > "The credentials stored in your Secrets Manager secret are not valid. Please verify the username and password for your source/target database and update the secret value if needed."
2. Show the customer the secret name to check (retrieve from the migration project, do NOT display the secret value):

   ```
   aws dms describe-migration-projects \
     --filters Name=migration-project-identifier,Values=<migration_project_identifier>
   ```

3. Once the customer confirms the secret has been updated, proceed to Step 2.

---

### Group 2 — Database Connectivity

**Messages:**

- `Could not connect to the source database. Please verify your network configuration, server name, and port, then try again.`
- `Could not connect to the target database. Please verify your network configuration, server name, and port, then try again.`
- `Could not connect to the database. Please verify your network configuration, server name, and port, then try again.`
- `The DB connection has not been established. For details, see the log.`

**Fix:**

1. Verify the server name and port in the data provider:

   ```
   aws dms describe-data-providers \
     --filters Name=data-provider-identifier,Values=<project_name>-source
   ```

2. Check security group egress rules — see [Verify Connectivity](#verify-connectivity).
3. Confirm the database is running and reachable from the configured subnets.

---

### Group 3 — Database Not Found

**Messages:**

- `The specified source database name was not found. Check your database name and try again.`
- `The specified target database name was not found. Check your database name and try again.`

**Fix:**

1. Retrieve the database name currently configured in the data provider and show it to the customer:

   ```
   aws dms describe-data-providers \
     --filters Name=data-provider-identifier,Values=<project_name>-source
   ```

   Extract and display the `DatabaseName` from the settings so the customer can see what name DMS is using.
2. Ask the customer to confirm whether this database name exists on the server.
3. If the name is wrong, update the data provider:

   ```
   aws dms modify-data-provider \
     --data-provider-identifier <arn> \
     --engine <engine> \
     --settings '{...corrected settings...}'
   ```

---

### Group 4 — S3 Access and Configuration

**Messages:**

- `Access to the project storage is denied. Check you bucket, S3 role and try again.`
- `Access to project storage denied. Check your S3 bucket, role, region, and try again.`
- `Unable to access to S3. Check the name of your S3 bucket, the IAM role to access your bucket, and the Region, then try again.`
- `S3 settings are not valid. Check the name of your S3 bucket, the IAM role to access your bucket, and the Region, then try again.`
- `The export metadata error happened during publishing to S3. Check your bucket, S3 role and restart operation.`
- `The read metadata error happened during reading from S3.`
- `S3 bucket url with the selected project was not found. Please close and open your project again.`

**Fix:**

1. Retrieve the S3 bucket path and S3 role ARN from the migration project and display them to the customer:

   ```
   aws dms describe-migration-projects \
     --filters Name=migration-project-identifier,Values=<migration_project_identifier>
   ```

   Extract and show `SchemaConversionApplicationAttributes.S3BucketPath` and `SchemaConversionApplicationAttributes.S3BucketRoleArn`.

2. Validate the bucket exists:

   ```
   aws s3api head-bucket --bucket <bucket_name>
   ```

3. Verify the S3 role trust policy includes `dms.<region>.amazonaws.com`:

   ```
   aws iam get-role --role-name <s3_role_name>
   ```

4. Verify the S3 role has the required permissions (`s3:PutObject`, `s3:GetObject`, `s3:GetObjectVersion`, `s3:GetBucketVersioning`, `s3:GetBucketLocation`, `s3:ListBucket`) on the bucket:

   ```
   aws iam list-attached-role-policies --role-name <s3_role_name>
   ```

5. Check the bucket policy does not explicitly deny DMS access:

   ```
   aws s3api get-bucket-policy --bucket <bucket_name>
   ```

---

### Group 5 — S3 Versioning

**Message:**

- `S3 bucket versioning is disabled. Please turn it on and try again.`

**Fix:**

1. Retrieve the S3 bucket name from the migration project:

   ```
   aws dms describe-migration-projects \
     --filters Name=migration-project-identifier,Values=<migration_project_identifier>
   ```

   Extract `SchemaConversionApplicationAttributes.S3BucketPath` and display it to the customer.

2. Enable versioning on the bucket:

   ```
   aws s3api put-bucket-versioning \
     --bucket <bucket_name> \
     --versioning-configuration Status=Enabled
   ```

---

### Group 6 — Secrets Manager Access

**Messages:**

- `The Secret does not exist. Please check the Secret name, IAM secret role, and region.`
- `DMS Schema Conversion is unable to process the request at this time because data from Secrets Manager is not available. Please check your network configuration and try again.`
- `Unable to access AWS Secrets Manager: <details>`

**Fix:**

1. Retrieve the secret ARNs and secrets role ARN from the migration project and display them to the customer:

   ```
   aws dms describe-migration-projects \
     --filters Name=migration-project-identifier,Values=<migration_project_identifier>
   ```

   Extract and show `SecretsManagerSecretId` from both source and target data provider descriptors, and `SecretsManagerAccessRoleArn`.

2. Verify each secret exists:

   ```
   aws secretsmanager describe-secret --secret-id <secret_arn>
   ```

3. Verify the secrets role trust policy includes `dms.<region>.amazonaws.com`:

   ```
   aws iam get-role --role-name <secrets_role_name>
   ```

4. Verify the secrets role has `secretsmanager:GetSecretValue` and `secretsmanager:DescribeSecret` on the secret ARNs:

   ```
   aws iam list-attached-role-policies --role-name <secrets_role_name>
   ```

5. If the message mentions network unavailability, check that the DMS subnets have outbound access to Secrets Manager (via NAT gateway or VPC endpoint).

---

### Group 7 — SSL / Certificate

**Message:**

- `Verify that your database has SSL configured and doesn't provide self-signed certificates (certificates that were signed by an unknown Certificate Authority). By default, SSL isn't configured in your database.`

**Fix:**

1. If SSL is not required, update the data provider to set `SslMode: none`.
2. If SSL is required, ensure the database uses a certificate signed by a trusted CA.
3. Update the data provider settings accordingly.

---

### Group 8 — Insufficient Database Privileges

**Message:**

- `The specified account does not have sufficient privileges for working with one or several objects.`

**Fix:**

1. The database user does not have enough permissions to perform the requested operation.
2. Guide the customer to set up the correct database credentials based on:
   - For source databases: [source data provider prerequisites](https://docs.aws.amazon.com/dms/latest/userguide/data-providers-source.html)
   - For target databases: [target data provider prerequisites](https://docs.aws.amazon.com/dms/latest/userguide/data-providers-target.html)
3. Update the secret if the user needs to be changed.

---

### Group 9 — Project / Configuration Issues

**Messages:**

- `DMS Schema Conversion cannot open the project because it is already opened.`
- `The wrong project was selected for opening. Please verify the project identifier and try again.`
- `The Schema Conversion Application Attributes were not provided. Please add the required data to the Migration Project and try again.`
- `The project settings format is not valid. Please modify the field value and try again.`
- `DMS Schema Conversion cannot create the project because it already exists.`
- `DMS Schema Conversion cannot process your request because the Conversion does not exist.`

**Fix:**

1. Verify the migration project identifier is correct:

   ```
   aws dms describe-migration-projects \
     --filters Name=migration-project-identifier,Values=<migration_project_identifier>
   ```

2. Check that `SchemaConversionApplicationAttributes` (S3 bucket path and S3 role ARN) are set on the project.
3. If the project configuration is incomplete or corrupted, recreate it via the setup wizard with the same or a new project name.

---

### Group 10 — Capacity / Transient Errors

**Messages:**

- `Capacity is unavailable at this time. Please try again later.`
- `DMS Schema Conversion cannot process your request. Please try again later or contact the support team.`
- `The service is currently experiencing high load. Please try your request again later.`

**Fix:**
These are transient errors. Wait 5 minutes and retry the operation.

---

#### Step 2 — Retry

After the customer confirms the fix, ask:
> "Would you like to retry the operation? (yes / no)"

If yes, return to the appropriate action. If no, return to the [Actions Menu](../SKILL.md#actions-menu).

---

## Outdated AWS CLI Version

If a DMS command fails with `Invalid choice` or `argument operation: Invalid choice`, the installed AWS CLI version does not support the operation.

**Fix:**

1. Check the current version:

   ```
   aws --version
   ```

2. Update to the latest version following the [AWS CLI installation guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).
3. Verify the operation is now available:

   ```
   aws dms <operation> help
   ```

---

## Verify Connectivity

If the error indicates a network or connectivity issue, read [DMS SC network configuration](https://docs.aws.amazon.com/dms/latest/userguide/instance-profiles-network.html) and guide the customer through setting up the correct network configuration.

---

## DDL Processing Statistics (Offline Source)

For offline source projects, DMS produces processing statistics in the project's S3 bucket after import, conversion, or assessment operations. **Check these statistics proactively** when results contain fewer objects than expected or when an operation completes without errors but the metadata tree appears incomplete.

Retrieve the statistics:

```
aws s3 cp s3://<project-bucket>/<migration-project-folder>/ddl-statistics/ds.csv ./ds.csv
```

Review the output for entries indicating processing failures. Common causes: malformed DDL, unsupported statements (DML/DROP), encoding issues, or non-compliant file structure. Refer to Phase 3d of the setup wizard for DDL structure requirements.
