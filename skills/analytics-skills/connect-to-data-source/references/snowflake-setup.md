# Snowflake Connection Setup

AWS Glue native Snowflake connection (type `SNOWFLAKE`, not `JDBC`). Required for Glue for Spark ETL jobs reading from or writing to Snowflake.

## Contents

- [Connection Type](#connection-type)
- [Authentication Modes](#authentication-modes)
- [Connection JSON Template](#connection-json-template)
- [PrivateLink](#privatelink)
- [Further Reading](#further-reading)

## Connection Type

Use `ConnectionType: SNOWFLAKE`. Do NOT use a JDBC connection configured with the Snowflake JDBC URL -- that path is for Glue crawlers only and cannot be used by Glue for Spark ETL jobs. The two credential types are stored separately in the Data Catalog.

## Authentication Modes

| Mode | When to use | Secret contents |
|---|---|---|
| User + password | Quick start, non-production | `username`, `password` |
| Key-pair (RSA) | Production, long-lived workloads | `username`, `private_key` (PEM, base64) |
| OAuth 2.0 | Enterprise SSO, credential-free for end users | `client_id`, `client_secret`, `refresh_token`, token URL |

OAuth 2.0 for Glue Snowflake connections was released April 2026. For current Snowflake OAuth setup steps, cite [Snowflake's OAuth docs](https://docs.snowflake.com/en/user-guide/oauth-intro) rather than repeating them.

## Connection JSON Template

Password-based:

```json
{
  "Name": "snowflake-analytics",
  "ConnectionType": "SNOWFLAKE",
  "ConnectionProperties": {
    "HOST": "<account>.<region>.snowflakecomputing.com",
    "WAREHOUSE": "<warehouse-name>",
    "ROLE": "<role-name>",
    "DATABASE": "<default-database>",
    "SECRET_ID": "<secrets-manager-arn>"
  }
}
```

The secret must contain `snowflakeUser` and `snowflakePassword` keys per Glue's Snowflake connection convention.

Account identifier formats vary -- see [Snowflake account identifier docs](https://docs.snowflake.com/en/user-guide/admin-account-identifier) for the correct form for your region/cloud.

Private sources add `PhysicalConnectionRequirements` as in [jdbc-setup.md](jdbc-setup.md#connection-json-template).

## PrivateLink

Snowflake accounts configured for AWS PrivateLink have a different hostname pattern. Glue jobs use the privatelink hostname directly. Configure the Glue connection's security group to allow outbound to the privatelink endpoint. See [Snowflake PrivateLink docs](https://docs.snowflake.com/en/user-guide/admin-security-privatelink).

## Further Reading

- [AWS Glue: Creating a Snowflake connection](https://docs.aws.amazon.com/glue/latest/ug/creating-snowflake-connection.html)
- [AWS Glue: Snowflake connections (programming)](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-connect-snowflake-home.html)
