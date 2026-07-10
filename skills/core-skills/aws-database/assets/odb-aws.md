# Oracle Database@AWS (ODB@AWS)

- **Docs**: https://docs.aws.amazon.com/odb/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/odb/latest/userguide/llms.txt
- **Data model**: Relational (Oracle Database, full feature set including RAC)
- **Query language**: Oracle SQL, PL/SQL
- **Compatibility**: Full Oracle Database (Enterprise Edition, RAC, Data Guard, all options)
- **Serverless**: Yes (Oracle Autonomous Database on Serverless); dedicated Exadata infrastructure also available
- **Scale to zero**: Near zero (serverless)
- **VPC required**: Yes (runs in customer VPC on Oracle-managed Exadata in AWS data centers)
- **Multi-region**: Oracle Data Guard (active-passive DR)
- **Free Tier**: None
- **Min cost**: ~$140/month (Standard Edition serverless); dedicated infrastructure starts ~$10k/month (Exadata + Oracle licensing, enterprise pricing)
- **Time to first query**: Minutes (serverless) to hours/days (dedicated infrastructure provisioning)
- **Key features**: Full Oracle Database feature parity (RAC, Data Guard, RMAN, ASM, Multitenant), runs in AWS data centers with low-latency access to other AWS services, managed by Oracle, BYOL or License Included
- **Limitations**: Oracle licensing cost, Exadata-only (no small instances), complex setup, managed by Oracle (not AWS), limited to regions with ODB@AWS availability
- **Best for**: Enterprise Oracle workloads requiring Exadata and/or RAC capabilities, Oracle-to-cloud migrations where RDS for Oracle feature gaps are blockers, consolidation of Oracle estates onto cloud infrastructure
- **Not for**: New applications, teams looking to move off commercial licensing (that's a refactor to Aurora PostgreSQL)
