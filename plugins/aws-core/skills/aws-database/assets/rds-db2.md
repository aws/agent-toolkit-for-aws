# RDS for Db2

- **Docs**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_Db2.html
- **Docs (llms.txt)**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/llms.txt
- **Data model**: Relational (IBM Db2)
- **Query language**: Db2 SQL
- **Compatibility**: IBM Db2 (Community Edition, Standard Edition, Advanced Edition)
- **Serverless**: No (fixed instance types)
- **Scale to zero**: No
- **VPC required**: Yes
- **Multi-region**: Cross-region read replicas using HADR (active-passive DR)
- **Free Tier**: None
- **Min cost**: ~$25/month (Community Edition License Included, db.t3.small)
- **Time to first query**: 15-20 min (VPC + instance + Db2 configuration)
- **Key features**: IBM Db2 compatibility, automated backups, Multi-AZ, Db2-native tools support
- **Limitations**: IBM licensing cost, no serverless, smaller community than PostgreSQL/MySQL
- **Best for**: Lift-and-shift Db2 migrations, mainframe modernization first step, teams with Db2 expertise and existing licenses (BYOL)
- **Not for**: New applications (use Aurora PostgreSQL or DSQL), cost-sensitive workloads, teams looking to move off commercial licensing (that's a refactor)
