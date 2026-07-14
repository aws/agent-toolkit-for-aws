# Aurora MySQL

- **Docs**: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.AuroraMySQL.html
- **Docs (llms.txt)**: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/llms.txt
- **Data model**: Relational (full MySQL)
- **Query language**: MySQL SQL
- **Compatibility**: Full MySQL
- **Serverless**: Yes
- **Serverless type**: Capacity — you still create and manage a cluster, but compute scales automatically (including to zero with auto-pause)
- **Scale to zero**: Yes, via auto-pause
- **VPC required**: Yes (no Express Configuration for MySQL)
- **Multi-region**: Global Database for disaster recovery
- **Free Tier**: new-account AWS Free Tier — $100 at sign-up plus up to $100 more ($200 total), usable across eligible services including Aurora for up to 12 months (per aws.amazon.com/rds/aurora/pricing). Note: the named "Free plan" 4-ACU/1-GiB-per-cluster allowance is documented for Aurora PostgreSQL serverless; MySQL workloads draw on the same credits
- **Min cost**: ~$0 with auto-pause; ~$45/month always-on at 0.5 ACU (compute only; storage billed separately)
- **Time to first query**: 10-15 min (VPC + cluster setup)
- **Key features**: Serverless, Global Database, I/O-Optimized, parallel query
- **Migration tooling**: Aurora MySQL power for Kiro (AI-assisted RDS MySQL → Aurora MySQL migration via the Kiro IDE; a migration aid, not an engine feature)
- **Limitations**: No Express Configuration, no pgvector equivalent
- **Best for**: Existing MySQL workloads, teams with MySQL expertise
- **Not for**: New apps without MySQL requirement
