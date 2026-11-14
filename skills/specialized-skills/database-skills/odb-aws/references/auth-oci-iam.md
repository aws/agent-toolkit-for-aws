# Auth — OCI IAM (SSO Token and Password Verifier)

ODB@AWS does not support AWS IAM database authentication. Two OCI-native IAM paths are available: **SSO tokens** (modern, passwordless) and **password verifier** (OCI IAM credentials → database). Both require an OCI Identity Domain configured with the database.

## When to Pick Which

| Signal | Method |
|---|---|
| No DB password wanted anywhere | SSO token |
| CI/CD pipelines on OCI-connected infrastructure | SSO token |
| Users already in OCI IAM, simpler rollout | Password verifier |
| AWS-native workload (Lambda, ECS) with no OCI SDK | Password auth + Secrets Manager (see **auth-wallet-tcps.md** (loaded reference)) |

## SSO Token Flow

1. Client authenticates to OCI IAM (API key, instance principal, or session token).
2. Client requests a **db-token** from OCI IAM.
3. Client presents the db-token to Oracle.
4. Oracle validates via OIDC federation with OCI IAM.
5. OCI IAM user is mapped to a database schema.

### Python example

```python
import oracledb
import oci

# Authenticate to OCI
config = oci.config.from_file()  # or instance principal
identity_client = oci.identity.IdentityClient(config)

token_response = identity_client.generate_scoped_access_token(
    generate_scoped_access_token_details=oci.identity.models.GenerateScopedAccessTokenDetails(
        scope="urn:oracle:db::id::*",
        public_key=public_key_pem,
    )
)
db_token = token_response.data.token

conn = oracledb.connect(
    user="/",                    # forces token auth
    dsn="mydb_high",
    config_dir="/opt/oracle/wallet",
    wallet_location="/opt/oracle/wallet",
    access_token=db_token,
)
```

### Java example

```java
IdentityClient identityClient = IdentityClient.builder().build(provider);
GenerateScopedAccessTokenResponse tokenResponse =
    identityClient.generateScopedAccessToken(request);
String dbToken = tokenResponse.getToken();

Properties props = new Properties();
props.setProperty("oracle.jdbc.tokenAuthentication", "OCI_TOKEN");
props.setProperty("oracle.jdbc.accessToken", dbToken);

Connection conn = DriverManager.getConnection(url, props);
```

### Token lifecycle

- Tokens typically live ~1 hour.
- Refresh proactively at ~80% of lifetime.
- For connection pools: refresh on new-connection acquisition.
- For Lambda: fetch a fresh token each invocation (no cross-invocation caching).
- Clock skew > 5 minutes → ORA-28276 (see **troubleshooting-errors.md** (loaded reference)).

## Password Verifier Flow

### Setup

1. Create the OCI IAM user in the identity domain.
2. Map the OCI IAM user to a database schema:

```sql
-- Connect as ADMIN or SYS
CREATE USER oci_user IDENTIFIED GLOBALLY AS 'OCI_IAM_USER_OCID';
GRANT CREATE SESSION TO oci_user;
GRANT SELECT ON schema.table_name TO oci_user;
```

3. Connect using the OCI IAM username + password:

```python
conn = oracledb.connect(
    user="oci_iam_username",
    password=oci_iam_password,   # OCI IAM password, not DB password
    dsn="mydb_high",
    config_dir="/opt/oracle/wallet",
    wallet_location="/opt/oracle/wallet",
    wallet_password=wallet_password,
)
```

## User-to-Schema Mapping

### Individual user

```sql
CREATE USER oci_user IDENTIFIED GLOBALLY AS 'OCI_IAM_USER_OCID';
GRANT CREATE SESSION TO oci_user;
GRANT app_role TO oci_user;
```

### Group (shared schema)

```sql
CREATE USER shared_app_user IDENTIFIED GLOBALLY AS 'OCI_IAM_GROUP_OCID';
GRANT CREATE SESSION TO shared_app_user;
GRANT app_role TO shared_app_user;
```

### Verify

```sql
SELECT username, authentication_type, external_name
FROM dba_users
WHERE authentication_type = 'GLOBAL';
```

## Critical Rules

- The OCID in `IDENTIFIED GLOBALLY AS` MUST exactly match the OCI IAM user or group OCID.
- TCPS (wallet) is REQUIRED for both token and password-verifier flows.
- Group membership changes in OCI IAM take effect on next login; no database restart needed.
- For AWS-native workloads without the OCI SDK, DB password + Secrets Manager (see **auth-wallet-tcps.md** (loaded reference)) is simpler than bundling OCI SDKs.
- There is NO AWS IAM database authentication for ODB@AWS.

## Common Errors

See **troubleshooting-errors.md** (loaded reference) for ORA-28276 (token/time/domain issues) and ORA-01017 under OCI IAM (verifier re-sync).
