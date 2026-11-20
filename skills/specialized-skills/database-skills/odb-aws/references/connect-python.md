# Connect — Python (python-oracledb and SQLAlchemy)

Use **python-oracledb** (not `cx_Oracle`). Install with `pip install oracledb`. Thin mode is the default and preferred — no Oracle Client install needed. Thick mode is only required for Kerberos, Advanced Queuing, LDAP auth, or Sharding.

## python-oracledb — TCP

```python
import oracledb

conn = oracledb.connect(
    user="app_user",
    password=password,  # from Secrets Manager — never hardcode
    dsn="cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521/orclpdb1.sub1.vcn1.oraclevcn.com",
    tcp_connect_timeout=10,
    retry_count=3,
    retry_delay=1,
)
```

## python-oracledb — TCPS with Wallet

```python
# Never commit wallet files to source control
conn = oracledb.connect(
    user="app_user",
    password=password,
    dsn="cluster-abc-scan.sub1.vcn1.oraclevcn.com:2484/orclpdb1.sub1.vcn1.oraclevcn.com",
    config_dir="/opt/oracle/wallet",
    wallet_location="/opt/oracle/wallet",
    wallet_password=wallet_password,  # from Secrets Manager
    tcp_connect_timeout=10,
)
```

The wallet directory MUST contain `cwallet.sso`, `tnsnames.ora`, `sqlnet.ora` for thin mode to work.

## python-oracledb — TNS Alias from Wallet

```python
conn = oracledb.connect(
    user="app_user",
    password=password,
    dsn="mydb_high",  # alias from wallet's tnsnames.ora
    config_dir="/opt/oracle/wallet",
    wallet_location="/opt/oracle/wallet",
    wallet_password=wallet_password,
)
```

## Connection Pooling (long-running apps)

```python
pool = oracledb.create_pool(
    user="app_user",
    password=password,
    dsn="cluster-abc-scan.sub1.vcn1.oraclevcn.com:2484/orclpdb1.sub1.vcn1.oraclevcn.com",
    config_dir="/opt/oracle/wallet",
    wallet_location="/opt/oracle/wallet",
    wallet_password=wallet_password,
    min=2, max=10, increment=1,
    timeout=300,        # idle eviction (seconds)
    wait_timeout=5000,  # wait for available connection (ms)
    retry_count=3,
    retry_delay=1,
)

with pool.acquire() as conn:
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM DUAL")
        print(cursor.fetchone())
```

For **Lambda**, do not use connection pools — keep a single module-level connection and reuse it across warm invocations. See **compute-runtimes.md** (loaded reference).

## ConnectParams (advanced)

```python
params = oracledb.ConnectParams(
    host="cluster-abc-scan.sub1.vcn1.oraclevcn.com",
    port=2484,
    service_name="orclpdb1.sub1.vcn1.oraclevcn.com",
    protocol="tcps",
    ssl_server_dn_match=True,
    config_dir="/opt/oracle/wallet",
    wallet_location="/opt/oracle/wallet",
    wallet_password=wallet_password,
    retry_count=3,
    tcp_connect_timeout=10,
)
conn = oracledb.connect(user="app_user", password=password, params=params)
```

## Error Handling with Transient-Retry

```python
import oracledb

TRANSIENT_ERRORS = {12170, 12541, 3113, 3114, 3135, 25408}

def connect_with_retry():
    for attempt in range(3):
        try:
            return oracledb.connect(...)
        except oracledb.DatabaseError as e:
            code = e.args[0].code
            if code in TRANSIENT_ERRORS and attempt < 2:
                continue
            raise
```

## SQLAlchemy

Use `oracle+oracledb://`. **Never** `oracle://` (deprecated) or `oracle+cx_oracle://`.

### TCP

```python
from sqlalchemy import create_engine

engine = create_engine(
    "oracle+oracledb://app_user:password@cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521/?service_name=orclpdb1.sub1.vcn1.oraclevcn.com",
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=10,
)
```

### TCPS with Wallet

```python
engine = create_engine(
    "oracle+oracledb://app_user:password@",
    connect_args={
        "dsn": "cluster-abc-scan.sub1.vcn1.oraclevcn.com:2484/orclpdb1.sub1.vcn1.oraclevcn.com",
        "config_dir": "/opt/oracle/wallet",
        "wallet_location": "/opt/oracle/wallet",
        "wallet_password": wallet_password,
        "tcp_connect_timeout": 10,
    },
    pool_pre_ping=True,
    pool_recycle=1800,
)
```

`pool_pre_ping=True` is important for ODB@AWS because RAC can move services between nodes; stale pooled connections silently fail without it.

## Security

- Never log the wallet password or DB password to stdout, CloudWatch, or any persisted log. Lambda's default logger captures stdout.
- Pull credentials from Secrets Manager and use them in-memory only.
- Encrypt CloudWatch log groups with a customer-managed KMS key for defense in depth.

## Critical Rules

- Always use **service names** with SCAN hostnames — SIDs bypass SCAN load balancing.
- Use `oracledb.connect()`, not `cx_Oracle.connect()`.
- For TCPS, both `config_dir` and `wallet_location` are required.
- Never hardcode passwords — use Secrets Manager.
- Never commit wallet files to source control.
- For Lambda: thin mode, no pool, single module-level connection.
- For long-running apps: use a pool with `timeout` for idle eviction and set `pool_pre_ping=True` on SQLAlchemy.
