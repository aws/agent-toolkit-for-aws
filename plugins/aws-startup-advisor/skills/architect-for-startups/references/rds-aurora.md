# RDS & Aurora — Startup-Specific Guidance

## The Startup Database Decision

**PostgreSQL on Aurora Serverless v2 is the default database for startups.** It gives you:

- Familiar SQL with full query flexibility (critical when access patterns are unknown)
- Scale-to-near-zero (0.5 ACU minimum = ~$44/month)
- Auto-scaling during traffic spikes without capacity planning
- No DBA required until Series B

**Use plain RDS (not Aurora) when:**

- Budget is extremely tight — `db.t4g.micro` RDS PostgreSQL costs ~$12/month vs Aurora's $44/month minimum
- You need Oracle or SQL Server (Aurora doesn't support these)
- Your database will stay small (<50GB) with low connection counts

## Startup Cost Traps

1. **Aurora Serverless v2 minimum ACU cost**: Even "scaled to zero" isn't zero — minimum is 0.5 ACU = ~$44/month. For a side project or internal tool, plain RDS `db.t4g.micro` at $12/month is 4x cheaper. Use Aurora Serverless v2 when the auto-scaling justifies the minimum.

2. **Multi-AZ on day one**: Multi-AZ doubles your database cost. At pre-PMF with no revenue, single-AZ + automated daily snapshots is an acceptable risk. Your "HA plan" is: restore from snapshot (10-30 min downtime). Add Multi-AZ when you have paying customers with uptime expectations.

3. **RDS Proxy when you don't need it**: $18/month minimum per proxy. Only needed for Lambda→RDS connections (Lambda's connection storm problem). If your app uses containers with connection pooling (HikariCP, pgBouncer), skip RDS Proxy entirely.

4. **Oversized instances "for headroom"**: Startups provision `db.r6g.large` ($140/month) when `db.t4g.medium` ($48/month) with 2 vCPU/4GB handles their workload fine. Start with the smallest `t4g` class that has enough memory for your working set. Upsize takes <10 minutes with minimal downtime.

5. **Read replicas before you need them**: Each Aurora read replica adds ~$44/month minimum. Don't add replicas until: (a) you've confirmed reads are the bottleneck via Performance Insights, and (b) your read traffic exceeds what the writer can handle. Most startups need 0 read replicas until post-Series A.

6. **Snapshot retention at 35 days**: Default is 7 days, but teams set 35 days "for safety." At 100GB database, that's ~$23/month in backup storage vs ~$5/month for 7 days. Right-size retention to your actual compliance needs.

## Stage-Specific Recommendations

### Pre-PMF (minimal spend, maximum flexibility)

- **RDS PostgreSQL `db.t4g.micro`** (~$12/month) OR **Aurora Serverless v2** (0.5 ACU, ~$44/month)
- Single-AZ, automated daily snapshots
- `gp3` storage (20GB minimum, auto-extends)
- No read replicas, no RDS Proxy
- Password in Secrets Manager with `--manage-master-user-password`
- Total cost: $12-50/month

### Post-PMF / Series A (real users, need reliability)

- **Aurora Serverless v2** with 0.5-8 ACU range (handles spikes without pre-provisioning)
- Enable Multi-AZ (add one reader in a second AZ — doubles as HA AND read scaling)
- Enable Performance Insights (free tier covers 7 days retention)
- Add RDS Proxy only if using Lambda for API handlers
- Enable deletion protection
- Total cost: $100-300/month

### Scale (Series B+, >$500/month database)

- Evaluate Aurora Provisioned vs Serverless v2 — provisioned is cheaper for sustained high load
- Aurora Global Database if you need multi-region reads or DR
- Blue/Green deployments for zero-downtime major version upgrades
- Consider Reserved Instances for Aurora provisioned (1-year, up to 30% savings)

## Counterintuitive Startup Advice

- **Start with RDS, not Aurora.** Aurora's $44/month minimum seems trivial, but at pre-PMF you might have 5 services each needing a database. 5 × $44 = $220/month. 5 × RDS `db.t4g.micro` = $60/month. Migrate to Aurora when a specific database needs auto-scaling storage or high availability.

- **PostgreSQL, always PostgreSQL.** Even if your team knows MySQL better. PostgreSQL has: better JSON support (replace MongoDB), full-text search (replace Elasticsearch for simple cases), PostGIS (location queries), and a richer extension ecosystem. This flexibility reduces the number of databases you need.

- **Single-AZ is fine until you have SLAs.** The "always use Multi-AZ in production" guidance assumes production means "paying customers with contractual uptime." If your production means "100 beta users who'll understand 10 minutes of downtime," save the money.

- **Connection pooling in your app, not RDS Proxy.** PgBouncer sidecar or built-in pooling (HikariCP for Java, Prisma for Node.js) is free and runs co-located with your app. RDS Proxy's value is specifically for Lambda's thousands-of-ephemeral-connections problem.

## When to Evaluate Alternatives

| Signal                                                     | Direction                                              |
| ---------------------------------------------------------- | ------------------------------------------------------ |
| Single table with >10K writes/sec, simple key-value access | DynamoDB for that table                                |
| Need sub-10ms reads on hot data                            | DynamoDB or ElastiCache in front of Aurora             |
| Full-text search beyond PostgreSQL's capabilities          | OpenSearch for search, keep Aurora as source of truth  |
| Time-series data (metrics, IoT) growing unbounded          | Timestream or InfluxDB                                 |
| Monthly database cost > $2K, mostly reads                  | Consider read replicas + Aurora Global if multi-region |

## Credits-Specific Guidance

- RDS/Aurora instance hours are covered by credits. During credits: use Aurora Serverless v2 with a generous ACU range — let it auto-scale without worrying about cost.
- **Critical warning**: when credits expire, Aurora Serverless v2 with a 0.5-64 ACU range can surprise you with a $500+ first bill if it scaled up during a traffic spike. Set `max ACU` conservatively (4-8 ACU) unless you know your peak load.
- Multi-AZ costs double — enable during credits to test failover behavior, but be aware it doubles your post-credits cost.
- Snapshot storage accumulates outside of instance costs. Clean up manual snapshots before credits expire.
