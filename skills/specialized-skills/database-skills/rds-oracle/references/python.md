# RDS for Oracle — Python

Python driver: **python-oracledb** (≥ 6.0). `cx_Oracle` is legacy — migrate.

```bash
pip install oracledb
```

## Thin mode — default, no Oracle Client needed

```python
import oracledb

conn = oracledb.connect(
    user="dbadmin",
    password="<from-secrets-manager>",  # fetch at runtime; see connection-auth.md section (b) — via AWS Secrets Manager
    dsn="mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL"
)
cursor = conn.cursor()
cursor.execute("SELECT sysdate FROM dual")
print(cursor.fetchone())
conn.close()
```

## DSN formats

```python
# Easy Connect
dsn = "hostname:1521/ORCL"

# Full descriptor (for CMAN, failover, TCPS)
dsn = """(DESCRIPTION=
  (ADDRESS=(PROTOCOL=TCP)(HOST=hostname)(PORT=1521))
  (CONNECT_DATA=(SERVICE_NAME=ORCL)))"""

# Route 53 CNAME
dsn = "mydb.example.internal:1521/ORCL"
```

## Thick mode (only when needed)

Required for Kerberos with in-memory tickets, LDAP, Oracle Wallet-based Advanced Security. Requires Oracle Instant Client.

```bash
# Amazon Linux 2 (RHEL 7-based)
sudo yum install -y oracle-instantclient-release-el7
sudo yum install -y oracle-instantclient-basic
```

```python
import oracledb

# Call once, before any connection
oracledb.init_oracle_client(lib_dir="/usr/lib/oracle/21/client64/lib")

conn = oracledb.connect(
    user="dbadmin", password="<from-secrets-manager>",
    dsn="mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL"
)
```

If `lib_dir` is omitted, it searches standard OS library paths.

## Connection pooling (production)

```python
import oracledb

pool = oracledb.create_pool(
    user="dbadmin", password="<from-secrets-manager>",
    dsn="mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL",
    min=2, max=10, increment=1,
    getmode=oracledb.POOL_GETMODE_WAIT,
    timeout=60,         # idle connections closed after 60s
    wait_timeout=5000,  # ms to wait for a connection from pool
)

with pool.acquire() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT sysdate FROM dual")
    print(cursor.fetchone())

# On shutdown
pool.close()
```

### Pool with Secrets Manager

```python
import json, boto3, oracledb

def create_pool_from_secret(secret_name: str, region: str = "us-east-1"):
    client = boto3.client("secretsmanager", region_name=region)
    secret = json.loads(client.get_secret_value(SecretId=secret_name)["SecretString"])
    return oracledb.create_pool(
        user=secret["username"], password=secret["password"],
        dsn=f'{secret["host"]}:{secret["port"]}/{secret["dbname"]}',
        min=2, max=10, increment=1,
    )
```

### Pool sizing

| Workload | min | max | increment |
|---|---|---|---|
| Low | 1 | 5 | 1 |
| Medium | 2 | 10 | 1 |
| High | 5 | 20 | 2 |

`max` ≤ RDS `max_connections` / number of app instances.

## SQLAlchemy

URL scheme is `oracle+oracledb://` (not `oracle://` or `oracle+cx_oracle://`):

```python
from sqlalchemy import create_engine

engine = create_engine(
    "oracle+oracledb://dbadmin:<from-secrets-manager>@mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/?service_name=ORCL",
    pool_size=10, max_overflow=5, pool_pre_ping=True,
)
```

## Lambda pattern

Pool at module scope, outside the handler, so it's reused across warm invocations:

```python
import json, os, boto3, oracledb

_secret = json.loads(
    boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["SECRET_NAME"]
    )["SecretString"]
)
_pool = oracledb.create_pool(
    user=_secret["username"], password=_secret["password"],
    dsn=f'{_secret["host"]}:{_secret["port"]}/{_secret["dbname"]}',
    min=1, max=2,     # small pool per Lambda instance
)

def handler(event, context):
    with _pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute("SELECT sysdate FROM dual")
        return {"result": str(cur.fetchone())}
```

Total Oracle connections = concurrent Lambda instances × `max` (typically 1-2 per instance). Keep `max` small to avoid exhausting RDS `max_connections`.

## SSL/TLS thin mode

```python
import oracledb

dsn = """(DESCRIPTION=
  (ADDRESS=(PROTOCOL=TCPS)(HOST=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com)(PORT=2484))
  (CONNECT_DATA=(SERVICE_NAME=ORCL))
  (SECURITY=(SSL_SERVER_DN_MATCH=YES)))"""

conn = oracledb.connect(user="dbadmin", password="<from-secrets-manager>", dsn=dsn,
                        ssl_server_cert_dn="CN=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com")
```

For certificate validation, point at a wallet with the RDS CA imported (or use `config_dir` with `ewallet.pem`).

## Error handling

```python
import oracledb

try:
    conn = oracledb.connect(user="dbadmin", password="<from-secrets-manager>", dsn="...")
except oracledb.DatabaseError as e:
    error, = e.args
    if error.code == 12170:
        print("TNS connect timeout — check security groups and network path")
    elif error.code == 1017:
        print("Invalid username/password — check Secrets Manager rotation")
    elif error.code == 12541:
        print("No listener — check RDS endpoint and port")
    elif error.code == 12514:
        print("Service name mismatch — check SERVICE_NAME in your DSN")
    else:
        print(f"Oracle error {error.code}: {error.message}")
```

## Common driver errors (thick mode only)

- **`DPI-1047`** — "Cannot locate a 64-bit Oracle Client library" → switch to thin mode (default in 6.0+) or fix `lib_dir`.
- **`DPY-6005`** — thin mode incompatibility → some operation isn't supported in thin mode; switch to thick for just that code path if truly needed, otherwise find the thin-compatible equivalent.
