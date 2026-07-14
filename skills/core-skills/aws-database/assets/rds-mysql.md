# RDS for MySQL

- **Docs**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_MySQL.html
- **Docs (llms.txt)**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/llms.txt
- **Data model**: Relational (community MySQL)
- **Query language**: MySQL SQL (identical to community)
- **Compatibility**: IS community MySQL (not "compatible" — it IS MySQL)
- **Serverless**: No (fixed instance types)
- **Scale to zero**: No
- **VPC required**: Yes
- **Multi-region**: Cross-region read replicas (async)
- **Free Tier**: new-account AWS Free Tier — $100 in credits at sign-up plus up to $100 more ($200 total), usable across eligible services including RDS/Aurora for up to 12 months
- **Min cost**: $0 (free tier) → ~$15/month after
- **Time to first query**: 10-15 min (VPC + instance + configuration)
- **Key features**: All MySQL features, reserved instances (up to 60% off), full portability, Multi-AZ deployments
- **Limitations**: No auto-scaling compute, manual instance sizing, no serverless option
- **Best for**: Cost-sensitive MySQL workloads, portability priority, teams wanting standard MySQL with no proprietary layer
- **Not for**: Variable traffic needing auto-scaling (Aurora MySQL is better), new apps without MySQL requirement
