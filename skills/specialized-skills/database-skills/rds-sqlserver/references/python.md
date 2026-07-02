# Python — pymssql and pyodbc

Two Python drivers for RDS SQL Server. `pymssql` is simpler for pure SQL-auth workloads. `pyodbc` is required when you need Kerberos/Windows auth.

## pymssql

### Install

```bash
pip install pymssql
# Linux: FreeTDS is bundled in the wheel
# macOS: pip install pymssql (wheel available)
# Windows: pip install pymssql (wheel available)
```

### Minimal connection

```python
import pymssql, os, json, boto3

# Fetch creds from Secrets Manager
sm = boto3.client("secretsmanager", region_name="us-east-1")
creds = json.loads(sm.get_secret_value(SecretId="rds/sqlserver/app")["SecretString"])

conn = pymssql.connect(
    server=creds["host"],
    port="1433",                 # string, NOT int — common bug
    user=creds["username"],
    password=creds["password"],
    database=creds["dbname"],
    tds_version="7.3",           # 7.3 for SQL Server 2008-2019, 7.4 for 2022+
    encryption="require",        # not "request" — see below
    login_timeout=10,
)
```

### Critical pymssql gotchas

| Gotcha | Why it matters |
|---|---|
| `port="1433"` must be a string | Passing `port=1433` (int) silently fails with "connection refused" on some versions |
| Use `server=`, NOT `host=` | If both set, `host=` wins silently |
| `tds_version` is mandatory | Default negotiation can pick TDS 4.2 → fails on modern RDS |
| `encryption="require"` not `"request"` | `"request"` is opportunistic and can fall back to cleartext |
| No native connection pool | Use SQLAlchemy or DBUtils for pooling |
| No Kerberos support | Use pyodbc for AD auth |

### TLS with cert validation

Download RDS CA bundle and point pymssql at it:

```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

```python
conn = pymssql.connect(
    server="mydb.xxxx.us-east-1.rds.amazonaws.com",
    user="admin", password=pw, database="mydb",
    tds_version="7.3",
    encryption="require",
)
# pymssql on Linux uses the system CA bundle — put global-bundle.pem in
# /etc/ssl/certs/ or set SSL_CERT_FILE env var
```

For strict validation set `SSL_CERT_FILE=/path/to/global-bundle.pem` before connecting.

## pyodbc (needed for Kerberos)

### Install

```bash
# Linux — install Microsoft ODBC Driver 18
curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list | \
  sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt update && sudo ACCEPT_EULA=Y apt install -y msodbcsql18 unixodbc-dev
pip install pyodbc
```

### SQL auth

```python
import pyodbc
conn = pyodbc.connect(
    "Driver={ODBC Driver 18 for SQL Server};"
    "Server=mydb.xxxx.us-east-1.rds.amazonaws.com,1433;"
    "Database=mydb;"
    "Uid=admin;Pwd=secret;"
    "Encrypt=Yes;"
    "TrustServerCertificate=No;"
)
```

### Windows auth (Kerberos)

```python
import pyodbc
# Must be on a domain-joined host with valid TGT
# Connect to the CNAME, NOT the RDS endpoint
conn = pyodbc.connect(
    "Driver={ODBC Driver 18 for SQL Server};"
    "Server=database-1.corp.example.com,1433;"   # CNAME — Kerberos needs this
    "Database=mydb;"
    "Trusted_Connection=Yes;"
    "Encrypt=Yes;"
)
```

Verify Kerberos (not NTLM):

```sql
SELECT auth_scheme FROM sys.dm_exec_connections WHERE session_id = @@SPID
-- Expected: KERBEROS
```

## Connection pooling

### SQLAlchemy + pymssql (most common)

```python
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

engine = create_engine(
    "mssql+pymssql://admin:secret@mydb.xxxx.us-east-1.rds.amazonaws.com:1433/mydb"
    "?tds_version=7.3&encryption=require",
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
)
```

`pool_pre_ping=True` detects stale connections (e.g. after Multi-AZ failover). `pool_recycle=300` limits idle connection age.

## Lambda-specific (pymssql)

pymssql needs to be packaged for the Lambda Linux runtime. Either:

- Use a Lambda layer with the pymssql wheel for `manylinux2014_x86_64`
- Or build a container image based on `public.ecr.aws/lambda/python:3.12` + `pip install pymssql`

```python
# handler.py
import pymssql, json, boto3, os

sm = boto3.client("secretsmanager")
SECRET = json.loads(sm.get_secret_value(SecretId=os.environ["SECRET_ARN"])["SecretString"])

def handler(event, context):
    conn = pymssql.connect(
        server=SECRET["host"], port="1433",
        user=SECRET["username"], password=SECRET["password"],
        database=SECRET["dbname"],
        tds_version="7.3", encryption="require", login_timeout=5,
    )
    # use conn...
    conn.close()
```

For Lambda-level pooling, use RDS Proxy — see `rds-proxy.md`.

## Verify the connection

After any pymssql/pyodbc connection, run:

```sql
SELECT
  encrypt_option,                  -- TRUE if TLS
  auth_scheme,                     -- SQL, KERBEROS, or NTLM
  net_transport,
  client_net_address
FROM sys.dm_exec_connections
WHERE session_id = @@SPID
```
