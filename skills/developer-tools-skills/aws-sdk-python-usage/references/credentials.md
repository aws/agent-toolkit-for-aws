# Credentials Reference

## Default Credential Chain

boto3 resolves credentials in this order:

1. Explicit `aws_access_key_id`/`aws_secret_access_key` passed to `Session()` or `client()`
2. `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` env vars
3. Assume role (`role_arn` + `source_profile` / `credential_source` in the active profile)
4. Web identity token (EKS IRSA via `AWS_WEB_IDENTITY_TOKEN_FILE` / `AWS_ROLE_ARN`, or `web_identity_token_file` in profile)
5. SSO credentials (IAM Identity Center profile; token from `aws sso login`)
6. `~/.aws/credentials` file (default or named profile)
7. Login session (`login_session` in profile; requires `botocore[crt]`)
8. Credential process (`credential_process` in profile)
9. `~/.aws/config` file (static keys in profile)
10. Legacy boto config (`BOTO_CONFIG`, `~/.boto`, `/etc/boto.cfg`)
11. Container credentials — ECS task role / EKS Pod Identity (`AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` or `AWS_CONTAINER_CREDENTIALS_FULL_URI`)
12. EC2 instance metadata (IMDS)

In most cases, let the default chain handle credential resolution rather than hardcoding credentials.

## Sessions

```python
import boto3

# Default session -- shared across boto3.client()/boto3.resource() calls
client = boto3.client("s3")

# Explicit session -- isolated credentials and config
session = boto3.Session(
    profile_name="dev-account",
    region_name="us-west-2",
)
client = session.client("s3")

# Multiple sessions for cross-account access
dev = boto3.Session(profile_name="dev")
prod = boto3.Session(profile_name="prod")
dev_s3 = dev.client("s3")
prod_s3 = prod.client("s3")
```

Use explicit sessions when you need multiple credential sets or profiles in the same process.

## Named Profiles

```python
# Use a profile from ~/.aws/credentials or ~/.aws/config
session = boto3.Session(profile_name="my-profile")
client = session.client("s3")

# Or set via environment variable
# AWS_PROFILE=my-profile
```

## Assume Role (STS)

```python
import boto3

# Assume a role and create a client with the temporary credentials
sts = boto3.client("sts")
response = sts.assume_role(
    RoleArn="arn:aws:iam::123456789012:role/MyRole",
    RoleSessionName="my-session",
    DurationSeconds=3600,
)
creds = response["Credentials"]

client = boto3.client(
    "s3",
    aws_access_key_id=creds["AccessKeyId"],
    aws_secret_access_key=creds["SecretAccessKey"],
    aws_session_token=creds["SessionToken"],
)
```

For automatic credential refresh when the assumed role expires, use a profile with `role_arn` in `~/.aws/config`:

```ini
[profile cross-account]
role_arn = arn:aws:iam::123456789012:role/MyRole
source_profile = default
```

```python
session = boto3.Session(profile_name="cross-account")
client = session.client("s3")  # credentials auto-refresh
```

## Chained Role Assumption

```ini
# ~/.aws/config
[profile role-a]
role_arn = arn:aws:iam::111111111111:role/RoleA
source_profile = default

[profile role-b]
role_arn = arn:aws:iam::222222222222:role/RoleB
source_profile = role-a
```

## Environment Variables

| Variable | Purpose |
|---|---|
| `AWS_ACCESS_KEY_ID` | Access key |
| `AWS_SECRET_ACCESS_KEY` | Secret key |
| `AWS_SESSION_TOKEN` | Session token (temporary creds) |
| `AWS_DEFAULT_REGION` | Default region |
| `AWS_PROFILE` | Named profile |
| `AWS_ROLE_ARN` | Role ARN for web identity |
| `AWS_WEB_IDENTITY_TOKEN_FILE` | Path to OIDC token file (EKS) |
| `AWS_CONFIG_FILE` | Override config file path |
| `AWS_SHARED_CREDENTIALS_FILE` | Override credentials file path |

## STS Get Caller Identity

Useful for verifying which credentials are in use:

```python
sts = boto3.client("sts")
identity = sts.get_caller_identity()
print(identity["Account"], identity["Arn"])
```
