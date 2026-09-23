# DynamoDB — Startup-Specific Guidance

## When Startups Should Choose DynamoDB

**DynamoDB is the right default database for startups when:**

- Your data model is key-value or document-oriented (user profiles, sessions, IoT telemetry, orders)
- You need single-digit millisecond latency at any scale
- You want zero operational overhead (no patching, scaling, backups to manage)
- Your access patterns are known upfront (this is critical — DynamoDB punishes query pattern changes)

**DynamoDB is the WRONG choice when:**

- You don't know your access patterns yet (early prototyping with ad-hoc queries → use PostgreSQL)
- You need complex joins, aggregations, or flexible queries → use PostgreSQL/Aurora
- Your data is highly relational with many-to-many relationships → use PostgreSQL
- You need full-text search → use OpenSearch or PostgreSQL with pg_trgm

## The Access Pattern Lock-in Problem

This is the #1 DynamoDB mistake startups make: choosing DynamoDB for operational simplicity, then discovering 6 months later that a new feature requires a query pattern the table design doesn't support.

**Mitigation**: Before committing to DynamoDB, write down your top 10 access patterns. If you can't, you don't know enough about your product to choose DynamoDB. Use PostgreSQL/Aurora until patterns stabilize, then migrate hot paths to DynamoDB.

## Startup Cost Traps

1. **On-Demand mode at scale without noticing**: On-Demand is correct at the start (zero cost at zero traffic). But at sustained load, it's 5-7x more expensive than provisioned. **Trigger to switch**: when your DynamoDB bill exceeds $100/month with predictable traffic patterns, switch to provisioned with auto-scaling.

2. **GSI proliferation**: Each GSI copies all projected attributes and consumes write capacity on every write to the base table. Startups add GSIs reactively ("we need to query by email too") without budgeting the cost. At 5+ GSIs with full projections, you may be paying 5x your base table cost in GSI writes.

3. **Scan-based "analytics"**: Teams build admin dashboards that Scan the entire table. At 1M items, a full Scan costs ~$1.25 and takes seconds. At 100M items, it's $125 per scan. Export to S3 + Athena for analytics — never Scan production tables repeatedly.

4. **DAX when you don't need it**: DAX clusters start at ~$50/month (t3.small) and require VPC placement. Don't add DAX until you've confirmed: (a) reads are the bottleneck, (b) the same items are read repeatedly, (c) eventual consistency is acceptable. Most startups don't need DAX.

5. **DynamoDB Streams + Lambda at high volume**: Each Lambda invocation from Streams counts against your Lambda concurrent execution limit AND costs per invocation. At 10K writes/second, that's 10K Lambda invocations/second. Use Kinesis Data Streams as the consumer if write volume is high.

## Stage-Specific Recommendations

### Pre-PMF (validating product)

- **Use On-Demand mode** — zero cost at zero traffic, scales automatically
- **Simple key design**: don't over-engineer single-table design at this stage. One table per entity is fine (users table, orders table). Optimize later.
- **Enable Point-in-Time Recovery** ($0.20/GB-month) — your only protection against accidental deletes
- Total cost at low traffic: $0-5/month

### Post-PMF (scaling, Series A)

- Switch predictable tables to **Provisioned + Auto-Scaling** (target 70% utilization)
- Consider single-table design for entities that transact together
- Add DynamoDB Streams for event-driven patterns (materialized views, search indexing)
- Export to S3 for analytics instead of Scanning

### Scale (Series B+, >$1K/month DynamoDB)

- Reserved capacity (1-year or 3-year) for base throughput — up to 77% savings
- Evaluate Global Tables only if you genuinely need multi-region writes
- DAX for read-heavy hot key patterns
- Consider moving some tables to Aurora if query flexibility is needed

## Counterintuitive Startup Advice

- **Don't do single-table design at the start.** It's an optimization for scale and reduced table management. At pre-PMF with 2-3 entities, separate tables are more readable, easier to reason about, and trivial to change. Single-table design is a one-way door that's painful to refactor.

- **DynamoDB is often MORE expensive than Aurora for typical CRUD apps.** A startup with a standard web app (users, posts, comments, likes) paying $50/month for a `db.t4g.micro` Aurora Serverless v2 instance would pay $200+/month for the same data in DynamoDB with GSIs for all query patterns. DynamoDB wins on latency and ops burden, not on cost for relational-shaped data.

- **Free tier covers you longer than you think.** DynamoDB free tier (25 RCU, 25 WCU, 25 GB) is permanent and enough for ~200 reads/sec and ~25 writes/sec. Most pre-PMF startups never exceed this.

## When to Graduate FROM DynamoDB

| Signal                                                         | Direction                                   |
| -------------------------------------------------------------- | ------------------------------------------- |
| Constantly needing new GSIs for new features                   | Your data is relational — use PostgreSQL    |
| Admin dashboards Scanning tables                               | Export to S3, query with Athena             |
| Need full-text search                                          | Add OpenSearch (or use PostgreSQL)          |
| Monthly bill > $500 with Reserved Capacity still too expensive | Data model mismatch — evaluate alternatives |

## Credits-Specific Guidance

- DynamoDB On-Demand costs are covered by credits. During credits: stay on On-Demand even if traffic is predictable — the flexibility is worth it while you're iterating on data models.
- When credits expire: On-Demand bills hit immediately. Switch to Provisioned + Auto-Scaling for any table with consistent traffic before credits run out.
- Point-in-Time Recovery and backups also count against credits — enable them generously during the credits period.
