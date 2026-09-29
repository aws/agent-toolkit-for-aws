# Timestream for InfluxDB

- **Docs**: https://docs.aws.amazon.com/timestream/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/timestream/latest/developerguide/llms.txt
- **Data model**: Time-series (measurements, tags, fields, timestamps — line protocol)
- **Query language**: SQL + InfluxQL (v3); Flux + InfluxQL (v2)
- **Compatibility**: InfluxDB wire protocol (Telegraf, Grafana, Flight SQL)
- **Serverless**: No (instance/cluster-based)
- **Scale to zero**: No
- **VPC required**: Yes (private by default; public opt-in)
- **Multi-region**: No
- **Free Tier**: No
- **Min cost**: ~$95/month (db.influx.medium, on-demand)
- **Time to first query**: ~15-25 min (instance provisioning)
- **Engine variants**: InfluxDB 2 (single-node/read replica, Flux, port 8086), InfluxDB 3 Core/Enterprise (multi-node, SQL, port 8181)
- **Key features**: Built-in UI (v2), Flux task engine (v2), Telegraf integration (v2), org/bucket multi-tenancy (v2), read replicas for read scaling (v2), unlimited cardinality (v3), Processing Engine with Python plugins (v3), S3-backed Parquet storage (v3), horizontal scaling up to 15 nodes (v3), open data format — Parquet/Iceberg (v3)
- **Limitations**: No scale to zero; cardinality degrades above ~10M series (v2), no SQL (v2), no horizontal write scaling (v2), max practical storage ~2TB (v2), no Flux — queries must be rewritten (v3), no built-in UI (v3)
- **Best for**: High-frequency IoT telemetry, DevOps/infrastructure metrics, industrial sensor data, satellite telemetry, financial time-series, high-cardinality workloads (>10M series) (v3), SQL analytics over time-series (v3), self-hosted InfluxDB migration (v2)
- **Not for**: General-purpose relational data, workloads needing JOINs/transactions, sub-millisecond key-value lookups, workloads needing $0 idle cost
