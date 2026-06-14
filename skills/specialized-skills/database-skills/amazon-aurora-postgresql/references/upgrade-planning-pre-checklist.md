# Pre-Upgrade Checklist

## Common Steps (Both Engines)

1. **Create test environment via snapshot restore**

   ```bash
   aws rds create-db-cluster-snapshot --db-cluster-identifier {cluster} \
     --db-cluster-snapshot-identifier {cluster}-pre-upgrade-snapshot --region {region}
   aws rds restore-db-cluster-from-snapshot --db-cluster-identifier {cluster}-upgrade-test \
     --snapshot-identifier {cluster}-pre-upgrade-snapshot \
     --engine {engine} --engine-version {target_version} --region {region}
   ```

2. **Review and create new parameter group**

   ```bash
   aws rds describe-db-cluster-parameters --db-cluster-parameter-group-name {current_pg} \
     --query "Parameters[?Source=='user' && ParameterValue!=null].{Name:ParameterName,Value:ParameterValue}" \
     --output table --region {region}
   ```

   Create new group for target version family and apply custom parameters.

3. **Check pending maintenance actions**

   ```bash
   aws rds describe-pending-maintenance-actions \
     --resource-identifier arn:aws:rds:{region}:{account}:cluster:{cluster} --region {region}
   ```

4. **Capture baseline performance metrics** — CloudWatch: CPUUtilization, DatabaseConnections, ReadLatency, WriteLatency, FreeableMemory, BufferCacheHitRatio. Save EXPLAIN plans for critical queries.

5. **Consider Blue/Green Deployments** for minimal downtime. Ref: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/blue-green-deployments.html

6. **Plan maintenance window** — schedule during lowest traffic (use Performance Insights).

## Aurora PostgreSQL-Specific

1. **Check extension compatibility** with target version.

2. **Review PostgreSQL release notes** for each major version between current and target:
   - PG 14: https://www.postgresql.org/docs/14/release-14.html
   - PG 15: https://www.postgresql.org/docs/15/release-15.html
   - PG 16: https://www.postgresql.org/docs/16/release-16.html
   - PG 17: https://www.postgresql.org/docs/17/release-17.html

3. **Check encoding/locale compatibility** with target.

4. **Test on snapshot-restored cluster** — Aurora handles pg_upgrade internally.

5. **Check objects owned by rdsadmin** — can block upgrades.

6. **Drop unused logical replication slots** — active slots block major upgrades.
