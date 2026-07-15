# RDS for MariaDB

- **Docs**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_MariaDB.html
- **Docs (llms.txt)**: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/llms.txt
- **Data model**: Relational (community MariaDB)
- **Query language**: MariaDB SQL (MySQL-compatible with extensions)
- **Compatibility**: MariaDB (10.6, 10.11), MySQL-compatible but diverging (new features like system-versioned tables, Oracle-mode PL/SQL)
- **Serverless**: No (fixed instance types)
- **Scale to zero**: No
- **VPC required**: Yes
- **Multi-region**: Cross-region read replicas (async)
- **Free Tier**: new-account AWS Free Tier — $100 in credits at sign-up plus up to $100 more ($200 total), usable across eligible services including RDS/Aurora for up to 12 months
- **Min cost**: $0 (free tier) → ~$15/month after
- **Time to first query**: 10-15 min (VPC + instance + configuration)
- **Key features**: System-versioned (temporal) tables, Oracle PL/SQL compatibility mode, Aria storage engine, reserved instances (up to 60% off), full portability
- **Limitations**: No auto-scaling compute, no serverless, smaller managed-tooling footprint than MySQL/PostgreSQL on AWS, no Aurora equivalent
- **Best for**: MariaDB migrations, teams using MariaDB-specific features (temporal tables, Oracle mode), open-source MySQL alternative without Oracle ownership
- **Not for**: Variable traffic needing auto-scaling, new apps without MariaDB requirement (Aurora MySQL or Aurora PostgreSQL are better starting points)
