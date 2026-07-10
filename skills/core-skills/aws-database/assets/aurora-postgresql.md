# Aurora PostgreSQL

- **Docs**: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.AuroraPostgreSQL.html
- **Docs (llms.txt)**: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/llms.txt
- **Data model**: Relational (full PostgreSQL)
- **Query language**: PostgreSQL SQL (full dialect + extensions)
- **Compatibility**: Full PostgreSQL (all extensions, stored procedures, triggers, FDWs)
- **Serverless**: Yes (Serverless, auto-scaling 0-256 ACU)
- **Serverless type**: Capacity — you still create and manage a cluster, but compute scales automatically (including to zero with auto-pause)
- **Scale to zero**: Yes, via auto-pause
- **VPC required**: Yes (unless Express Configuration — no VPC, PostgreSQL only, limited regions)
- **Multi-region**: Global Database for disaster recovery (<1s replication, single write region)
- **Free Tier**: new-account AWS Free Tier — $100 in credits at sign-up plus up to $100 more ($200 total), usable across eligible services including Aurora for up to 12 months. Free plan gives Aurora PostgreSQL serverless up to 4 ACUs and 1 GiB storage per cluster; upgrade to Paid for up to 256 ACUs / 256 TiB (per aws.amazon.com/rds/aurora/pricing)
- **Min cost**: ~$0 with auto-pause (storage only); ~$45/month always-on at 0.5 ACU (compute only; storage billed separately)
- **Time to first query**: ~90-120 seconds (Express Configuration) or 10-15 min (standard VPC setup)
- **Key features**: Express Configuration, I/O-Optimized, Managed Upgrades with Blue/Green Deployments, AWS Organizations for upgrade rollout policy, PostgreSQL extensions including pgvector, dynamic data masking (pg_columnmask), PostGIS, Zero ETL integrations to Redshift and Opensearch, up to 5x write and 3x read throughput vs RDS, faster failover (<30s vs 60-120s for RDS Multi-AZ)
- **Limitations**: Single write region, slightly higher cost than RDS for equivalent instance size, proprietary storage layer (not portable to community PostgreSQL without application-level export)
- **Best for**: Workloads requiring full PostgreSQL, pgvector/AI embeddings, migrations from PostgreSQL, refactors from Oracle/SQL Server
- **Not for**: Users who just need simple SQL without PG-specific features (DSQL is simpler)
