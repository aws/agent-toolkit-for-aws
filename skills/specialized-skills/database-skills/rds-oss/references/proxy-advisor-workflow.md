# RDS Proxy Advisor Workflow

Evaluate whether RDS Proxy is worth adding for an RDS MySQL, MariaDB, or PostgreSQL instance. Pulls live connection metrics, compares against `max_connections`, estimates proxy cost, identifies pinning risks, and produces a recommend / consider / not-recommended verdict. Read-only — does not create proxies.

## When This Applies

User mentions: "should I use RDS Proxy", "too many connections", "connection pooling RDS", "RDS Proxy pinning", "Lambda database connections", "RDS Proxy cost", "RDS Proxy for PostgreSQL/MySQL". Not for Aurora — Aurora has its own proxy considerations (Aurora Serverless interactions, Global Database).

## Tasks

### 1. Gather Instance Metrics

Pull connection data to assess whether proxy is needed.

**Constraints:**

- You MUST ask for the DB instance identifier and region upfront
- You MUST run `aws rds describe-db-instances` to get engine, instance class, and vCPU count
- You MUST pull CloudWatch metrics for the last 7 days from the `AWS/RDS` namespace:
  - `DatabaseConnections` (Average, Maximum; for p99 pass it via `--extended-statistics p99`, not `--statistics`) — current connection count on the DB
  - `CPUUtilization` (correlate connection spikes with CPU)
- If the user is considering migration **away** from an existing RDS Proxy, you MUST also pull these proxy metrics (`AWS/RDS` namespace, dimension `ProxyName`):
  - `ClientConnections` — frontend connections to the proxy
  - `DatabaseConnections` — backend connections the proxy holds (distinct from the DB-side metric)
  - `DatabaseConnectionsCurrentlySessionPinned` — the canonical pinning diagnostic; high values mean multiplexing is defeated
- You MUST determine `max_connections` for the instance class. The RDS default is roughly `LEAST({DBInstanceClassMemory/9531392}, 5000)`. Check the parameter group for overrides.

Example CLI to pull the DB-side connection metric:

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name DatabaseConnections \
  --dimensions Name=DBInstanceIdentifier,Value=<instance-id> \
  --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 --statistics Average Maximum \
  --region <region>
```

For proxy-side metrics, swap the dimension to `Name=ProxyName,Value=<proxy-name>`. For p99, drop `--statistics` and pass `--extended-statistics p99` instead.

- You MUST calculate connection utilization: `peak_connections / max_connections × 100`%

### 2. Assess Proxy Need

**Constraints:**

- You MUST categorize the result using these thresholds:
  - 🔴 **Recommended**: peak connections > 80% of `max_connections`, OR Lambda/serverless callers present
  - 🟡 **Consider**: peak connections 50–80% of `max_connections`, OR frequent connection churn (spiky workload)
  - 🟢 **Not recommended**: peak connections < 50% and stable connection patterns
- You MUST ask if the application uses Lambda or other serverless compute, because connection churn from cold starts is the primary RDS Proxy use case
- You MUST check whether the application already uses client-side connection pooling (PgBouncer, ProxySQL, HikariCP, etc.) — if it does and connections are healthy, proxy may add latency without benefit
- You MUST NOT recommend proxy on utilization metrics alone — low utilization with heavy Lambda churn still benefits from proxy

### 3. Check for Pinning Risks

Connect to the database or ask the user to run diagnostic queries to identify SQL patterns that cause proxy pinning.

**Constraints:**

- You MUST explain what pinning is: the proxy pins a frontend connection to a specific backend connection, preventing multiplexing — the proxy's core benefit
- For MySQL/MariaDB, check for patterns from [proxy-pinning-mysql.md](proxy-pinning-mysql.md)
- For PostgreSQL, check for patterns from [proxy-pinning-postgresql.md](proxy-pinning-postgresql.md)
- You MUST categorize pinning risk as High / Medium / Low
- If pinning risk is High, you MUST warn that proxy benefit will be significantly reduced and quantify where possible (e.g., "if >30% of connections pin, the multiplexing advantage is largely negated")
- For PostgreSQL: you MUST call out `SET search_path` as the most common high-pinning pattern (Django, Rails ORM defaults pin every connection). Recommend moving it to the proxy init query or parameter group default.
- For MySQL: you MUST call out server-side prepared statements as the most common high-pinning pattern (JDBC default). Recommend `useServerPrepStmts=false` or client-side prepared statements.
- When the user asks how to measure pinning in production, you MUST direct them to the CloudWatch metrics `DatabaseConnectionsCurrentlySessionPinned` and `ClientConnections` (`AWS/RDS` namespace, dimension `ProxyName`) and the RDS Proxy pinning log events. You MUST NOT fabricate a pinning-rate percentage when no live metrics have been pulled.

### 4. Estimate Cost

**Constraints:**

- You MUST calculate proxy cost based on vCPU count of the target instance. RDS Proxy pricing is **$0.015 per vCPU per hour** in us-east-1 (verify for other regions; pricing varies slightly).
- Monthly cost = `vCPUs × $0.015 × 730 hours`
- You MUST present cost alongside the benefit (connection multiplexing value, failover improvement ≈ 66% faster than direct)
- You MUST note that proxy adds ~5 ms latency per connection establishment — for latency-sensitive workloads with short connection lifetimes, this can matter

### 5. Special Cases

- **Already using PgBouncer in transaction mode:** RDS Proxy's multiplexing benefit is marginal. PgBouncer in transaction mode is actually more aggressive (no pinning on SET). RDS Proxy adds value for managed infrastructure, IAM auth, and Multi-AZ failover handling — but it's a "Consider", not a strong "Recommend".
- **TLS to the backend:** RDS Proxy enforces TLS between proxy and database by default — a security advantage over self-managed PgBouncer, which may not enforce backend TLS.
- **Advisory locks (PostgreSQL) or `GET_LOCK()` (MySQL):** High pinning — connection is pinned for the lock's entire hold time. Recommend replacing with application-level locking (Redis, DynamoDB).
- **LISTEN/NOTIFY (PostgreSQL):** Pins the backend. Replace with SQS/SNS/EventBridge if using proxy.

### 6. Present Recommendation

**Constraints:**

- You MUST present a clear verdict: Recommended / Consider / Not Recommended
- You MUST include: current connection utilization, pinning risk level, estimated monthly cost, and key tradeoffs
- You MUST NOT create an RDS Proxy — this workflow is advisory only
- You SHOULD reference [proxy-pinning-mysql.md](proxy-pinning-mysql.md) or [proxy-pinning-postgresql.md](proxy-pinning-postgresql.md) for the engine-specific pinning taxonomy

## Troubleshooting

- **No CloudWatch data**: Instance may be newly created. Ask user for expected connection patterns instead.
- **`max_connections` unclear**: Check parameter group with `aws rds describe-db-parameters`. If not custom, use the engine default formula based on instance memory.
- **User unsure about pinning**: Provide the diagnostic queries from the pinning references and ask them to run and paste results.
- **Multi-AZ with proxy**: Proxy handles failover automatically — additional benefit worth mentioning in the recommendation.
- **IAM auth required**: RDS Proxy is the supported path for IAM database authentication on RDS MySQL/PostgreSQL — mention as a benefit when applicable.

## References

- [proxy-pinning-mysql.md](proxy-pinning-mysql.md) — MySQL/MariaDB pinning patterns and diagnostics
- [proxy-pinning-postgresql.md](proxy-pinning-postgresql.md) — PostgreSQL pinning patterns, search_path gotcha, extended query protocol notes
