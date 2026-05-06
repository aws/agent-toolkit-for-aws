# Reserved Instances

## RI Types

| Type | Discount | Flexibility | Marketplace |
|------|----------|-------------|-------------|
| Standard | Up to 72% | Size flexibility within family (regional) | Can sell |
| Convertible | Up to 66% | Can exchange for different family/size/OS | Cannot sell |

## Payment Options
All Upfront (highest discount) > Partial Upfront > No Upfront (lowest discount).

## Break-Even Points

- 1-year RI: typically 7-10 months
- 3-year RI: typically 10-14 months

## Size Flexibility (Regional RIs)

Regional RIs (both Standard and Convertible) automatically apply across instance sizes within the same family using normalization factors. Example: 1 c5.xlarge RI covers 2 c5.large instances. AZ-scoped RIs provide capacity reservation but NO size flexibility.

## Application Order
RIs apply first, then Savings Plans cover remaining eligible usage.

## Service-Specific Considerations

**EC2:** Available for Linux, RHEL, SUSE, Windows. Regional or zonal. Size flexibility within family (except dedicated tenancy).

**RDS:** Available for MySQL, PostgreSQL, MariaDB, Oracle, SQL Server, Aurora. Size flexibility within family. Automatically applied to Multi-AZ deployments.

**ElastiCache:** Redis/Valkey and Memcached. Redis/Valkey reserved nodes support size flexibility within family. Memcached reserved nodes do not.

**OpenSearch:** Specific instance types in specific regions. No size flexibility. Cannot sell on Marketplace.

**Redshift:** Specific node types in specific regions.

## CLI Commands

```bash
# RI utilization
aws ce get-reservation-utilization \
  --time-period Start=2026-03-01,End=2026-04-01 \
  --granularity MONTHLY

# RI purchase recommendations
aws ce get-reservation-purchase-recommendation \
  --service "Amazon Elastic Compute Cloud - Compute" \
  --term-in-years ONE_YEAR \
  --payment-option NO_UPFRONT \
  --lookback-period-in-days SIXTY_DAYS

# RI coverage
aws ce get-reservation-coverage \
  --time-period Start=2026-03-01,End=2026-04-01 \
  --granularity MONTHLY
```

## Gotchas

- Standard RIs can be sold on Marketplace; Convertible cannot
- Regional RIs provide size flexibility; AZ-scoped provide capacity reservation — pick one
- DynamoDB Reserved Capacity is deprecated — use Database Savings Plans instead
- RI modifications (splitting/merging) don't change the term or payment — only the instance count and AZ
