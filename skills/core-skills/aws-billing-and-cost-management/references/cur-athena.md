# CUR and AWS Data Exports

## Which Report Format?

AWS has three billing data formats. Determine which the customer is using before writing queries:

| Format | Table Name | Status | Key Differences |
|--------|-----------|--------|-----------------|
| **CUR 2.0** | `COST_AND_USAGE_REPORT` | Recommended | Fixed schema, nested columns (`resource_tags`, `cost_category`, `product`, `discount` are key-value maps), Parquet/GZIP only. Created via AWS Data Exports. |
| **Legacy CUR** | User-defined | Still supported, no deprecation planned | Dynamic schema (columns vary monthly based on usage), tags/categories as separate columns (e.g., `resource_tags_user_creator`), supports CSV/ZIP/GZIP/Parquet. Created via CUR console or API. |
| **FOCUS 1.2** | `FOCUS_1_2_AWS` | GA | FinOps Open Cost and Usage Specification — cloud-agnostic schema for multi-cloud FinOps. Different column names entirely (e.g., `BilledCost`, `EffectiveCost`, `ServiceName`). Created via AWS Data Exports. |

**How to tell which format a customer has:** Ask, or check the Data Exports console. If they reference `billing_period` as a string column, they're likely on Legacy CUR. If they reference `bill_billing_period_start_date` as a timestamp, they're on CUR 2.0.

**Key query differences between Legacy CUR and CUR 2.0:**

- **Billing period filter:** Legacy CUR uses `billing_period = '2026-03'` (string). CUR 2.0 uses `bill_billing_period_start_date = TIMESTAMP '2026-03-01'` (timestamp).
- **Tags:** Legacy CUR CSV has `resource_tags_user_<tagname>` as separate columns. CUR 2.0 nests all tags into a `resource_tags` map column — query with `resource_tags['user:tagname']`.
- **Product attributes:** Legacy CUR has `product_<attribute>` as separate columns. CUR 2.0 nests into `product` map — query with `product['attribute']`.
- **Table name:** Legacy CUR uses whatever name the customer chose. CUR 2.0 is always `COST_AND_USAGE_REPORT`.

## Setup (CUR 2.0)

```bash
aws bcm-data-exports create-export --export '{
  "Name":"MyCUR2Export",
  "DataQuery":{"QueryStatement":"SELECT * FROM COST_AND_USAGE_REPORT",
    "TableConfigurations":{"COST_AND_USAGE_REPORT":{"TIME_GRANULARITY":"DAILY","INCLUDE_RESOURCES":"TRUE"}}},
  "DestinationConfigurations":{"S3Destination":{"S3Bucket":"my-cur-bucket","S3Prefix":"cur2","S3Region":"us-east-1",
    "S3OutputConfigurations":{"OutputType":"CUSTOM","Format":"PARQUET","Compression":"PARQUET","Overwrite":"OVERWRITE_REPORT"}}},
  "RefreshCadence":{"Frequency":"SYNCHRONOUS"}}'
```

Always use PARQUET — 10-100x cheaper Athena queries than CSV. Set `INCLUDE_RESOURCES=TRUE` only if per-resource analysis needed (dramatically increases data volume).

## Key Column Groups

| Group | Key Columns | Use |
|-------|-------------|-----|
| line_item | `unblended_cost`, `resource_id`, `product_code`, `usage_amount` | Core cost data |
| savings_plan | `savings_plan_effective_cost`, `savings_plan_a_r_n` | SP analysis |
| reservation | `reservation_a_r_n`, `effective_cost`, `unused_quantity` | RI analysis |
| pricing | `public_on_demand_cost`, `public_on_demand_rate` | On-demand comparison |
| resource_tags | **Legacy CUR:** `resource_tags_user_<tagname>` columns; **CUR 2.0:** `resource_tags` map — query with `resource_tags['user:tagname']` | Tag-based allocation |

## Common Athena Queries

CUR 2.0 uses `bill_billing_period_start_date` as a TIMESTAMP column, not a string. Filter with `TIMESTAMP` literal or `date_trunc`:

```sql
-- Monthly cost by service
SELECT line_item_product_code AS service, SUM(line_item_unblended_cost) AS cost
FROM cost_and_usage_report
WHERE bill_billing_period_start_date = TIMESTAMP '2026-03-01'
GROUP BY line_item_product_code ORDER BY cost DESC;

-- Top 10 most expensive resources
SELECT line_item_resource_id, line_item_product_code, SUM(line_item_unblended_cost) AS cost
FROM cost_and_usage_report
WHERE bill_billing_period_start_date = TIMESTAMP '2026-03-01' AND line_item_resource_id != ''
GROUP BY line_item_resource_id, line_item_product_code ORDER BY cost DESC LIMIT 10;

-- Data transfer breakdown (uses same regex patterns as cost-explorer.md)
SELECT line_item_product_code, line_item_usage_type,
  SUM(line_item_usage_amount) AS usage_gb, SUM(line_item_unblended_cost) AS cost
FROM cost_and_usage_report
WHERE bill_billing_period_start_date = TIMESTAMP '2026-03-01'
  AND (
    REGEXP_LIKE(line_item_usage_type,
      'DataTransfer|AWS-(In|Out)-Bytes|Bytes-(Internet|AWS)|CloudFront-.*-Bytes|DataXfer|-ABytes-')
    OR REGEXP_LIKE(line_item_usage_type,
      'NatGateway-Bytes|VpcEndpoint-Bytes|TransitGateway-Bytes')
    OR (line_item_usage_type LIKE '%DataProcessing-Bytes%'
        AND line_item_product_code = 'AWSELB')
  )
GROUP BY line_item_product_code, line_item_usage_type ORDER BY cost DESC;

-- SP effective rate vs on-demand
SELECT line_item_product_code,
  SUM(savings_plan_savings_plan_effective_cost) AS sp_cost,
  SUM(pricing_public_on_demand_cost) AS ondemand_cost,
  ROUND(1 - SUM(savings_plan_savings_plan_effective_cost) / NULLIF(SUM(pricing_public_on_demand_cost), 0), 3) AS savings_pct
FROM cost_and_usage_report
WHERE savings_plan_savings_plan_a_r_n IS NOT NULL
  AND bill_billing_period_start_date = TIMESTAMP '2026-03-01'
GROUP BY line_item_product_code;
```

## Gotchas

- **Confirm the report format first.** Legacy CUR and CUR 2.0 have different column names, filtering syntax, and table names. Queries written for one will fail on the other.
- **Service names differ between Cost Explorer and CUR.** Cost Explorer uses human-readable names (e.g., `Elastic Load Balancing`). CUR uses API-style product codes (e.g., `AWSELB`). Before writing filter queries, run `SELECT DISTINCT line_item_product_code` to discover available values. If a filtered query returns 0 results, check the product code first.
- CUR 2.0 table name is `COST_AND_USAGE_REPORT` (fixed) — not user-defined
- **Tags differ by format:** Legacy CUR uses `resource_tags_user_<tagname>` columns. CUR 2.0 uses `resource_tags['user:tagname']` map syntax. Neither matches Cost Explorer API, which uses the tag key directly.
- CUR data delivered to S3 up to 3 times daily — not real-time
- Current month CUR is incomplete until month closes — don't compare to Cost Explorer
- Tags activated after CUR creation require manual Athena table column addition

## Additional Resources

- **CUR Query Library** (Well-Architected Labs): https://wellarchitectedlabs.com/cost-optimization/cur_queries/ — curated SQL queries for common cost analysis tasks (data transfer, EC2, RDS, S3, Savings Plans, etc.). NOTE: These queries are written for Legacy CUR column names — adapt for CUR 2.0 if needed (see "Key query differences" above).
- **Data Transfer Cost Analysis Dashboard** (Well-Architected Labs): https://wellarchitectedlabs.com/cost/200_labs/200_enterprise_dashboards/3_create_data_transfer_cost_analysis_dashboard/ — pre-built QuickSight dashboard for data transfer analysis from CUR data.
- **CUR 2.0 column reference**: https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-cur2.html
- **FOCUS 1.2 column reference**: https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-focus-1-2-aws.html
