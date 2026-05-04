# Credential Security

Order of preference for authenticating Glue connections to data sources:

1. IAM database authentication (where supported)
2. AWS Secrets Manager (`SECRET_ID`)
3. Plaintext `USERNAME`/`PASSWORD` in connection properties (not recommended)

## Contents

- [IAM Database Authentication](#iam-database-authentication)
- [AWS Secrets Manager](#aws-secrets-manager)
- [Plaintext Credentials](#plaintext-credentials)
- [Rotation](#rotation)

## IAM Database Authentication

Supported sources:

- Aurora MySQL, Aurora PostgreSQL
- RDS MySQL, RDS PostgreSQL
- Amazon Redshift (via `GetClusterCredentials` / `GetCredentials`)

Benefits:

- No long-lived database passwords
- No secret to rotate
- Database access controlled by IAM policies
- Audit trail via CloudTrail

### RDS / Aurora Setup

1. Enable IAM DB auth on the cluster or instance:

   ```bash
   aws rds modify-db-instance \
     --db-instance-identifier <ID> \
     --enable-iam-database-authentication \
     --apply-immediately
   ```

2. Create a DB user that authenticates via IAM (MySQL):

   ```sql
   CREATE USER 'etl_user'@'%' IDENTIFIED WITH AWSAuthenticationPlugin AS 'RDS';
   GRANT SELECT ON app_db.* TO 'etl_user'@'%';
   ```

   PostgreSQL:

   ```sql
   CREATE USER etl_user;
   GRANT rds_iam TO etl_user;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO etl_user;
   ```

3. Grant the Glue job role the `rds-db:connect` action:

   ```json
   {
     "Effect": "Allow",
     "Action": "rds-db:connect",
     "Resource": "arn:aws:rds-db:<region>:<account>:dbuser:<resource-id>/etl_user"
   }
   ```

4. In the Glue connection, omit `SECRET_ID`, `USERNAME`, and `PASSWORD`. Glue generates an auth token on each connection.

### Redshift Setup

Grant the Glue role `redshift:GetClusterCredentials` (provisioned) or `redshift-serverless:GetCredentials` (serverless), scoped to the cluster/workgroup and DB user.

Configure the connection with the Redshift endpoint and a DB user. No password.

## AWS Secrets Manager

When IAM DB auth is not available (Oracle, SQL Server, Snowflake, BigQuery, self-managed), use Secrets Manager.

### Create Secret

JDBC sources:

```bash
aws secretsmanager create-secret \
  --name glue/<connection-name>/credentials \
  --secret-string '{"username":"etl_user","password":"<password>"}' \
  --region <region>
```

Snowflake (key names are Glue-specific):

```bash
aws secretsmanager create-secret \
  --name glue/snowflake-analytics/credentials \
  --secret-string '{"snowflakeUser":"ETL_USER","snowflakePassword":"<password>"}' \
  --region <region>
```

BigQuery (base64 of service account JSON, stored as the secret string directly):

```bash
base64 -i <sa>.json | tr -d '\n' | \
aws secretsmanager create-secret \
  --name glue/bigquery/<project-id>/credentials \
  --secret-string file:///dev/stdin \
  --region <region>
```

### Grant Glue Role Access

```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "arn:aws:secretsmanager:<region>:<account>:secret:glue/<connection-name>/credentials-*"
}
```

The `-*` suffix matches the random 6-character suffix Secrets Manager appends.

### Reference in Connection

```json
"ConnectionProperties": {
  "JDBC_CONNECTION_URL": "...",
  "SECRET_ID": "glue/<connection-name>/credentials"
}
```

Omit `USERNAME` and `PASSWORD`. Glue reads them from the secret at job runtime.

## Plaintext Credentials

Not recommended. Use only for:

- Disposable developer sandboxes
- Sources where Secrets Manager integration is not supported by the Glue connector

If you must, use `USERNAME` and `PASSWORD` in `ConnectionProperties`. The password is encrypted at rest in the Data Catalog but visible in `get-connection` responses to any principal with `glue:GetConnection`.

## Rotation

Secrets Manager rotation:

- Enable automatic rotation on the secret (7, 30, 60, or 90 days)
- Rotation Lambda updates the password in the source database and writes the new value to the secret
- Glue picks up the new value on the next job run; no connection update needed
- For Aurora/RDS, use the AWS-provided rotation template

IAM DB auth: no rotation -- tokens are minted per-connection and expire in 15 minutes.

Service account keys (BigQuery) / key-pairs (Snowflake): rotate by generating a new key at the source, updating the Secrets Manager value, and letting the old key expire or be deleted in the source.
