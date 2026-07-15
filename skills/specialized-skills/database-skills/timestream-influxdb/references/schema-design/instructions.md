# Schema & Data Modeling

## When to Activate

User asks about tag vs field decisions, cardinality management, table/measurement design, retention policies, or InfluxDB 3 best practices for data modeling.

## Workflow

### 1. Identify the Engine

Schema design differs significantly between V2 and V3. Confirm the engine before advising.

### 2. Core Concepts

**Line protocol** (both engines):

```
measurement,tag1=val1,tag2=val2 field1=1.0,field2="text" timestamp
```

**Tags** = indexed, low-cardinality metadata (device_id, region, sensor_type)
**Fields** = values not indexed by default (temperature, cpu_usage, response_time)
**Timestamp** = nanosecond precision, always present

### 3. Tag vs Field Decision

Ask: "Will I filter or GROUP BY this column frequently?"

- **Yes** → Tag (indexed, fast lookups)
- **No** → Field (not indexed by default, stores the actual measurements)

**Cardinality rule:** The product of all unique tag value combinations = series cardinality.

- V2: Keep below 1M series per bucket. Performance degrades sharply above this.
- V3: No hard limit. High cardinality is handled natively, but tag design still affects query performance and storage efficiency.

### 4. InfluxDB 3 Schema Best Practices

**Table and column limits:**

- `maxTables` default: **4,000** per database. Recommended: keep under ~500 for optimal query performance.
- `maxColumnsPerTable` default: **200**. Each unique tag key or field key counts as a column.
- Both are configurable via parameter groups. Exceeding these limits will reject writes.

**Table design:**

- One table per logical measurement type (e.g., `cpu`, `memory`, `http_requests`)
- Avoid mega-tables with hundreds of fields — split by domain
- Use meaningful table names (they map to SQL table names)

**Partition templates:**

- Default: partition by day. Good for most workloads.
- High-volume: partition by hour if writing >1M points/day per table
- Configure via: `--partition-template tag:region,tag:host,time:%Y-%m-%d`

**Deduplication and uniqueness:**

- InfluxDB 3 deduplicates on: all tags + timestamp (the "primary key")
- Two points with identical tags and timestamp → last write wins
- To preserve both: add a distinguishing tag or use different timestamps

**Field indexing (V3):**

- Fields are NOT indexed by default
- For fields used in WHERE clauses, create a field index:

  ```sql
  CREATE INDEX idx_status ON http_requests (status);
  ```

**Retention:**

- V2: Set retention policy per bucket
- V3: Set retention period per database

### 5. Common Anti-Patterns

| Anti-Pattern | Problem | Fix |
|-------------|---------|-----|
| Encoding data in tag values (e.g., `sensor_123_temp`) | Explodes cardinality | Split into `sensor_id=123` tag + `temp` field |
| Using high-cardinality values as tags (UUIDs, timestamps) | V2: crashes. V3: bloated indexes | Move to fields; use field indexes if needed |
| Single mega-table for all data | Poor query performance, hard to manage | Split by measurement domain |
| Missing timestamp precision | Accidental deduplication | Use nanosecond precision for high-frequency data |
| Storing constants as fields | Wastes storage on every point | Move to tags (indexed once per series) |

### Canonical tag examples for HTTP / API logs

For typical HTTP request log schemas, use these as default **tags** (low-to-moderate cardinality, commonly filtered/grouped):

- `method` (~10 values: GET, POST, etc.)
- `status_code` (~20 values: 200, 404, 500, etc.)
- `endpoint` (the request path — typically <500 unique paths in a well-normalized API; commonly filtered/grouped in error queries)

Note on `endpoint` cardinality: if the application logs raw paths with embedded IDs (e.g., `/users/123` instead of `/users/:id`), normalize the path before ingestion. The default classification is **tag**.

### Canonical field examples

- `response_time_ms`, `bytes_sent` (numeric measurements)
- `user_agent`, `request_id` (unbounded cardinality — never tags)

### 6. Example Schemas

**IoT sensor data:**

```
sensors,device_id=d001,location=factory-a,type=temperature value=23.5 1714000000000000000
sensors,device_id=d001,location=factory-a,type=humidity value=45.2 1714000000000000000
```

**Application metrics:**

```
http_requests,method=GET,endpoint=/api/users,status=200 response_time=45.2,bytes=1024 1714000000000000000
```

**Infrastructure monitoring:**

```
cpu,host=web-01,region=us-east-1 usage_user=23.5,usage_system=5.2,usage_idle=71.3 1714000000000000000
```
