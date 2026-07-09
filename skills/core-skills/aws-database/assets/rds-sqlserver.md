# RDS for SQL Server

- **Docs**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_SQLServer.html
- **Docs (llms.txt)**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/llms.txt
- **Data model**: Relational (Microsoft SQL Server)
- **Query language**: T-SQL
- **Compatibility**: SQL Server (Express, Web, Standard, Enterprise editions)
- **Serverless**: No (fixed instance types)
- **Scale to zero**: No
- **VPC required**: Yes
- **Multi-region**: Cross-region read replicas (Enterprise Edition)
- **Free Tier**: 12 months (750 hrs/month db.t3.micro, Express Edition + 20 GB)
- **Min cost**: $0 (free tier, Express) → ~$50/month (Web) → ~$500/month (Standard)
- **Time to first query**: 15-20 min (VPC + instance + SQL Server configuration)
- **Key features**: SQL Server features (SSRS, SSIS, SQL Agent jobs), Windows Authentication, automated backups, Multi-AZ with Always On
- **Limitations**: Microsoft licensing cost (License Included or BYOM), no serverless, Windows-centric tooling
- **Best for**: Lift-and-shift SQL Server migrations, .NET applications, teams with T-SQL expertise and existing licenses
- **Not for**: New applications (use Aurora PostgreSQL or DSQL), cost-sensitive workloads, teams looking to move off commercial licensing (that's a refactor)
