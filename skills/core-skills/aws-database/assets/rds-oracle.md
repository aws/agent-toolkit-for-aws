# RDS for Oracle

- **Docs**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_Oracle.html
- **Docs (llms.txt)**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/llms.txt
- **Data model**: Relational (Oracle Database)
- **Query language**: Oracle SQL, PL/SQL
- **Compatibility**: Oracle Database (Standard Edition 2, Enterprise Edition)
- **Serverless**: No (fixed instance types)
- **Scale to zero**: No
- **VPC required**: Yes
- **Multi-region**: Cross-region read replicas (Enterprise Edition); cross-region automated backups for multi-region DR (Standard Edition 2)
- **Free Tier**: None
- **Min cost**: ~$55/month (BYOL, db.t3.small) or ~$85/month (License Included, db.t3.small)
- **Time to first query**: 15-20 min (VPC + instance + Oracle configuration)
- **Key features**: Oracle Database features (Data Guard, Multitenant, Partitioning, Advanced Compression, APEX, TDE, JVM; RAC not supported on RDS), automated backups, Multi-AZ, monitoring with CloudWatch and Database Insights, Oracle-native tools compatibility
- **Limitations**: Oracle licensing cost, no RAC (use ODB@AWS for RAC), no serverless
- **Best for**: Lift-and-shift Oracle migrations where the database cannot be modernized to Aurora right away. Teams with Oracle expertise but wanting to offload their operational burden with a fully-managed service.
- **Not for**: New applications (use Aurora PostgreSQL or DSQL), cost-sensitive workloads, teams looking to move off commercial licensing (that's a refactor to Aurora PostgreSQL)
