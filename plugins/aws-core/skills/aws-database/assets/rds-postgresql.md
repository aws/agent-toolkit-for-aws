# RDS for PostgreSQL

- **Docs**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html
- **Docs (llms.txt)**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/llms.txt
- **Data model**: Relational (community PostgreSQL)
- **Query language**: PostgreSQL SQL (identical to community)
- **Compatibility**: IS community PostgreSQL (not "compatible" — it IS PostgreSQL)
- **Serverless**: No (fixed instance types)
- **Scale to zero**: No
- **VPC required**: Yes
- **Multi-region**: Cross-region read replicas (async)
- **Free Tier**: new-account AWS Free Tier — $100 in credits at sign-up plus up to $100 more ($200 total), usable across eligible services including RDS/Aurora for up to 12 months.
- **Min cost**: $0 (free tier) → ~$15/month after
- **Time to first query**: 10-15 min (VPC + instance + configuration)
- **Key features**: PostgreSQL extensions including pgvector and PostGIS, Managed Upgrades with Blue/Green Deployments, AWS Organizations for upgrade rollout policy, High availability and disaster recovery options such as Multi-AZ instances, delayed read replicas, Zero ETL integrations to Redshift
- **Limitations**: Manual instance sizing, no serverless, slower failover than Aurora
- **Best for**: Cost-sensitive workloads, teams wanting standard community PostgreSQL with full portability
- **Not for**: Variable traffic workloads needing auto-scaling
