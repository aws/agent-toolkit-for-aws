# LMI Migration Patterns

Before/after code examples for migrating to multi-concurrency.

## Node.js

### Global State

```javascript
// BEFORE (race condition)
let requestCount = 0;
exports.handler = async (event) => {
  requestCount++;
  return { count: requestCount };
};

// AFTER (request-isolated)
const { AsyncLocalStorage } = require('node:async_hooks');
const als = new AsyncLocalStorage();
exports.handler = async (event, context) => {
  return als.run({ id: context.awsRequestId }, async () => {
    return await processEvent(event);
  });
};
```

### File I/O

```javascript
// BEFORE (shared path)
fs.writeFileSync('/tmp/output.json', JSON.stringify(data));

// AFTER (request-unique path)
const path = `/tmp/output-${context.awsRequestId}.json`;
try { fs.writeFileSync(path, JSON.stringify(data)); }
finally { fs.unlinkSync(path); }
```

### Database

```javascript
// BEFORE (per-invocation connection)
exports.handler = async (event) => {
  const conn = await mysql.createConnection({/*...*/});
  const [rows] = await conn.execute('SELECT ...');
  await conn.end();
};

// AFTER (shared pool)
// For production: retrieve credentials from AWS Secrets Manager
// const { SecretsManagerClient, GetSecretValueCommand } = require('@aws-sdk/client-secrets-manager');
const pool = mysql.createPool({ connectionLimit: 10, /*...*/ });
exports.handler = async (event) => {
  const [rows] = await pool.execute('SELECT ...');
  return rows;
};
```

## Python

Python on LMI uses **process-based isolation**. Each concurrent invocation runs in its own process with independent memory. Global state is NOT shared, so no locking is needed. The main migration concerns are `/tmp` conflicts, memory sizing, and connection pooling.

### Global State (No Changes Needed)

```python
# This is SAFE on LMI — each process has its own copy of cache
cache = {}
def handler(event, context):
    cache[event['key']] = compute(event)
    return cache[event['key']]

# Module-level clients are also safe (isolated per process)
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
```

### File I/O (Change Required — `/tmp` is shared across processes)

```python
# BEFORE (conflict — all processes share /tmp)
with open('/tmp/data.json', 'w') as f: json.dump(event, f)

# AFTER (request-unique path)
path = f'/tmp/data-{context.aws_request_id}.json'
try:
    with open(path, 'w') as f: json.dump(event, f)
finally:
    os.unlink(path)
```

### Database (Change Required — each process needs pooled connections)

```python
# BEFORE (per-invocation connection — exhausts limits at concurrency)
def handler(event, context):
    conn = psycopg2.connect(host='...')

# AFTER (pool per process — initialized at module level)
from psycopg2 import pool
db_pool = pool.SimpleConnectionPool(1, 3, host=os.environ['DB_HOST'])
def handler(event, context):
    conn = db_pool.getconn()
    try: return query(conn, event)
    finally: db_pool.putconn(conn)
# Note: total connections = pool_size × concurrency (e.g., 3 × 16 = 48)

# For production: retrieve credentials from Secrets Manager, not environment variables
# import boto3
# secret = boto3.client("secretsmanager").get_secret_value(SecretId="my-db-creds")
```

### Memory Sizing

```python
# A function using 200 MB per process with default concurrency of 16:
# Total memory ≈ 200 MB × 16 = 3.2 GB
# Use 4:1 or 8:1 memory-to-vCPU ratio to accommodate
# Monitor MemoryUtilization metric and adjust as needed
```

## Java

### Global State

```java
// BEFORE (race condition)
private static Map<String, String> cache = new HashMap<>();

// AFTER (thread-safe)
private static final ConcurrentHashMap<String, String> cache = new ConcurrentHashMap<>();
// Use cache.computeIfAbsent(key, k -> compute(k));
```

### Database

```java
// BEFORE (per-invocation)
Connection conn = DriverManager.getConnection("jdbc:...");

// AFTER (HikariCP pool, static init)
private static final HikariDataSource ds;
static {
    HikariConfig c = new HikariConfig();
    // For production: retrieve credentials from Secrets Manager, not env vars
    c.setJdbcUrl(System.getenv("DB_URL"));
    c.setMaximumPoolSize(10);
    ds = new HikariDataSource(c);
}
// Use: try (Connection conn = ds.getConnection()) { ... }
```
